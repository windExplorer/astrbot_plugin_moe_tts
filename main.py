"""萌萌语音 · AstrBot 语音合成插件入口。

接入 TaskHub 中转站（默认）或 tts_serve 网关，让机器人以可配置音色朗读回复。
触发方式：会话级开关 / 关键词 / 自动语音 / LLM 工具 / /语音 指令。

硬约束：文本绝不因发语音而丢失上下文（both 原文留链，voice_only 依赖 AstrBot
单独存 completion_text）；任何合成失败都不阻断文字消息。
"""
from __future__ import annotations

import asyncio
import importlib
import json
import os
import re
import sys
import time
import uuid

import astrbot.api.message_components as Comp

try:
    from astrbot.api.all import MessageChain
except ImportError:  # noqa: BLE001
    try:
        from astrbot.core.message.message_event_result import MessageChain
    except ImportError:  # noqa: BLE001
        from astrbot.api.message_components import MessageChain  # type: ignore
from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, filter
from astrbot.api.star import Context, Star, register

try:
    from astrbot.api.provider import LLMResponse
except Exception:  # noqa: BLE001
    LLMResponse = object  # type: ignore

# 热重载：必须从包内相对导入，且初始化时强制 reload 依赖模块，
# 否则从旧版本热更上来的实例 sys.modules 里是旧代码。
from . import server as server_mod
from . import store as store_mod
from . import textutil as textutil_mod
from . import translator as translator_mod
from . import tts_engine as engine_mod
from . import tts_api as tts_api_mod
from . import webapi as webapi_mod
from . import avatar as avatar_mod
from . import contacts as contacts_mod

PLUGIN_ID = "astrbot_plugin_moe_tts"

_RELOAD_MODULES = [
    "textutil", "store", "server", "translator", "avatar", "contacts", "tts_engine", "tts_api", "webapi",
]
_PKG = __package__ or PLUGIN_ID

SERVER_DOWN_TIP = "🎙️（语音服务暂时不可用，文字照常发送，稍后再试～）"
SERVER_BUSY_TIP = "🎙️（语音服务正忙，排队较多，这次先用文字回复啦～）"
LAST_LLM_TTL = 120.0


def _reload_sibling_modules() -> None:
    for name in _RELOAD_MODULES:
        full = f"{_PKG}.{name}"
        try:
            mod = sys.modules.get(full)
            if mod is not None:
                importlib.reload(mod)
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[moe_tts] 热重载模块 {name} 失败: {e}")


def _read_version() -> str:
    """版本号唯一来源：metadata.yaml（显式 UTF-8）。"""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "metadata.yaml")
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                m = re.match(r"^version:\s*(v?[0-9]+\.[0-9]+\.[0-9]+)", line)
                if m:
                    return m.group(1)
    except Exception:
        pass
    return "v0.1.0"


@register(PLUGIN_ID, "windExplorer", "萌萌语音：可配置音色的语音合成（TaskHub / tts_serve）", "0.1.0")
class MoeTtsPlugin(Star):
    def __init__(self, context: Context, config: dict | None = None):
        super().__init__(context)
        _reload_sibling_modules()
        # 保留 AstrBot 注入的插件配置对象（WebUI 保存配置要写回它并 save_config）。
        # 注意：绝不能用 context.get_config() 回退——那是全局 cmd_config.json，
        # 与插件自己的 data/config/<plugin>_config.json 无关，会把插件配置冲成空。
        self._injected_config = config if config is not None else {}
        self.config = self._injected_config
        self._version = _read_version()

        data_dir = self._data_dir()
        self.store = store_mod.PluginStore(data_dir)
        self.avatars = avatar_mod.AvatarCache(os.path.join(data_dir, "avatars"))
        self._group_name_pending: set = set()
        # 全量群/好友联系人同步（后台定时 + WebUI 手动）
        self.contacts_scheduler = contacts_mod.ContactsScheduler(
            self.context, self.store,
            interval_min=int(self.config.get("contacts_sync_interval_min", 30) or 30),
            timeout=float(self.config.get("contacts_sync_timeout_sec", 15) or 15),
        )
        self._server_file = os.path.join(data_dir, "servers.json")
        self._translate_file = os.path.join(data_dir, "translate_config.json")

        # 服务端列表（WebUI 单选启用），落盘在 servers.json，优先于配置
        servers = self._load_servers()
        if not servers:
            servers = list(self.config.get("servers") or [])
        self.router = server_mod.TTSRouter(
            servers,
            timeout=int(self.config.get("timeout", 250) or 250),
            max_retry=int(self.config.get("tts_max_retry", 1) or 0),
            retry_backoff=float(self.config.get("tts_retry_backoff", 0.5) or 0.5),
            cooldown_sec=float(self.config.get("tts_cooldown_sec", 30) or 30),
            queue_max_position=int(self.config.get("tts_queue_max_position", 8) or 0),
        )

        self.translator = translator_mod.Translator(
            self._translate_file, self._load_translate_cfg()
        )
        self.engine = engine_mod.TtsEngine(
            self.config, self.router, self.store, self.translator,
            concurrency=int(self.config.get("tts_concurrency", 1) or 1),
        )
        # 跨插件语音契约 tts.v1：其它插件通过 star_cls.api 取用（零依赖、失败不抛）。
        # 挂在 engine 构造之后，确保 api 调用的运行时对象都已就绪。
        self.api = tts_api_mod.TtsApi(self)

        # 每消息标记（防重复 / 关键词触发 / 音色覆盖）
        self._flags: dict[str, dict] = {}
        self._last_llm: dict[str, tuple[float, str]] = {}
        self._last_user_msg: dict[str, tuple[float, str]] = {}  # 用户原消息（按会话，跨钩子抑制判定）
        self._spoken_msgs: set = set()
        self._sent_texts: dict[str, float] = {}
        self._origin_tasks: dict[str, asyncio.Task] = {}
        self._CONFIG_GROUPS = self._build_config_groups()

    # ---------- 数据目录 ----------
    def _data_dir(self) -> str:
        plugin_dir = os.path.dirname(os.path.abspath(__file__))
        # <root>/data/plugins/<name>/ -> <root>/data/astrbot_plugin_moe_tts/
        external = os.path.join(
            os.path.dirname(os.path.dirname(plugin_dir)), PLUGIN_ID
        )
        for cand in (external, os.path.join(plugin_dir, "data")):
            try:
                os.makedirs(cand, exist_ok=True)
                probe = os.path.join(cand, ".writable_test")
                with open(probe, "w", encoding="utf-8") as f:
                    f.write("1")
                os.remove(probe)
                return cand
            except Exception:
                continue
        return os.path.join(plugin_dir, "data")

    def _load_servers(self) -> list[dict]:
        try:
            with open(self._server_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, list) else []
        except Exception:
            return []

    def _save_servers(self, servers: list[dict]) -> None:
        try:
            os.makedirs(os.path.dirname(self._server_file), exist_ok=True)
            with open(self._server_file, "w", encoding="utf-8") as f:
                json.dump(servers, f, ensure_ascii=False, indent=2)
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[moe_tts] 保存服务端列表失败: {e}")

    def _active_index(self) -> int:
        for i, s in enumerate(self.router.specs):
            if s.enabled:
                return i
        return 0

    def _load_translate_cfg(self) -> dict:
        try:
            with open(self._translate_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _build_config_groups(self) -> dict:
        """配置分组映射（WebUI 配置页按组展示；键全量覆盖 schema）。"""
        return {
            "服务端": ["servers", "timeout", "tts_queue_max_position", "fast_clone"],
            "音色与语言": ["default_voice", "voices"],
            "触发与范围": ["auto_tts", "tts_scope", "enable_llm_tool", "enable_user_trigger",
                       "trigger_keywords", "text_keywords", "blocklist", "allowlist"],
            "发送与展示": ["send_mode", "skip_bracket_tts", "auto_breath", "auto_effect",
                       "effect_intensity"],
            "分段": ["split_by_newline", "newline_min_len", "segment_len", "segment_first_len",
                   "segment_punct", "segment_merge", "max_text_len"],
            "容错": ["tts_concurrency", "tts_max_retry", "tts_retry_backoff", "tts_cooldown_sec"],
            "联系人同步": ["contacts_sync_interval_min", "contacts_sync_timeout_sec"],
        }

    async def initialize(self):
        try:
            webapi_mod.register_web_apis(self)
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[moe_tts] WebUI API 注册失败（不影响语音功能）: {e}")
        active = self.router.active
        if active:
            health = await self.router.adapter.health()
            sr = health.get("sample_rate", 24000)
            logger.info(
                f"[moe_tts] 就绪 v{self._version} | 服务端={active.name}({active.type}) "
                f"{active.url} | 采样率={sr} | 音色库={len(self.store.voices.data)} 条"
            )
        else:
            logger.warning(f"[moe_tts] 就绪 v{self._version} 但未配置服务端，请在 WebUI 添加")
        # 启动后台联系人同步（延时首拉，不阻塞初始化）
        try:
            self.contacts_scheduler.start()
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[moe_tts] 联系人同步启动失败（不影响语音功能）: {e}")

    def _refresh_cfg(self) -> dict:
        """返回插件自己的配置对象（AstrBot 注入的 AstrBotConfig，dict 子类）。

        严禁在此处用 context.get_config()：那是全局 cmd_config.json，
        会把插件配置冲成空——正是「WebUI 配置保存后仍为空」的根因。
        WebUI 保存写回同一个注入对象，所以这里直接返回即可拿到最新值。
        """
        return self.config

    def _sync_runtime_config(self) -> None:
        """把保存后的标量配置同步到已构造的运行时对象（无需重启即生效）。

        config 本身是同一 dict 引用，字典类配置自动生效；但 router/engine
        在 __init__ 时把一些值读成了标量属性，需要这里显式刷新。
        """
        cfg = self.config
        try:
            self.router.timeout = int(cfg.get("timeout", 250) or 250)
            self.router.max_retry = max(0, int(cfg.get("tts_max_retry", 1) or 0))
            self.router.retry_backoff = float(cfg.get("tts_retry_backoff", 0.5) or 0.5)
            self.router.cooldown_sec = float(cfg.get("tts_cooldown_sec", 30) or 30)
            self.router.queue_max_position = int(cfg.get("tts_queue_max_position", 8) or 0)
            if self.router.adapter:
                self.router.adapter.timeout = self.router.timeout
        except Exception as e:  # noqa: BLE001
            logger.debug(f"[moe_tts] 同步运行时配置失败: {e}")

    # ---------- 事件标记 ----------
    def _flag(self, event) -> dict:
        mid = getattr(event, "message_id", "") or id(event)
        return self._flags.setdefault(str(mid), {})

    def _set_flag(self, event, key: str, value) -> None:
        self._flag(event)[key] = value

    def _get_flag(self, event, key: str, default=None):
        return self._flag(event).get(key, default)

    def _clear(self, event) -> None:
        mid = getattr(event, "message_id", "") or id(event)
        self._flags.pop(str(mid), None)

    def _set_last_llm(self, origin: str, text: str) -> None:
        self._last_llm[origin] = (time.time(), text)

    def _get_last_llm(self, origin: str) -> str:
        item = self._last_llm.get(origin)
        if not item:
            return ""
        ts, text = item
        if time.time() - ts > LAST_LLM_TTL:
            self._last_llm.pop(origin, None)
            return ""
        return text

    def _remember_names(self, event, origin: str) -> None:
        """记录会话元数据：类型/群号/QQ/昵称/群名(后台补查)/头像ID/活跃时间。"""
        parsed = textutil_mod.parse_origin(origin)
        changes: dict = {
            "is_group": parsed["is_group"],
            "group_id": parsed["group_id"],
            "user_id": parsed["user_id"],
            "avatar_id": parsed["group_id"] if parsed["is_group"] else parsed["user_id"],
            "avatar_kind": "group" if parsed["is_group"] else "user",
            "last_active": int(time.time()),
            "updated": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        try:
            name = event.get_sender_name()
            if name:
                changes["nickname"] = str(name)
        except Exception:
            pass
        # 群名：优先取消息随附的 group.group_name（不触发额外 API）
        if parsed["is_group"]:
            g = getattr(getattr(event, "message_obj", None), "group", None)
            gname = str(getattr(g, "group_name", "") or "").strip()
            if gname:
                changes["group_name"] = gname
        # 每次消息都更新活跃时间（群名/昵称不变也要刷新 last_active）
        self.store.session_update(origin, changes)

        # 群名缺失时后台补查（get_group 会连发两个 OneBot API，不能阻塞回复）
        if parsed["is_group"] and not self.store.session(origin).get("group_name"):
            if origin not in self._group_name_pending:
                self._group_name_pending.add(origin)
                asyncio.create_task(self._fetch_group_name(event, origin))

    async def _fetch_group_name(self, event, origin: str) -> None:
        try:
            group = await event.get_group()
            gname = str(getattr(group, "group_name", "") or "").strip() if group else ""
            if gname:
                self.store.session_set(origin, "group_name", gname)
        except Exception as e:  # noqa: BLE001
            logger.debug(f"[moe_tts] 后台补查群名失败 {origin}: {e}")
        finally:
            self._group_name_pending.discard(origin)

    def _is_llm(self, result) -> bool:
        ct = getattr(result, "result_content_type", None)
        name = getattr(ct, "name", "") or ""
        if name:
            return name == "LLM_RESULT"
        return str(ct).upper().endswith("LLM_RESULT")

    # ---------- 触发判定 ----------
    def _should_tts(self, event, cfg: dict) -> bool:
        if self._get_flag(event, "suppress", False):
            return False
        origin = event.unified_msg_origin
        # 白黑名单
        blocklist = cfg.get("blocklist") or []
        allowlist = cfg.get("allowlist") or []
        sender = ""
        try:
            sender = str(event.get_sender_id())
        except Exception:
            pass
        for key in (origin, sender):
            if key and key in blocklist:
                return False
        if allowlist and not any(k in allowlist for k in (origin, sender)):
            return False
        # 范围
        want = self._get_flag(event, "want", False)
        on = self.store.is_on(origin, cfg)
        if not on and not want:
            return False
        # llm_only 必须是 LLM 结果
        if cfg.get("tts_scope", "llm_only") == "llm_only":
            result = event.get_result()
            if not (self._get_flag(event, "llm_this_round", False) or self._is_llm(result)):
                return False
        return True

    # ---------- LLM 回复钩子 ----------
    @filter.on_llm_response()
    async def on_llm_response(self, event: AstrMessageEvent, resp: LLMResponse):
        self._refresh_cfg()
        self._set_flag(event, "is_llm", True)
        self._set_flag(event, "llm_this_round", True)
        text = getattr(resp, "completion_text", None) or getattr(resp, "text", "") or ""
        if isinstance(text, (list, tuple)):
            text = "".join(str(x) for x in text)
        clean = textutil_mod.clean_tts_text(text)
        tool_calls = getattr(resp, "tool_calls", None) or getattr(resp, "tools", None) or []
        if not (tool_calls and not clean):
            self._set_last_llm(event.unified_msg_origin, clean)

        cfg = self.config
        msg = textutil_mod.clean_tts_text(event.message_str or "")
        if cfg.get("enable_user_trigger", True):
            if msg:
                self._last_user_msg[event.unified_msg_origin] = (time.time(), msg)
            if any(kw and kw in msg for kw in (cfg.get("trigger_keywords") or [])):
                self._set_flag(event, "want", True)
            if any(kw and kw in msg for kw in (cfg.get("text_keywords") or [])):
                self._set_flag(event, "suppress", True)
        if cfg.get("auto_tts", False):
            self._set_flag(event, "want", True)

    # ---------- 结果装饰钩子 ----------
    @filter.on_decorating_result()
    async def on_decorating_result(self, event: AstrMessageEvent):
        cfg = self._refresh_cfg()
        origin = event.unified_msg_origin
        self._remember_names(event, origin)

        # 用户「用文字回复」关键词（跨钩子兜底，按会话取，避免并发串台）
        ut = self._last_user_msg.get(origin)
        user_msg = ut[1] if ut and time.time() - ut[0] <= LAST_LLM_TTL else ""
        if cfg.get("enable_user_trigger", True) and user_msg:
            if any(kw and kw in user_msg for kw in (cfg.get("text_keywords") or [])):
                self._set_flag(event, "suppress", True)

        if self._get_flag(event, "suppress", False):
            self._clear(event)
            return
        if not self._should_tts(event, cfg):
            self._clear(event)
            return
        if self.router.in_cooldown:
            logger.warning(f"[moe_tts] 服务端冷却中，跳过语音，只发文字 | 剩余 {self.router.cooldown_remaining:.0f}s")
            self._clear(event)
            return

        result = event.get_result()
        chain = result.chain if result else []
        if not chain or any(isinstance(c, Comp.Record) for c in chain):
            self._clear(event)
            return

        texts = [
            textutil_mod.clean_tts_text(getattr(c, "text", ""))
            for c in chain if isinstance(c, Comp.Plain) and getattr(c, "text", "")
        ]
        full = textutil_mod.collapse_adjacent_repeats("".join(texts).strip())
        if not textutil_mod.is_speakable(full):
            fb = textutil_mod.clean_tts_text(self._get_last_llm(origin))
            if textutil_mod.is_speakable(fb):
                full = fb
            else:
                self._clear(event)
                return
        if textutil_mod.is_error_text(full):
            self._clear(event)
            return

        mid = str(getattr(event, "message_id", "") or "")
        if mid and mid in self._spoken_msgs:
            self._clear(event)
            return
        # 主动推送回环拦截
        key = re.sub(r"\s+", "", full)
        now = time.time()
        for k in [k for k, ts in self._sent_texts.items() if ts < now - 60]:
            del self._sent_texts[k]
        if key and key in self._sent_texts:
            self._clear(event)
            return
        if mid:
            self._spoken_msgs.add(mid)
            if len(self._spoken_msgs) > 500:
                self._spoken_msgs = set(list(self._spoken_msgs)[-250:])

        voice = self._get_flag(event, "voice", None) or self.store.voice_for(origin)
        send_mode = self.store.send_mode_for(origin, cfg)
        has_media = any(isinstance(c, Comp.Image) for c in chain)
        merge = bool(cfg.get("segment_merge", False))
        text_in_chain = bool(send_mode == "both" and merge) or has_media

        # 新消息优先：取消该会话正在跑的旧合成任务
        old = self._origin_tasks.get(origin)
        if old and not old.done():
            old.cancel()

        task = asyncio.create_task(
            self._do_tts(event, full, voice, send_mode, text_in_chain, has_media, cfg)
        )
        self._origin_tasks[origin] = task

        # 按需从结果链移除文字（由后台任务逐段补发）
        if not text_in_chain:
            result.chain = [c for c in chain if not isinstance(c, Comp.Plain)]
        self._clear(event)

    async def _do_tts(self, event, full: str, voice: str, send_mode: str,
                      text_in_chain: bool, has_media: bool, cfg: dict) -> None:
        # text_state 记这一条的文字去向，写进任务日志供 WebUI 排查：
        # chain=原文留在结果链 / resent:N=后台补发 N 段 / voice_only=设计上不发正文 /
        # cancelled=被新消息取消后补发 / send_failed=补发没成功。
        text_state = "chain" if text_in_chain else (
            "voice_only" if send_mode == "voice_only" else "pending")
        resent = 0
        res = None
        ok = False
        msg = ""
        try:
            res = await self.engine.synthesize(full, voice, kind="auto", origin=event.unified_msg_origin)
            ok = res.ok
            msg = res.error or "合成成功"
            if not ok:
                if "繁忙" in res.error:
                    await self._realtime_send(event, [Comp.Plain(SERVER_BUSY_TIP)])
                else:
                    await self._realtime_send(event, [Comp.Plain(SERVER_DOWN_TIP)])
                # 文字兜底：从链移除时必须补发完整原文
                if not text_in_chain and await self._realtime_send(event, [Comp.Plain(full)]):
                    text_state, resent = "resent:1", 1
                return
            self._sent_texts[re.sub(r"\s+", "", full)] = time.time()
            # 语音侧 _prepare_text 会剥离括号，段数常少于「完整原文」的段数；
            # 旧实现按语音段数截断文字，尾部文字（括号描写段 + 末段）永久丢失。
            # 现在文字按原文独立分段，循环取两者较大值，各自发完自己的全部。
            need_text = send_mode == "both" and not text_in_chain and not has_media
            text_segs = self.engine._segment(full) if need_text else []
            after = bool(cfg.get("text_after_voice", True))
            for i in range(max(len(res.files), len(text_segs))):
                path = res.files[i] if i < len(res.files) else None
                seg_text = self._seg_text_for(full, i, len(text_segs), cfg) if i < len(text_segs) else ""
                if seg_text and not after:
                    if await self._realtime_send(event, [Comp.Plain(seg_text)]):
                        resent += 1
                if path:
                    await self._realtime_send(event, [Comp.Record(file=path, url=path)])
                if seg_text and after:
                    if await self._realtime_send(event, [Comp.Plain(seg_text)]):
                        resent += 1
                if path:
                    self.engine.cleanup_file(path, delay=600)
            if need_text:
                text_state = f"resent:{resent}"
            # 括号内容单独补发：仅 voice_only 模式需要。
            # both 模式下正文补发的是完整原文（含括号），再补发会重复；
            # voice_only 模式正文完全不发，才需单独补发让语气描写可见。
            if res.brackets and send_mode == "voice_only" and not text_in_chain:
                await self._realtime_send(event, [Comp.Plain(f"（{res.brackets}）")])
        except asyncio.CancelledError:
            msg = "任务被新消息取消"
            logger.info("[moe_tts] 合成任务被新消息取消")
            # 文字已从结果链移除，取消时必须补发，否则该条消息文字永久丢失
            if not text_in_chain:
                if await self._realtime_send(event, [Comp.Plain(full)]):
                    text_state, resent = "cancelled", 1
                else:
                    text_state = "send_failed"
        except Exception as e:  # noqa: BLE001
            msg = str(e)[:300]
            logger.warning(f"[moe_tts] 后台合成异常: {e}")
            if not text_in_chain:
                if await self._realtime_send(event, [Comp.Plain(full)]):
                    text_state, resent = "resent:1(error)", 1
                else:
                    text_state = "send_failed"
        finally:
            self.store.log(
                ok=ok, msg=msg or "合成成功", origin=event.unified_msg_origin,
                voice=voice or self.engine.effective_default_voice(),
                chars=res.chars if res else len(full),
                elapsed_ms=res.elapsed_ms if res else 0,
                queue_position=res.queue_position if res else 0,
                kind="auto", segments=res.segments if res else 0,
                text=full, text_state=text_state,
            )

    def _seg_text_for(self, full: str, index: int, total: int, cfg: dict) -> str:
        """不合并 both 时文字如何随语音逐段发。

        补发的文字是**完整原文**（含括号语气描写），因为 AstrBot 结果链里的
        原文已被移除，这里必须把文本原样补回，遵守「文本绝不丢失」红线。
        语音侧才按 skip_bracket_tts 剥离括号（只读正文），两者口径不同是有意的：
        文字看到「（迷迷糊糊，声音很轻）\\n吃的什么。」全文，耳朵只听「吃的什么。」。
        """
        if total <= 1:
            return full
        segs = self.engine._segment(full)
        if index < len(segs):
            return segs[index]
        return ""

    async def _realtime_send(self, event, chain) -> bool:
        try:
            # context.send_message() 要的是 MessageChain 对象（内部访问 .chain），
            # 不能直接传 list[Component]，否则报 'list' object has no attribute 'chain'
            if not isinstance(chain, MessageChain):
                chain = MessageChain(list(chain))
            await self.context.send_message(event.unified_msg_origin, chain)
            return True
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[moe_tts] 发送消息失败: {e}")
            return False

    # ---------- 指令 ----------
    @filter.command("语音开")
    async def cmd_on(self, event: AstrMessageEvent):
        cfg = self._refresh_cfg()
        self.store.session_update(event.unified_msg_origin, {
            "on": True, "updated": time.strftime("%Y-%m-%d %H:%M:%S")
        })
        yield event.plain_result("🎙️ 已开启本会话的自动语音，之后我会用声音回复你～")

    @filter.command("语音关")
    async def cmd_off(self, event: AstrMessageEvent):
        self.store.session_update(event.unified_msg_origin, {
            "on": False, "updated": time.strftime("%Y-%m-%d %H:%M:%S")
        })
        yield event.plain_result("🔇 已关闭本会话的自动语音，改用文字回复～")

    @filter.command("语音音色")
    async def cmd_voice(self, event: AstrMessageEvent, name: str = ""):
        voices = await self.engine.voices()
        if not name:
            cur = self.store.voice_for(event.unified_msg_origin) or self.engine.effective_default_voice(voices)
            lines = [f"🎙️ 当前音色：{cur or '未设置'}", "可用音色："]
            lines += [f"  · {v['name']}" + (f"（{v['language']}）" if v.get("language") else "")
                      for v in voices if v.get("enabled", True)]
            yield event.plain_result("\n".join(lines))
            return
        match = next((v for v in voices if v["name"] == name), None)
        if not match:
            yield event.plain_result(f"没找到音色「{name}」哦，用 /语音音色 查看可用列表～")
            return
        self.store.session_set(event.unified_msg_origin, "voice", name)
        yield event.plain_result(f"🎙️ 本会话音色已切换为：{name}")

    @filter.command("语音状态")
    async def cmd_status(self, event: AstrMessageEvent):
        cfg = self._refresh_cfg()
        origin = event.unified_msg_origin
        active = self.router.active
        on = self.store.is_on(origin, cfg)
        voice = self.store.voice_for(origin) or self.engine.effective_default_voice()
        lines = [
            "🎙️ 萌萌语音 · 状态",
            f"  会话语音：{'开启' if on else '关闭'}",
            f"  当前音色：{voice or '未设置'}",
            f"  发送方式：{self.store.send_mode_for(origin, cfg)}",
            f"  服务端：{active.name if active else '未配置'}（{active.type if active else '-'}）",
        ]
        if self.router.in_cooldown:
            lines.append(f"  ⚠️ 冷却中（剩余 {self.router.cooldown_remaining:.0f}s）")
        if self.router.last_error:
            lines.append(f"  上次错误：{self.router.last_error[:60]}")
        yield event.plain_result("\n".join(lines))

    @filter.command("语音")
    async def cmd_speak(self, event: AstrMessageEvent, text: str = ""):
        """临时朗读一段文本（一次性）。"""
        cfg = self._refresh_cfg()
        text = (text or "").strip()
        if not text and event.message_str:
            text = event.message_str.split(" ", 1)[-1].strip()
        if not text:
            yield event.plain_result("用法：/语音 <要念的文本>，例：/语音 你好呀")
            return
        self._set_flag(event, "suppress", True)
        clean = textutil_mod.clean_tts_text(text)
        voice = self.store.voice_for(event.unified_msg_origin) or self.engine.effective_default_voice()
        res = await self.engine.synthesize(clean, voice, kind="command",
                                           origin=event.unified_msg_origin, want_brackets=False)
        self.store.log(ok=res.ok, msg=res.error or "指令合成", voice=voice, chars=res.chars,
                       elapsed_ms=res.elapsed_ms, kind="command", segments=res.segments, text=clean)
        if not res.ok:
            yield event.plain_result(f"语音没念出来：{res.error}")
            return
        for path in res.files:
            yield Comp.Record(file=path, url=path)
            self.engine.cleanup_file(path, delay=600)

    # ---------- LLM 工具 ----------
    @filter.llm_tool(name="text_to_speech")
    async def tool_speak(self, event: AstrMessageEvent, text: str, voice: str = ""):
        """把指定文本合成语音念出来（临时一次，不开启长期语音模式）。
        仅当用户明确要求朗读某段具体内容时使用；若用户想长期语音交流请用 set_voice_mode。

        Args:
            text(string): 要朗读的文本内容
            voice(string): 可选，音色名；留空用默认音色
        """
        cfg = self._refresh_cfg()
        if not cfg.get("enable_llm_tool", True):
            return "语音工具还没开启哦。"
        if self.router.in_cooldown:
            await self._realtime_send(event, [Comp.Plain(SERVER_DOWN_TIP)])
            return "语音服务暂时不可用，已用文字告知用户。"
        self._set_flag(event, "suppress", True)
        clean = textutil_mod.clean_tts_text(text)
        if not textutil_mod.is_speakable(clean):
            fb = textutil_mod.clean_tts_text(self._get_last_llm(event.unified_msg_origin))
            if textutil_mod.is_speakable(fb):
                clean = fb
            else:
                return "用户没有给出要朗读的具体内容。"
        target = voice or self.store.voice_for(event.unified_msg_origin) or self.engine.effective_default_voice()
        res = await self.engine.synthesize(clean, target, kind="tool",
                                           origin=event.unified_msg_origin, want_brackets=False)
        self.store.log(ok=res.ok, msg=res.error or "工具合成", voice=target, chars=res.chars,
                       elapsed_ms=res.elapsed_ms, kind="tool", segments=res.segments, text=clean)
        if not res.ok:
            return f"语音合成失败：{res.error}"
        for path in res.files:
            await self._realtime_send(event, [Comp.Record(file=path, url=path)])
            self.engine.cleanup_file(path, delay=600)
        return "已朗读完成。"

    @filter.llm_tool(name="set_voice_mode")
    async def tool_mode(self, event: AstrMessageEvent, enable: bool):
        """开启或关闭当前聊天的自动语音模式（用户说「以后用语音交流 / 别用语音了」时调用）。

        Args:
            enable(bool): true=开启自动语音，false=关闭
        """
        self.store.session_set(event.unified_msg_origin, "on", bool(enable))
        self._set_flag(event, "suppress", True)
        return ("已开启本聊天的自动语音，之后我会用声音回复～" if enable
                else "已关闭本聊天的自动语音，改用文字回复～")

    @filter.llm_tool(name="set_voice")
    async def tool_set_voice(self, event: AstrMessageEvent, voice: str):
        """切换当前聊天的语音音色（用户说「换成某某的声音」时调用）。

        Args:
            voice(string): 音色名，可用 list_voices 查看
        """
        voices = await self.engine.voices()
        match = next((v for v in voices if v["name"] == voice), None)
        if not match:
            names = "、".join(v["name"] for v in voices if v.get("enabled", True))
            return f"没找到音色「{voice}」。可用音色：{names or '（暂无）'}"
        self.store.session_set(event.unified_msg_origin, "voice", voice)
        self._set_flag(event, "suppress", True)
        return f"已把本聊天音色切换为：{voice}"

    @filter.llm_tool(name="list_voices")
    async def tool_list_voices(self, event: AstrMessageEvent):
        """列出当前可用的语音音色（用户问「你有哪些声音」时调用）。"""
        voices = await self.engine.voices()
        if not voices:
            return "目前没有可用的音色，请到 WebUI 添加或检查服务端。"
        lines = [f"· {v['name']}" + (f"（{v['language']}）" if v.get("language") else "")
                 for v in voices if v.get("enabled", True)]
        return "可用音色：\n" + "\n".join(lines)

    @filter.llm_tool(name="transcribe_audio")
    async def tool_asr(self, event: AstrMessageEvent, audio_base64: str, language: str = "zh"):
        """把一段音频转写成文字（仅直连 tts_serve 网关时可用）。

        Args:
            audio_base64(string): 音频的 base64 内容（不含 data: 前缀）
            language(string): 语种代码，默认 zh
        """
        cfg = self._refresh_cfg()
        if not cfg.get("enable_llm_tool", True):
            return "语音工具还没开启哦。"
        adapter = self.router.adapter
        if not adapter or self.router.active.type != "tts_serve":
            return "当前服务端不支持语音识别，请直连 tts_serve 网关后再试。"
        import base64 as _b64
        try:
            audio = _b64.b64decode(audio_base64)
            text = await adapter.asr(audio, "audio.wav", language)
            return f"识别结果：{text}" if text else "没有识别到内容。"
        except Exception as e:  # noqa: BLE001
            return f"语音识别失败：{e}"

    async def terminate(self):
        for task in self._origin_tasks.values():
            try:
                if not task.done():
                    task.cancel()
            except Exception:
                pass
        try:
            await self.avatars.close()
        except Exception:
            pass
        try:
            await self.contacts_scheduler.stop()
        except Exception:
            pass
        logger.info("[moe_tts] 插件已卸载")
