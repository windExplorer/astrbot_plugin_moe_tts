"""服务端适配层：统一 TaskHub 中转站与 tts_serve 网关的 HTTP 契约。

对外暴露 TTSRouter：
- 多服务端配置，同时只启用一个（单选）；
- 统一 synth()：返回原始 PCM bytes + 采样率 + 元信息；
- 熔断冷却、退避重试、排队位置解析；
- 直连 tts_serve 时提供 ASR / 后端切换 / 显存管理 / 音色管理 API。

不依赖 astrbot，便于独立测试（用 httpx mock）。
"""
from __future__ import annotations

import asyncio
import base64
import json
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

try:
    from astrbot.api import logger
except ImportError:  # 独立测试环境降级
    import logging
    logger = logging.getLogger("moe_tts.server")


class TTSError(Exception):
    """可分类的语音服务错误。"""

    def __init__(self, message: str, *, code: int = 0, retryable: bool = False):
        super().__init__(message)
        self.code = code
        self.retryable = retryable


@dataclass
class VoiceInfo:
    name: str
    file: str = ""
    text: str = ""
    language: str = ""
    enabled: bool = True


@dataclass
class SynthResult:
    pcm: bytes
    sample_rate: int
    queue_position: int = 0
    generation_time: float = 0.0
    elapsed_ms: int = 0


@dataclass
class ServerSpec:
    name: str
    type: str  # taskhub | tts_serve
    url: str
    enabled: bool = False
    timeout: int = 250


class BaseAdapter:
    """适配器基类。子类实现 health / voices / synth。"""

    def __init__(self, spec: ServerSpec, sample_rate: int = 24000):
        self.spec = spec
        self.base_url = spec.url.rstrip("/")
        self.sample_rate = sample_rate
        self.timeout = spec.timeout

    def _client(self, timeout: float | None = None, connect: float = 10.0) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            timeout=httpx.Timeout(timeout if timeout is not None else self.timeout, connect=connect),
            trust_env=False,
            follow_redirects=True,
        )

    async def health(self) -> dict:
        """探测服务健康 + 采样率（短超时，独立于合成的 250s 读超时）。"""
        try:
            # 健康检查必须是「秒级」：连不上时 3s 内失败，服务端假死时 6s 内失败，
            # 否则 WebUI 总览会一直转圈、且把「没连通」误显示成「在线」。
            async with self._client(timeout=6.0, connect=3.0) as client:
                r = await client.get(self.base_url + "/")
                r.raise_for_status()
                content_type = r.headers.get("content-type", "")
                if "json" in content_type:
                    data = r.json()
                else:
                    # 非 JSON 响应也算「HTTP 层连通」，但不解析采样率
                    data = {}
                if isinstance(data, dict) and data.get("sample_rate"):
                    self.sample_rate = int(data["sample_rate"])
                return {
                    "ok": True,
                    "data": data,
                    "sample_rate": self.sample_rate,
                    "status_code": r.status_code,
                }
        except Exception as e:
            return {"ok": False, "error": str(e), "sample_rate": self.sample_rate}

    async def voices(self) -> list[VoiceInfo]:
        raise NotImplementedError

    async def synth(
        self,
        text: str,
        *,
        voice: str = "",
        prompt_text: str = "",
        prompt_wav: bytes | None = None,
        generation: dict | None = None,
    ) -> SynthResult:
        raise NotImplementedError

    # ---- 管理 API（仅 tts_serve 支持，基类默认抛错）----
    async def status(self) -> dict:
        raise TTSError("当前服务端类型不支持管理接口", code=0)

    async def asr(self, audio: bytes, filename: str = "audio.wav", language: str = "zh") -> str:
        raise TTSError("当前服务端不支持 ASR，请直连 tts_serve 网关", code=0)

    async def switch_backend(self, backend: str) -> dict:
        raise TTSError("当前服务端不支持后端切换，请直连 tts_serve 网关", code=0)

    async def vram(self, action: str) -> dict:
        raise TTSError("当前服务端不支持显存管理，请直连 tts_serve 网关", code=0)


def _text_of(value: Any) -> str:
    """兼容 texts 的值是 str 或对象（prompt_text 字段）。"""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        for k in ("prompt_text", "text", "prompt"):
            v = value.get(k)
            if isinstance(v, str) and v:
                return v
    return ""


def _parse_voices_taskhub(data: Any) -> list[VoiceInfo]:
    """解析 TaskHub /voices。

    TaskHub 原版返回 ``{voices_dir, files: list[str], texts: dict[str,str]}``；
    我们改造后代理上游 tts_serve 音色，仍是这套结构（files 为文件名列表，
    texts 按文件名索引）。同时兼容 files 为 dict 的旧/变体格式。
    """
    out: list[VoiceInfo] = []
    if not isinstance(data, dict):
        return out
    files = data.get("files")
    texts = data.get("texts") if isinstance(data.get("texts"), dict) else {}

    def add(name: str, file: str) -> None:
        if not name:
            return
        out.append(VoiceInfo(
            name=name,
            file=file or name,
            text=_text_of(texts.get(name) or texts.get(file) or ""),
        ))

    if isinstance(files, (list, tuple)):
        # 标准：files 是文件名列表，texts 按文件名索引
        for item in files:
            name = str(item)
            add(name, name)
    elif isinstance(files, dict):
        # 变体：files 是 {name: file} 或 {name: {...}}
        for name, val in files.items():
            if isinstance(val, dict):
                add(str(name), str(val.get("prompt_wav") or name))
            else:
                add(str(name), str(val or name))
    return out


def _parse_voices_ttsserve(data: Any) -> list[VoiceInfo]:
    """tts_serve /voices: {name: {prompt_wav, prompt_text, enabled}}。"""
    out: list[VoiceInfo] = []
    if not isinstance(data, dict):
        return out
    for name, info in data.items():
        if isinstance(info, dict):
            out.append(VoiceInfo(
                name=str(name),
                file=str(info.get("prompt_wav", "") or ""),
                text=str(info.get("prompt_text", "") or ""),
                enabled=bool(info.get("enabled", True)),
            ))
        elif isinstance(info, str):
            out.append(VoiceInfo(name=str(name), file=str(name), text=info))
    return out


class TaskHubAdapter(BaseAdapter):
    """TaskHub 任务中转站：只暴露合成、音色列表、健康检查；无鉴权。"""

    async def voices(self) -> list[VoiceInfo]:
        try:
            async with self._client() as client:
                r = await client.get(self.base_url + "/voices")
                r.raise_for_status()
                return _parse_voices_taskhub(r.json())
        except Exception as e:
            logger.warning(f"[moe_tts] TaskHub 读取音色失败: {e}")
            return []

    async def synth(
        self, text, *, voice="", prompt_text="", prompt_wav=None, generation=None
    ) -> SynthResult:
        # TaskHub 只认 tts_text / prompt_text / prompt_wav_path / prompt_wav
        form: dict[str, Any] = {"tts_text": text}
        if prompt_text:
            form["prompt_text"] = prompt_text
        files: dict[str, Any] | None = None
        if prompt_wav is not None:
            files = {"prompt_wav": ("prompt.wav", prompt_wav, "audio/wav")}
        elif voice:
            form["prompt_wav_path"] = voice
        started = time.perf_counter()
        async with self._client() as client:
            r = await client.post(
                self.base_url + "/inference_zero_shot",
                data=form,
                files=files,
            )
        elapsed = int((time.perf_counter() - started) * 1000)
        if r.status_code != 200:
            detail = _extract_detail(r)
            retryable = r.status_code in (429, 503, 504)
            raise TTSError(f"TaskHub 合成失败 HTTP {r.status_code}: {detail}",
                           code=r.status_code, retryable=retryable)
        qpos = _int_header(r.headers.get("X-Queue-Position"), 0)
        return SynthResult(
            pcm=r.content,
            sample_rate=self.sample_rate,
            queue_position=qpos,
            elapsed_ms=elapsed,
        )


class TtsServeAdapter(BaseAdapter):
    """tts_serve 网关：合成契约更丰富，且开放管理 API。"""

    async def voices(self) -> list[VoiceInfo]:
        try:
            async with self._client() as client:
                r = await client.get(self.base_url + "/voices")
                r.raise_for_status()
                return _parse_voices_ttsserve(r.json())
        except Exception as e:
            logger.warning(f"[moe_tts] tts_serve 读取音色失败: {e}")
            return []

    async def synth(
        self, text, *, voice="", prompt_text="", prompt_wav=None, generation=None
    ) -> SynthResult:
        form: dict[str, Any] = {"tts_text": text}
        if prompt_text:
            form["prompt_text"] = prompt_text
        if voice:
            form["prompt_wav_path"] = voice
        if generation:
            for k, v in generation.items():
                if v is not None and v != "":
                    form[k] = str(v)
        files = None
        if prompt_wav is not None:
            files = {"prompt_wav": ("prompt.wav", prompt_wav, "audio/wav")}
        started = time.perf_counter()
        async with self._client() as client:
            r = await client.post(
                self.base_url + "/inference_zero_shot", data=form, files=files
            )
        elapsed = int((time.perf_counter() - started) * 1000)
        if r.status_code != 200:
            detail = _extract_detail(r)
            retryable = r.status_code in (429, 503, 504)
            raise TTSError(f"tts_serve 合成失败 HTTP {r.status_code}: {detail}",
                           code=r.status_code, retryable=retryable)
        sr = _int_header(r.headers.get("X-Sample-Rate"), self.sample_rate)
        return SynthResult(
            pcm=r.content,
            sample_rate=sr or self.sample_rate,
            queue_position=_int_header(r.headers.get("X-Queue-Position"), 0),
            generation_time=_float_header(r.headers.get("X-Generation-Time"), 0.0),
            elapsed_ms=elapsed,
        )

    async def status(self) -> dict:
        for path in ("/api/status", "/api/gateway_status"):
            try:
                async with self._client() as client:
                    r = await client.get(self.base_url + path)
                    if r.status_code == 200:
                        return r.json()
            except Exception as e:
                logger.debug(f"[moe_tts] status {path} 失败: {e}")
        raise TTSError("无法读取服务端状态")

    async def asr(self, audio: bytes, filename="audio.wav", language="zh") -> str:
        async with self._client() as client:
            r = await client.post(
                self.base_url + "/api/asr",
                data={"language": language},
                files={"file": (filename, audio, "audio/wav")},
            )
        if r.status_code != 200:
            raise TTSError(f"ASR 失败 HTTP {r.status_code}: {_extract_detail(r)}",
                           code=r.status_code)
        return str(r.json().get("text", "") or "")

    async def switch_backend(self, backend: str) -> dict:
        async with self._client() as client:
            r = await client.post(
                self.base_url + "/api/switch_backend", json={"backend": backend}
            )
        if r.status_code != 200:
            raise TTSError(f"切换后端失败 HTTP {r.status_code}: {_extract_detail(r)}",
                           code=r.status_code)
        return r.json()

    async def vram(self, action: str) -> dict:
        if action not in ("load", "unload"):
            raise TTSError("显存操作仅支持 load / unload")
        async with self._client() as client:
            r = await client.post(self.base_url + f"/api/vram/{action}")
        if r.status_code != 200:
            raise TTSError(f"显存 {action} 失败 HTTP {r.status_code}: {_extract_detail(r)}",
                           code=r.status_code)
        return r.json()

    async def upload_voice(self, name: str, prompt_text: str, audio: bytes, filename: str) -> dict:
        async with self._client() as client:
            r = await client.post(
                self.base_url + "/api/voices/upload",
                data={"name": name, "prompt_text": prompt_text, "enabled": "true"},
                files={"file": (filename, audio, "audio/wav")},
            )
        if r.status_code not in (200, 201):
            raise TTSError(f"上传音色失败 HTTP {r.status_code}: {_extract_detail(r)}", code=r.status_code)
        return r.json()

    async def delete_voice(self, name: str) -> dict:
        async with self._client() as client:
            r = await client.delete(self.base_url + f"/api/voices/{name}")
        if r.status_code != 200:
            raise TTSError(f"删除音色失败 HTTP {r.status_code}: {_extract_detail(r)}", code=r.status_code)
        return r.json()


def _extract_detail(r: httpx.Response) -> str:
    try:
        data = r.json()
        if isinstance(data, dict):
            return str(data.get("detail", data.get("error", r.text[:120])))[:200]
    except Exception:
        pass
    return r.text[:200]


def _int_header(value: str | None, default: int) -> int:
    try:
        return int(float(value)) if value else default
    except (ValueError, TypeError):
        return default


def _float_header(value: str | None, default: float) -> float:
    try:
        return float(value) if value else default
    except (ValueError, TypeError):
        return default


class TTSRouter:
    """服务端路由：多服务端单选 + 熔断冷却 + 退避重试 + 采样率缓存。"""

    def __init__(self, servers: list[dict], *, timeout: int = 250, max_retry: int = 1,
                 retry_backoff: float = 0.5, cooldown_sec: float = 30.0,
                 queue_max_position: int = 8):
        self.specs: list[ServerSpec] = []
        for item in servers or []:
            if not isinstance(item, dict):
                continue
            url = str(item.get("url", "") or "").strip()
            if not url:
                continue
            self.specs.append(ServerSpec(
                name=str(item.get("name", "") or url),
                type=str(item.get("type", "taskhub") or "taskhub"),
                url=url,
                enabled=bool(item.get("enabled", False)),
                timeout=int(item.get("timeout", 0) or timeout),
            ))
        self.timeout = timeout
        self.max_retry = max(0, int(max_retry))
        self.retry_backoff = float(retry_backoff)
        self.cooldown_sec = float(cooldown_sec)
        self.queue_max_position = int(queue_max_position)
        self._adapter: BaseAdapter | None = None
        self._cooldown_until = 0.0
        self._last_error = ""
        self._rebuild_adapter()

    def _rebuild_adapter(self) -> None:
        active = next((s for s in self.specs if s.enabled), None)
        if active is None and self.specs:
            # 没有显式启用项：默认启用第一个（避免全禁用导致插件失能）
            active = self.specs[0]
            for s in self.specs:
                s.enabled = (s is active)
        if active is None:
            self._adapter = None
            return
        cls = TtsServeAdapter if active.type == "tts_serve" else TaskHubAdapter
        self._adapter = cls(active, sample_rate=24000)

    @property
    def active(self) -> ServerSpec | None:
        return self._adapter.spec if self._adapter else None

    @property
    def adapter(self) -> BaseAdapter | None:
        return self._adapter

    @property
    def in_cooldown(self) -> bool:
        return bool(self._cooldown_until and time.time() < self._cooldown_until)

    @property
    def cooldown_remaining(self) -> float:
        return max(0.0, self._cooldown_until - time.time())

    @property
    def last_error(self) -> str:
        return self._last_error

    def set_active(self, index: int) -> None:
        """切换启用服务端（单选）。index 越界时回退第一个。"""
        if not self.specs:
            self._adapter = None
            return
        idx = index if 0 <= index < len(self.specs) else 0
        for i, s in enumerate(self.specs):
            s.enabled = (i == idx)
        self._cooldown_until = 0.0
        self._last_error = ""
        self._rebuild_adapter()

    def set_servers(self, servers: list[dict]) -> None:
        self.specs = []
        for item in servers or []:
            if not isinstance(item, dict):
                continue
            url = str(item.get("url", "") or "").strip()
            if not url:
                continue
            self.specs.append(ServerSpec(
                name=str(item.get("name", "") or url),
                type=str(item.get("type", "taskhub") or "taskhub"),
                url=url,
                enabled=bool(item.get("enabled", False)),
                timeout=int(item.get("timeout", 0) or self.timeout),
            ))
        self._cooldown_until = 0.0
        self._last_error = ""
        self._rebuild_adapter()

    def servers_view(self) -> list[dict]:
        return [
            {
                "index": i,
                "name": s.name,
                "type": s.type,
                "url": s.url,
                "enabled": s.enabled,
                "timeout": s.timeout,
            }
            for i, s in enumerate(self.specs)
        ]

    def _enter_cooldown(self, reason: str) -> None:
        self._cooldown_until = time.time() + self.cooldown_sec
        self._last_error = reason
        logger.warning(f"[moe_tts] 服务端进入冷却 {self.cooldown_sec:.0f}s: {reason}")

    def _leave_cooldown(self) -> None:
        self._cooldown_until = 0.0
        self._last_error = ""

    async def ensure_sample_rate(self) -> int:
        if self._adapter is None:
            return 24000
        if self._adapter.spec.type == "tts_serve" and self._adapter.sample_rate == 24000:
            await self._adapter.health()
        return self._adapter.sample_rate

    async def synth(self, text: str, *, voice: str = "", prompt_text: str = "",
                    prompt_wav: bytes | None = None,
                    generation: dict | None = None) -> SynthResult:
        if self._adapter is None:
            raise TTSError("未配置任何语音服务端，请在 WebUI「服务端」页添加")
        if self.in_cooldown:
            raise TTSError(f"服务端冷却中（剩余 {self.cooldown_remaining:.0f}s）: {self._last_error}",
                           code=0)
        last_exc: TTSError | None = None
        for attempt in range(self.max_retry + 1):
            try:
                result = await self._adapter.synth(
                    text, voice=voice, prompt_text=prompt_text,
                    prompt_wav=prompt_wav, generation=generation,
                )
                if result.queue_position and self.queue_max_position > 0:
                    if result.queue_position >= self.queue_max_position:
                        raise TTSError(
                            f"服务端繁忙（前面还有 {result.queue_position} 个任务）",
                            code=429, retryable=True,
                        )
                self._leave_cooldown()
                return result
            except TTSError as e:
                last_exc = e
                if e.code == 500:
                    # 上游失联/空音频：不重试，直接冷却
                    self._enter_cooldown(str(e))
                    raise
                if e.retryable and attempt < self.max_retry:
                    delay = self.retry_backoff * (2 ** attempt)
                    logger.warning(f"[moe_tts] 合成失败（{e}），{delay:.1f}s 后重试 "
                                   f"({attempt + 1}/{self.max_retry})")
                    await asyncio.sleep(delay)
                    continue
                self._enter_cooldown(str(e))
                raise
        raise last_exc or TTSError("合成失败")
