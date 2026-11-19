"""全量群/好友联系人同步：从 aiocqhttp(OneBot v11) 拉列表，落本地 JSON 快照。

参考 astrbot_plugin_moe_permission/sync.py 的成熟做法：
- 只取 aiocqhttp 平台（OneBot v11），其它平台跳过；
- WebUI 只读本地快照，不实时打 OneBot；同步由后台定时 + 手动触发；
- 每个平台/每类列表各自 try/except，失败不影响其它；超时用 asyncio.wait_for。

不依赖 astrbot 运行时类型（用鸭子类型），便于独立测试。
"""
from __future__ import annotations

import asyncio
import time
from typing import Any

try:
    from astrbot.api import logger
except ImportError:  # 独立测试环境降级
    import logging
    logger = logging.getLogger("moe_tts.contacts")

DEFAULT_TIMEOUT = 15.0


def iter_aiocqhttp_platforms(context) -> list:
    """从 context.platform_manager.platform_insts 里筛出 aiocqhttp 平台。"""
    try:
        pm = getattr(context, "platform_manager", None)
        insts = list(getattr(pm, "platform_insts", []) or [])
    except Exception:
        return []
    out = []
    for p in insts:
        try:
            meta = p.meta()
            name = str(getattr(meta, "name", "") or "")
            if name == "aiocqhttp":
                out.append(p)
        except Exception:
            continue
    return out


def _platform_id(p) -> str:
    try:
        return str(p.meta().id or "")
    except Exception:
        return ""


async def call_action(bot, action: str, timeout: float, **params) -> Any:
    return await asyncio.wait_for(bot.call_action(action, **params), timeout=timeout)


def normalize_friends(raw: Any) -> list[dict]:
    """get_friend_list → [{id, nickname, remark, name}]。"""
    out: list[dict] = []
    if not isinstance(raw, list):
        return out
    for it in raw:
        if not isinstance(it, dict):
            continue
        uin = str(it.get("user_id") or it.get("uin") or "").strip()
        if not uin:
            continue
        nickname = str(it.get("nickname") or "").strip()
        remark = str(it.get("remark") or "").strip()
        out.append({
            "id": uin,
            "nickname": nickname,
            "remark": remark,
            "name": remark or nickname or uin,
        })
    return out


def normalize_groups(raw: Any) -> list[dict]:
    """get_group_list → [{id, name, member_count, max_member_count}]。"""
    out: list[dict] = []
    if not isinstance(raw, list):
        return out
    for it in raw:
        if not isinstance(it, dict):
            continue
        gid = str(it.get("group_id") or "").strip()
        if not gid:
            continue
        name = str(it.get("group_name") or it.get("name") or "").strip()
        out.append({
            "id": gid,
            "name": name or f"群 {gid}",
            "member_count": it.get("member_count", 0),
            "max_member_count": it.get("max_member_count", 0),
        })
    return out


async def sync_contacts(context, store, *, timeout: float = DEFAULT_TIMEOUT) -> dict:
    """同步所有 aiocqhttp 平台的群与好友到 store 快照。

    返回 {ok, friends, groups, platforms, error, synced_at}。
    单个平台/单类列表失败只记录到 error，不抛异常、不影响其它。
    """
    platforms = iter_aiocqhttp_platforms(context)
    if not platforms:
        return {"ok": False, "friends": 0, "groups": 0, "platforms": 0,
                "error": "未发现 aiocqhttp 平台（仅支持 OneBot v11 拉取联系人）",
                "synced_at": ""}
    friends: dict[str, dict] = {}
    groups: dict[str, dict] = {}
    errors: list[str] = []
    for p in platforms:
        pid = _platform_id(p)
        try:
            bot = p.get_client()
        except Exception as e:  # noqa: BLE001
            errors.append(f"平台 {pid} 取客户端失败: {e}")
            continue
        # 好友
        try:
            raw = await call_action(bot, "get_friend_list", timeout)
            for item in normalize_friends(raw):
                item["platform"] = pid
                friends[item["id"]] = item  # 同 QQ 后者覆盖（多机器人去重）
        except Exception as e:  # noqa: BLE001
            errors.append(f"平台 {pid} 好友列表失败: {e}")
        # 群
        try:
            raw = await call_action(bot, "get_group_list", timeout)
            for item in normalize_groups(raw):
                item["platform"] = pid
                groups[item["id"]] = item
        except Exception as e:  # noqa: BLE001
            errors.append(f"平台 {pid} 群列表失败: {e}")

    synced_at = time.strftime("%Y-%m-%d %H:%M:%S")
    store.set_contacts(list(friends.values()), list(groups.values()),
                       synced_at=synced_at, platforms=len(platforms))
    ok = bool(friends or groups) or not errors
    return {
        "ok": ok,
        "friends": len(friends),
        "groups": len(groups),
        "platforms": len(platforms),
        "error": "；".join(errors)[:300],
        "synced_at": synced_at,
    }


class ContactsScheduler:
    """后台定时同步：启动后延时首拉，之后按间隔循环；手动同步共用一把锁。"""

    def __init__(self, context, store, *, interval_min: int = 30,
                 timeout: float = DEFAULT_TIMEOUT):
        self.context = context
        self.store = store
        self.interval_min = max(0, int(interval_min))
        self.timeout = float(timeout)
        self._lock = asyncio.Lock()
        self._task: asyncio.Task | None = None
        # contacts_meta 是 JsonStore 实例属性，取它的 .data（不要写成 contacts_meta()）
        self.last_result: dict = dict(store.contacts_meta.data)

    async def sync_once(self) -> dict:
        async with self._lock:
            try:
                result = await sync_contacts(self.context, self.store, timeout=self.timeout)
            except Exception as e:  # noqa: BLE001
                result = {"ok": False, "error": str(e)}
            self.last_result = result
            return result

    def start(self) -> None:
        if self.interval_min <= 0 or self._task is not None:
            return
        self._task = asyncio.create_task(self._loop())

    async def _loop(self) -> None:
        # 启动后先延时再首拉，避免拖慢插件初始化
        await asyncio.sleep(min(30, self.interval_min * 60))
        while True:
            await self.sync_once()
            await asyncio.sleep(max(60, self.interval_min * 60))

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
