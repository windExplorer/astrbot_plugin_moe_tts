"""QQ 头像抓取与本地缓存（WebUI 会话列表用）。

后端抓取而非浏览器直连：控制台在 AstrBot 面板 sandbox iframe 里，直连外网 CDN
在内网/离线/企业代理环境会挂掉；群头像无现成 URL，需按群号拼 CDN。

- 好友头像：https://q4.qlogo.cn/headimg_dl?dst_uin=<QQ>&spec=140（备 q1.qlogo.cn/g）
- 群头像：https://p.qlogo.cn/gh/<群号>/<群号>/140

缓存落盘 <data_dir>/avatars/<kind>_<id>.img，30 天过期，失败静默降级为首字母色块。
（与 astrbot_plugin_cosyvoice/utils/avatar.py 同款实现，保持一致行为。）
"""
from __future__ import annotations

import asyncio
import re
import time
from pathlib import Path
from typing import Any, Iterable, Optional

from astrbot.api import logger

try:
    import aiohttp
except Exception:  # pragma: no cover
    aiohttp = None  # type: ignore

_SAFE_ID = re.compile(r"[^0-9]")
FRIEND_URL = "https://q4.qlogo.cn/headimg_dl?dst_uin={id}&spec=140"
GROUP_URL = "https://p.qlogo.cn/gh/{id}/{id}/140"
FRIEND_URL_FALLBACK = "https://q1.qlogo.cn/g?b=qq&nk={id}&s=100"
MAX_BYTES = 512 * 1024


def safe_id(raw: Any) -> str:
    return _SAFE_ID.sub("", str(raw or "").strip())[:20]


def avatar_url(kind: str, target_id: str) -> str:
    tid = safe_id(target_id)
    if not tid:
        return ""
    return (GROUP_URL if kind == "group" else FRIEND_URL).format(id=tid)


def guess_mime(data: bytes) -> str:
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return "application/octet-stream"


def to_data_uri(data: bytes) -> str:
    import base64
    return f"data:{guess_mime(data)};base64,{base64.b64encode(data).decode('ascii')}"


class AvatarCache:
    def __init__(self, root: str | Path, *, timeout: float = 8.0,
                 concurrency: int = 6, max_age_days: int = 30) -> None:
        self.root = Path(root)
        self.timeout = float(timeout)
        self.concurrency = max(1, int(concurrency))
        self.max_age_days = int(max_age_days)
        self._sem: Optional[asyncio.Semaphore] = None
        self._session: Any = None
        try:
            self.root.mkdir(parents=True, exist_ok=True)
        except Exception as e:  # noqa: BLE001
            logger.warning(f"[moe_tts] 头像缓存目录创建失败（头像将不可用）: {e}")

    def path(self, kind: str, target_id: str) -> Optional[Path]:
        tid = safe_id(target_id)
        if not tid:
            return None
        return self.root / f"{'group' if kind == 'group' else 'user'}_{tid}.img"

    def read(self, kind: str, target_id: str, *, max_age_days: Optional[int] = None) -> Optional[bytes]:
        p = self.path(kind, target_id)
        if p is None or not p.exists():
            return None
        days = self.max_age_days if max_age_days is None else int(max_age_days)
        try:
            if days > 0 and time.time() - p.stat().st_mtime > days * 86400:
                return None
            return p.read_bytes() or None
        except Exception:
            return None

    def read_any(self, kind: str, target_id: str) -> Optional[bytes]:
        p = self.path(kind, target_id)
        try:
            return (p.read_bytes() or None) if p is not None and p.exists() else None
        except Exception:
            return None

    def write(self, kind: str, target_id: str, data: bytes) -> bool:
        p = self.path(kind, target_id)
        if p is None or not data:
            return False
        try:
            tmp = p.with_suffix(".tmp")
            tmp.write_bytes(data)
            tmp.replace(p)
            return True
        except Exception as e:  # noqa: BLE001
            logger.debug(f"[moe_tts] 头像写入失败（{kind}:{target_id}）: {e}")
            return False

    async def _get_session(self) -> Any:
        if aiohttp is None:
            return None
        if self._session is None or getattr(self._session, "closed", False):
            self._session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=self.timeout),
                headers={"User-Agent": "AstrBot-MoeTTS/avatar"},
            )
        return self._session

    async def close(self) -> None:
        s, self._session = self._session, None
        if s is not None:
            try:
                await s.close()
            except Exception:
                pass

    def _candidate_urls(self, kind: str, target_id: str) -> list[str]:
        tid = safe_id(target_id)
        if not tid:
            return []
        urls = [avatar_url(kind, tid)]
        if kind != "group" and FRIEND_URL_FALLBACK:
            urls.append(FRIEND_URL_FALLBACK.format(id=tid))
        return [u for u in urls if u]

    async def fetch_one(self, kind: str, target_id: str) -> Optional[bytes]:
        urls = self._candidate_urls(kind, target_id)
        if not urls:
            return None
        session = await self._get_session()
        if session is None:
            return None
        if self._sem is None:
            self._sem = asyncio.Semaphore(self.concurrency)
        for url in urls:
            try:
                async with self._sem:
                    async with session.get(url) as resp:
                        if resp.status != 200:
                            continue
                        data = await resp.content.read(MAX_BYTES + 1)
            except Exception as e:  # noqa: BLE001
                logger.debug(f"[moe_tts] 抓取头像失败 {kind}:{target_id} {url}: {e}")
                continue
            if not data or len(data) > MAX_BYTES:
                continue
            if guess_mime(data) == "application/octet-stream":
                continue
            return data
        return None

    async def ensure_map(self, kind: str, ids: Iterable[Any], *, force: bool = False,
                         max_age_days: Optional[int] = None) -> dict[str, str]:
        """返回 {id: data URI}；失败静默跳过。"""
        result: dict[str, bytes] = {}
        todo: list[str] = []
        for raw in ids:
            tid = safe_id(raw)
            if not tid or tid in result:
                continue
            cached = None if force else self.read(kind, tid, max_age_days=max_age_days)
            if cached:
                result[tid] = cached
            else:
                todo.append(tid)
        if todo:
            async def one(tid: str) -> None:
                data = await self.fetch_one(kind, tid)
                if data:
                    self.write(kind, tid, data)
                    result[tid] = data
                elif not force:
                    stale = self.read_any(kind, tid)
                    if stale:
                        result[tid] = stale
            await asyncio.gather(*(one(t) for t in todo), return_exceptions=True)
        return {tid: to_data_uri(data) for tid, data in result.items()}
