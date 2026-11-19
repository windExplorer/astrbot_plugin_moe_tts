"""合成引擎：把文本 + 音色编排成音频文件。

职责：
- 音色解析（服务端列表 + 配置备注 + WebUI 音色库合并）；
- 文本分段、括号剥离、副语言标记、翻译；
- 调 TTSRouter 合成，PCM→WAV 落盘到临时目录；
- 并发信号量、生成参数；
- 返回统一的结果供 main.py 发送。
"""
from __future__ import annotations

import asyncio
import os
import tempfile
import time
import uuid
from dataclasses import dataclass
from typing import Any

from astrbot.api import logger

from .server import BaseAdapter, TTSError, TTSRouter, VoiceInfo
from .store import PluginStore
from .textutil import (
    clean_tts_text,
    detect_language,
    extract_brackets,
    inject_breath,
    inject_effects,
    is_speakable,
    pcm_to_wav,
    split_segments,
    strip_brackets,
    strip_markups,
)
from .translator import Translator


@dataclass
class SynthesisResult:
    ok: bool
    files: list[str] = ""
    error: str = ""
    chars: int = 0
    segments: int = 0
    elapsed_ms: int = 0
    queue_position: int = 0
    brackets: str = ""


class TtsEngine:
    def __init__(self, config: dict, router: TTSRouter, store: PluginStore,
                 translator: Translator, *, concurrency: int = 1):
        self.config = config
        self.router = router
        self.store = store
        self.translator = translator
        self._sem = asyncio.Semaphore(max(1, int(concurrency)))
        self._tmp_dir = os.path.join(tempfile.gettempdir(), "moe_tts")
        os.makedirs(self._tmp_dir, exist_ok=True)
        self._wav_cache: dict[str, str] = {}  # sha -> wav path（试听复用）

    # ---------- 音色 ----------
    async def voices(self) -> list[dict]:
        """合并：服务端音色 + 配置备注 + WebUI 音色库。"""
        adapter = self.router.adapter
        server_voices: list[VoiceInfo] = []
        if adapter:
            try:
                server_voices = await adapter.voices()
            except Exception as e:
                logger.warning(f"[moe_tts] 读取服务端音色失败: {e}")
        merged: dict[str, dict] = {}
        for v in server_voices:
            merged[v.name] = {
                "name": v.name,
                "file": v.file or v.name,
                "text": v.text,
                "language": v.language,
                "enabled": v.enabled,
                "source": "server",
            }
        # 配置备注覆盖
        for item in self.config.get("voices") or []:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name", "") or "")
            if not name:
                continue
            prev = merged.get(name, {})
            merged[name] = {
                "name": name,
                "file": str(item.get("prompt_wav") or prev.get("file") or name),
                "text": str(item.get("prompt_text") or prev.get("text") or ""),
                "language": str(item.get("language") or prev.get("language") or ""),
                "enabled": prev.get("enabled", True),
                "markup": bool(item.get("markup", True)),
                "source": "server+config",
            }
        # WebUI 音色库最高优先级
        for name, info in self.store.voices.data.items():
            if not isinstance(info, dict):
                continue
            merged[name] = {
                "name": name,
                "file": str(info.get("file") or name),
                "text": str(info.get("text") or ""),
                "language": str(info.get("language") or ""),
                "enabled": bool(info.get("enabled", True)),
                "markup": bool(info.get("markup", True)),
                "source": "webui",
            }
        return sorted(merged.values(), key=lambda x: (x.get("language", ""), x["name"]))

    def effective_default_voice(self, voices: list[dict] | None = None) -> str:
        override = self.store.voice_default()
        if override:
            return override
        cfg_default = str(self.config.get("default_voice", "") or "")
        if cfg_default:
            return cfg_default
        vl = voices if voices is not None else []
        for v in vl:
            if v.get("enabled", True):
                return v["name"]
        return ""

    def voice_info(self, name: str) -> dict | None:
        v = self.store.voice(name)
        if v:
            return v
        for item in self.config.get("voices") or []:
            if isinstance(item, dict) and str(item.get("name", "")) == name:
                return dict(item)
        return None

    # ---------- 文本准备 ----------
    def _prepare_text(self, text: str, voice_info: dict | None) -> str:
        """括号剥离 + 标点换气 + 关键词音效（标记在分段之后逐段注入更稳，这里做全局部分）。"""
        cfg = self.config
        out = text
        if cfg.get("skip_bracket_tts", True):
            out = strip_brackets(out)
        out = clean_tts_text(out)
        return out

    def _segment(self, text: str) -> list[str]:
        cfg = self.config
        return split_segments(
            text,
            split_by_newline=bool(cfg.get("split_by_newline", True)),
            newline_min_len=int(cfg.get("newline_min_len", 10) or 0),
            segment_len=str(cfg.get("segment_len", "0") or "0"),
            segment_first_len=str(cfg.get("segment_first_len", "0") or "0"),
            segment_punct=str(cfg.get("segment_punct", "。！？.!?") or "。！？.!?"),
            max_text_len=int(cfg.get("max_text_len", 200) or 0),
        )

    def _markup_segment(self, seg: str, voice_info: dict | None) -> str:
        """逐段注入副语言标记（音色 markup=false 时跳过）。"""
        if voice_info and voice_info.get("markup") is False:
            return seg
        cfg = self.config
        out = inject_breath(seg, bool(cfg.get("auto_breath", True)))
        out = inject_effects(out, bool(cfg.get("auto_effect", False)),
                            str(cfg.get("effect_intensity", "medium")))
        return out

    def _generation_params(self) -> dict:
        """仅 tts_serve 直连时透传生成参数。"""
        if not self.router.active or self.router.active.type != "tts_serve":
            return {}
        cfg = self.config
        out: dict[str, Any] = {"fast_clone": "true" if cfg.get("fast_clone", True) else "false"}
        for key in ("max_new_tokens", "temperature", "top_k", "top_p",
                    "repetition_penalty", "subtalker_top_k", "subtalker_top_p",
                    "subtalker_temperature"):
            if key in cfg and cfg[key] not in (None, ""):
                out[key] = cfg[key]
        return out

    # ---------- 合成 ----------
    async def synthesize(
        self,
        text: str,
        voice: str = "",
        *,
        pre_translated: bool = False,
        kind: str = "auto",
        origin: str = "",
        want_brackets: bool = True,
    ) -> SynthesisResult:
        """合成一段文本，返回音频文件路径列表（逐段）。失败返回 ok=False，不抛异常。"""
        started = time.perf_counter()
        chars = len(strip_markups(text))
        if not is_speakable(text):
            return SynthesisResult(ok=False, error="无可朗读内容", chars=chars, kind=kind)

        target_voice = voice or self.effective_default_voice()
        info = self.voice_info(target_voice)
        brackets = extract_brackets(text) if want_brackets else ""

        # 翻译
        speak_text = text
        if not pre_translated and self.translator.should_translate(speak_text):
            try:
                speak_text = await self.translator.translate(speak_text)
            except Exception as e:
                logger.warning(f"[moe_tts] 翻译失败，回退原文: {e}")

        prepared = self._prepare_text(speak_text, info)
        segments = self._segment(prepared)
        if not segments:
            return SynthesisResult(ok=False, error="分段后无内容", chars=chars, kind=kind)

        files: list[str] = []
        max_qpos = 0
        sr = 24000
        try:
            for idx, seg in enumerate(segments):
                marked = self._markup_segment(seg, info)
                if not is_speakable(marked):
                    continue
                async with self._sem:
                    result = await self.router.synth(
                        marked,
                        voice=target_voice,
                        prompt_text=str((info or {}).get("text", "") or ""),
                        generation=self._generation_params(),
                    )
                max_qpos = max(max_qpos, result.queue_position)
                sr = result.sample_rate or sr
                path = await asyncio.to_thread(
                    self._write_wav, result.pcm, sr
                )
                files.append(path)
            elapsed = int((time.perf_counter() - started) * 1000)
            if not files:
                return SynthesisResult(ok=False, error="所有分段合成后为空", chars=chars,
                                       segments=len(segments), elapsed_ms=elapsed,
                                       queue_position=max_qpos, brackets=brackets)
            return SynthesisResult(ok=True, files=files, chars=chars,
                                   segments=len(files), elapsed_ms=elapsed,
                                   queue_position=max_qpos, brackets=brackets)
        except TTSError as e:
            elapsed = int((time.perf_counter() - started) * 1000)
            return SynthesisResult(ok=False, error=str(e), chars=chars,
                                   segments=len(segments), elapsed_ms=elapsed,
                                   queue_position=max_qpos, brackets=brackets)
        except Exception as e:
            logger.warning(f"[moe_tts] 合成异常: {e}")
            elapsed = int((time.perf_counter() - started) * 1000)
            return SynthesisResult(ok=False, error=str(e), chars=chars,
                                   segments=len(segments), elapsed_ms=elapsed,
                                   brackets=brackets)

    def _write_wav(self, pcm: bytes, sample_rate: int) -> str:
        wav = pcm_to_wav(pcm, sample_rate=sample_rate or 24000)
        name = f"{uuid.uuid4().hex}.wav"
        path = os.path.join(self._tmp_dir, name)
        with open(path, "wb") as f:
            f.write(wav)
        return path

    def cleanup_file(self, path: str, delay: float = 300.0) -> None:
        """延迟清理临时音频（后台任务由 main 调度）。"""
        async def _do():
            await asyncio.sleep(delay)
            try:
                if os.path.exists(path):
                    os.remove(path)
            except Exception:
                pass
        asyncio.create_task(_do())

    def preview_wav(self, text: str, voice: str = "") -> tuple[bytes | None, str]:
        """试听：合成一次返回 WAV 字节（不落盘），供 WebAPI data URI 用。"""
        raise NotImplementedError  # 由 webapi 直接调 router.synth + pcm_to_wav
