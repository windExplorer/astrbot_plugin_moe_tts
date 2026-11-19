"""跨插件语音契约 tts.v1 —— 让任何插件都能调用萌萌语音合成。

设计目标：调用方零依赖。拿到的永远是普通 dict / bool / list，不需要 import
本插件的任何内部类型（尤其是 SynthesisResult 这种会随版本改的 dataclass）。

用法（与 affinity.v1 同范式）：

    star = context.get_registered_star("astrbot_plugin_moe_tts")
    api = getattr(getattr(star, "star_cls", None), "api", None)   # TtsApi
    if api is None or api.API_VERSION != "tts.v1":
        ...  # 没装 / 版本过旧 → 安全降级（只发文字）
    if not api.available():
        ...  # 服务端没配 / 冷却中 / 没有音色
    res = await api.synthesize("你好呀", voice="", pre_translated=True)
    # res = {ok, files, error, chars, segments, elapsed_ms, queue_position}
    for path in res["files"]:
        ...  # 用 Comp.Record(file=path, url=path) 发送
        api.cleanup(path)

约束：
- synthesize 失败只返回 ok=False + error，**绝不抛异常**（调用方直接降级）。
- 文本清洗、分段、音色解析、翻译由引擎负责；调用方传入的 text 即"想朗读的话"。
- pre_translated=True 表示文案已定稿，不要经过翻译器改写（跨插件主动消息常用）。
"""
from __future__ import annotations

import asyncio
import threading
from typing import Any

API_VERSION = "tts.v1"


class TtsApi:
    """tts.v1 契约实现。挂在 MoeTtsPlugin.api 上，供其它插件通过 star_cls.api 取用。"""

    API_VERSION = API_VERSION

    def __init__(self, plugin: Any):
        self._plugin = plugin

    @property
    def plugin_version(self) -> str:
        return str(getattr(self._plugin, "_version", "") or "")

    def fingerprint(self) -> str:
        """供调用方做严格版本/实例校验：tts.v1:<插件版本>。"""
        return f"{API_VERSION}:{self.plugin_version}"

    # ------------------------------------------------------------------ #
    # 能力探测
    # ------------------------------------------------------------------ #
    def available(self) -> bool:
        """语音通道是否可用：配了服务端、不在冷却、至少有一个可用音色。

        同步方法（内部全是内存/JSON 快照读，无网络 IO），调用方可在任意上下文
        直接用。任一环节结构变动都按"不可用"处理，让调用方安全降级。
        """
        plugin = self._plugin
        router = getattr(plugin, "router", None)
        if router is None:
            return False
        try:
            if router.active is None or router.in_cooldown:
                return False
        except Exception:  # noqa: BLE001 - 老版本 router 结构不同
            return False
        engine = getattr(plugin, "engine", None)
        if engine is None:
            return False
        try:
            if engine.effective_default_voice():
                return True
        except Exception:  # noqa: BLE001
            pass
        # 没有默认音色时，看音色库里是否还有可用项（服务端快照 / WebUI 库 / 配置备注）
        try:
            store = getattr(engine, "store", None)
            for src in (
                getattr(store, "server_voices", None),
                getattr(store, "voices", None),
            ):
                data = getattr(src, "data", None) or {}
                for v in data.values():
                    if isinstance(v, dict) and v.get("enabled", True):
                        return True
            for item in (getattr(engine, "config", None) or {}).get("voices") or []:
                if isinstance(item, dict) and item.get("name"):
                    return True
        except Exception:  # noqa: BLE001
            pass
        return False

    async def voices(self) -> list[dict]:
        """可用音色列表（每项含 name/language/enabled）。失败返回空列表。"""
        engine = getattr(self._plugin, "engine", None)
        if engine is None:
            return []
        try:
            return await engine.voices()
        except Exception:  # noqa: BLE001
            return []

    # ------------------------------------------------------------------ #
    # 合成
    # ------------------------------------------------------------------ #
    async def synthesize(
        self,
        text: str,
        voice: str = "",
        *,
        pre_translated: bool = True,
    ) -> dict:
        """把文本合成语音，返回稳定 dict；任何失败都返回 ok=False，不抛异常。

        Returns:
            {ok: bool, files: list[str], error: str, chars: int,
             segments: int, elapsed_ms: int, queue_position: int}
            files 是本地 wav 路径列表（可能多段），发送后请调用 cleanup()。
        """
        result = {
            "ok": False, "files": [], "error": "", "chars": 0,
            "segments": 0, "elapsed_ms": 0, "queue_position": 0,
        }
        engine = getattr(self._plugin, "engine", None)
        if engine is None:
            result["error"] = "语音引擎未就绪"
            return result
        try:
            res = await engine.synthesize(
                text,
                voice or "",
                pre_translated=bool(pre_translated),
                want_brackets=False,
            )
        except Exception as exc:  # noqa: BLE001 - 契约层兜底，绝不外抛
            result["error"] = str(exc) or type(exc).__name__
            return result
        files = getattr(res, "files", None) or []
        if isinstance(files, str):  # 兼容老实现返回单路径字符串
            files = [files] if files else []
        result.update({
            "ok": bool(getattr(res, "ok", False)),
            "files": [str(p) for p in files],
            "error": str(getattr(res, "error", "") or ""),
            "chars": int(getattr(res, "chars", 0) or 0),
            "segments": int(getattr(res, "segments", 0) or 0),
            "elapsed_ms": int(getattr(res, "elapsed_ms", 0) or 0),
            "queue_position": int(getattr(res, "queue_position", 0) or 0),
        })
        return result

    # ------------------------------------------------------------------ #
    # 产物清理
    # ------------------------------------------------------------------ #
    def cleanup(self, path: str, delay: float | None = None) -> None:
        """延迟删除合成产物（默认 600s）。有事件循环时交给引擎，否则用定时器兜底。"""
        target = str(path or "").strip()
        if not target:
            return
        engine = getattr(self._plugin, "engine", None)
        if engine is not None:
            try:
                engine.cleanup_file(target, delay=float(delay) if delay else 600.0)
                return
            except RuntimeError:
                pass  # 无事件循环（测试/脚本环境），走下面的定时器兜底
            except Exception:  # noqa: BLE001
                pass
        wait = float(delay) if delay else 600.0

        def _delete() -> None:
            try:
                import os
                if os.path.isfile(target):
                    os.remove(target)
            except OSError:
                pass

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if loop is not None:
            async def _later() -> None:
                await asyncio.sleep(wait)
                _delete()
            loop.create_task(_later())
        else:
            timer = threading.Timer(wait, _delete)
            timer.daemon = True
            timer.start()
