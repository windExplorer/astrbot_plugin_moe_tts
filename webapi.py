"""WebUI 后端 API：通过 ctx.register_web_api 注册，供 pages/moe-tts 内嵌页调用。

路由统一前缀 /astrbot_plugin_moe_tts/（Page bridge 的 endpoint 不带前缀）。
所有 handler 用 astrbot.api.web 的 json_response / error_response。
"""
from __future__ import annotations

import asyncio
import base64
import json
import os
import time
from typing import Any

from astrbot.api import logger
from astrbot.api.web import error_response, json_response, request

from .server import TTSError
from .textutil import pcm_to_wav, preview_segments, detect_language
from .translator import DEFAULT_CONFIG as TRANSLATE_DEFAULT

PLUGIN_ROUTE_PREFIX = "astrbot_plugin_moe_tts"


def register_web_apis(plugin) -> None:
    ctx = plugin.context
    p = PLUGIN_ROUTE_PREFIX
    routes: list[tuple[str, Any, list[str], str]] = [
        ("/overview", _overview, ["GET"], "总览：服务端健康、统计、最近事件"),
        ("/voices", _voices, ["GET"], "音色列表（服务端 + 本地库）"),
        ("/voices/create", _voice_create, ["POST"], "新增本地音色"),
        ("/voices/update", _voice_update, ["POST"], "编辑本地音色"),
        ("/voices/delete", _voice_delete, ["POST"], "删除本地音色"),
        ("/voices/default", _voice_default, ["POST"], "设置默认音色"),
        ("/sessions", _sessions, ["GET"], "会话语音状态列表"),
        ("/sessions/set", _session_set, ["POST"], "设置会话语音状态"),
        ("/sessions/delete", _session_delete, ["POST"], "删除会话状态"),
        ("/sessions/clear", _session_clear, ["POST"], "清空会话状态"),
        ("/synthesize", _synthesize, ["POST"], "合成试听（返回 WAV data URI）"),
        ("/segment_preview", _segment_preview, ["POST"], "分段试算"),
        ("/servers", _servers, ["GET"], "服务端列表"),
        ("/servers/add", _server_add, ["POST"], "添加服务端"),
        ("/servers/activate", _server_activate, ["POST"], "切换启用的服务端（单选）"),
        ("/servers/remove", _server_remove, ["POST"], "删除服务端"),
        ("/servers/probe", _server_probe, ["POST"], "探测服务端健康与采样率"),
        ("/server/status", _server_status, ["GET"], "服务端管理状态（仅直连网关）"),
        ("/server/asr", _server_asr, ["POST"], "ASR 语音识别（仅直连网关）"),
        ("/server/backend", _server_backend, ["POST"], "切换模型后端（仅直连网关）"),
        ("/server/vram", _server_vram, ["POST"], "显存加载/卸载（仅直连网关）"),
        ("/translate", _translate, ["GET", "POST"], "翻译配置读取/保存"),
        ("/translate/test", _translate_test, ["POST"], "翻译测试"),
        ("/config", _config, ["GET"], "配置读取（schema + 当前值）"),
        ("/events", _events, ["GET"], "任务日志"),
    ]
    for path, factory, methods, desc in routes:
        ctx.register_web_api(f"/{p}{path}", factory(plugin), methods, f"萌萌语音：{desc}")
    logger.info(f"[moe_tts] WebUI API 已注册 {len(routes)} 条（前缀 /api/plug/{p}/）")


def _ok(data: Any):
    return json_response(data)


async def _body() -> dict:
    try:
        data = await request.json()
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


# ---------- 总览 ----------
def _overview(plugin):
    async def handler():
        plugin._refresh_cfg()
        cfg = plugin.config
        router = plugin.router
        events = plugin.store.recent_events()
        ok_n = sum(1 for e in events if e.get("ok"))
        active = router.active
        try:
            voices = await plugin.engine.voices()
        except Exception:
            voices = []
        return json_response({
            "ready": active is not None,
            "server": {
                "name": active.name if active else "",
                "type": active.type if active else "",
                "url": active.url if active else "",
                "sample_rate": getattr(router.adapter, "sample_rate", 24000) if router.adapter else 24000,
                "cooldown_remaining": round(router.cooldown_remaining, 1),
                "in_cooldown": router.in_cooldown,
                "last_error": router.last_error,
            } if active else None,
            "active_type": active.type if active else "",
            "can_manage": bool(active and active.type == "tts_serve"),
            "auto_tts": bool(cfg.get("auto_tts", False)),
            "send_mode": cfg.get("send_mode", "both"),
            "default_voice": plugin.engine.effective_default_voice(voices),
            "voices_count": len(voices),
            "session_count": len(plugin.store.sessions.data),
            "stats": {"total": len(events), "ok": ok_n, "failed": len(events) - ok_n},
            "recent": events[:20],
            "version": plugin._version,
        })
    return handler


# ---------- 音色 ----------
def _voices(plugin):
    async def handler():
        voices = await plugin.engine.voices()
        return json_response({
            "voices": voices,
            "default": plugin.engine.effective_default_voice(voices),
        })
    return handler


def _voice_create(plugin):
    async def handler():
        body = await _body()
        name = str(body.get("name", "") or "").strip()
        if not name:
            return error_response("音色名不能为空")
        info = {
            "name": name,
            "file": str(body.get("file") or name),
            "text": str(body.get("text") or ""),
            "language": str(body.get("language") or ""),
            "enabled": bool(body.get("enabled", True)),
            "markup": bool(body.get("markup", True)),
        }
        plugin.store.voice_set(name, info)
        return json_response({"ok": True, "voice": info})
    return handler


def _voice_update(plugin):
    async def handler():
        body = await _body()
        old = str(body.get("old_name", "") or "").strip()
        name = str(body.get("name", "") or old).strip()
        if not old or not name:
            return error_response("缺少音色名")
        info = plugin.store.voice(old) or {"name": name}
        info.update({
            "name": name,
            "file": str(body.get("file", info.get("file", name)) or name),
            "text": str(body.get("text", info.get("text", "")) or ""),
            "language": str(body.get("language", info.get("language", "")) or ""),
            "enabled": bool(body.get("enabled", info.get("enabled", True))),
            "markup": bool(body.get("markup", info.get("markup", True))),
        })
        if old != name:
            plugin.store.voice_delete(old)
        plugin.store.voice_set(name, info)
        if plugin.store.voice_default() == old:
            plugin.store.set_voice_default(name)
        for origin, s in plugin.store.sessions.data.items():
            if isinstance(s, dict) and s.get("voice") == old:
                s["voice"] = name
        plugin.store.sessions.save()
        return json_response({"ok": True, "voice": info})
    return handler


def _voice_delete(plugin):
    async def handler():
        body = await _body()
        name = str(body.get("name", "") or "").strip()
        if not name:
            return error_response("缺少音色名")
        plugin.store.voice_delete(name)
        if plugin.store.voice_default() == name:
            plugin.store.set_voice_default("")
        return json_response({"ok": True})
    return handler


def _voice_default(plugin):
    async def handler():
        body = await _body()
        plugin.store.set_voice_default(str(body.get("name", "") or ""))
        return json_response({"ok": True, "name": plugin.store.voice_default()})
    return handler


# ---------- 会话 ----------
def _sessions(plugin):
    async def handler():
        out = []
        for origin, s in plugin.store.sessions.data.items():
            if not isinstance(s, dict):
                continue
            out.append({
                "origin": origin,
                "on": bool(s.get("on", False)),
                "voice": str(s.get("voice", "") or ""),
                "send_mode": str(s.get("send_mode", "") or ""),
                "nickname": str(s.get("nickname", "") or ""),
                "group": str(s.get("group", "") or ""),
                "updated": s.get("updated", ""),
            })
        out.sort(key=lambda x: x.get("updated", ""), reverse=True)
        return json_response({"sessions": out})
    return handler


def _session_set(plugin):
    async def handler():
        body = await _body()
        origin = str(body.get("origin", "") or "")
        if not origin:
            return error_response("缺少会话标识")
        changes: dict[str, Any] = {}
        if "on" in body:
            changes["on"] = bool(body["on"])
        if "voice" in body:
            changes["voice"] = str(body["voice"] or "")
        if "send_mode" in body:
            changes["send_mode"] = str(body["send_mode"] or "")
        if "nickname" in body:
            changes["nickname"] = str(body["nickname"] or "")
        if "group" in body:
            changes["group"] = str(body["group"] or "")
        changes["updated"] = time.strftime("%Y-%m-%d %H:%M:%S")
        session = plugin.store.session_update(origin, changes)
        return json_response({"ok": True, "session": session})
    return handler


def _session_delete(plugin):
    async def handler():
        body = await _body()
        plugin.store.session_delete(str(body.get("origin", "") or ""))
        return json_response({"ok": True})
    return handler


def _session_clear(plugin):
    async def handler():
        plugin.store.sessions_clear()
        return json_response({"ok": True})
    return handler


# ---------- 合成试听 ----------
def _synthesize(plugin):
    async def handler():
        body = await _body()
        text = str(body.get("text", "") or "").strip()
        if not text:
            return error_response("请输入要合成的文本")
        voice = str(body.get("voice", "") or "")
        adapter = plugin.router.adapter
        if adapter is None:
            return error_response("未配置语音服务端")
        target_voice = voice or plugin.engine.effective_default_voice()
        info = plugin.engine.voice_info(target_voice)
        from .textutil import clean_tts_text, is_speakable
        clean = clean_tts_text(text)
        if not is_speakable(clean):
            return error_response("文本无可朗读内容")
        if plugin.translator.should_translate(clean):
            clean = await plugin.translator.translate(clean)
        try:
            result = await adapter.synth(
                clean,
                voice=target_voice,
                prompt_text=str((info or {}).get("text", "") or ""),
                generation=plugin.engine._generation_params(),
            )
        except TTSError as e:
            return error_response(str(e))
        except Exception as e:
            return error_response(f"合成失败: {e}")
        wav = pcm_to_wav(result.pcm, sample_rate=result.sample_rate or 24000)
        b64 = base64.b64encode(wav).decode("ascii")
        duration = int(len(wav) / max(1, (result.sample_rate or 24000) * 2) * 1000)
        return json_response({
            "audio": f"data:audio/wav;base64,{b64}",
            "sample_rate": result.sample_rate,
            "duration_ms": duration,
            "queue_position": result.queue_position,
            "generation_time": result.generation_time,
            "elapsed_ms": result.elapsed_ms,
            "voice": target_voice,
            "text": text,
        })
    return handler


def _segment_preview(plugin):
    async def handler():
        body = await _body()
        text = str(body.get("text", "") or "")
        cfg = plugin.config
        segs = preview_segments(
            text,
            split_by_newline=bool(cfg.get("split_by_newline", True)),
            newline_min_len=int(cfg.get("newline_min_len", 10) or 0),
            segment_len=str(cfg.get("segment_len", "0") or "0"),
            segment_first_len=str(cfg.get("segment_first_len", "0") or "0"),
            segment_punct=str(cfg.get("segment_punct", "。！？.!?") or "。！？.!?"),
            max_text_len=int(cfg.get("max_text_len", 200) or 0),
        )
        return json_response({"segments": segs, "count": len(segs)})
    return handler


# ---------- 服务端 ----------
def _servers(plugin):
    async def handler():
        return json_response({
            "servers": plugin.router.servers_view(),
            "active_index": plugin._active_index(),
        })
    return handler


def _server_add(plugin):
    async def handler():
        body = await _body()
        url = str(body.get("url", "") or "").strip()
        if not url:
            return error_response("服务地址不能为空")
        servers = plugin.router.servers_view()
        servers.append({
            "name": str(body.get("name") or url),
            "type": str(body.get("type") or "taskhub"),
            "url": url,
            "enabled": bool(body.get("enabled", False)),
            "timeout": int(body.get("timeout", 250) or 250),
        })
        plugin._save_servers(servers)
        return json_response({"ok": True, "servers": plugin.router.servers_view()})
    return handler


def _server_activate(plugin):
    async def handler():
        body = await _body()
        try:
            index = int(body.get("index", 0))
        except (TypeError, ValueError):
            return error_response("无效的服务端序号")
        plugin.router.set_active(index)
        plugin._save_servers(plugin.router.servers_view())
        active = plugin.router.active
        health = await plugin.router.adapter.health() if plugin.router.adapter else {"ok": False}
        return json_response({
            "ok": True,
            "active": active.name if active else "",
            "health": health,
        })
    return handler


def _server_remove(plugin):
    async def handler():
        body = await _body()
        try:
            index = int(body.get("index", -1))
        except (TypeError, ValueError):
            return error_response("无效的服务端序号")
        servers = plugin.router.servers_view()
        if 0 <= index < len(servers):
            servers.pop(index)
            plugin._save_servers(servers)
        return json_response({"ok": True, "servers": plugin.router.servers_view()})
    return handler


def _server_probe(plugin):
    async def handler():
        body = await _body()
        url = str(body.get("url", "") or "")
        stype = str(body.get("type") or "taskhub")
        from .server import ServerSpec, TaskHubAdapter, TtsServeAdapter
        spec = ServerSpec(name="probe", type=stype, url=url, timeout=15)
        adapter = TtsServeAdapter(spec) if stype == "tts_serve" else TaskHubAdapter(spec)
        health = await adapter.health()
        return json_response({"ok": health.get("ok", False), "health": health})
    return handler


def _server_status(plugin):
    async def handler():
        adapter = plugin.router.adapter
        if not adapter or plugin.router.active.type != "tts_serve":
            return error_response("仅直连 tts_serve 网关时可用")
        try:
            return json_response(await adapter.status())
        except TTSError as e:
            return error_response(str(e))
    return handler


def _server_asr(plugin):
    async def handler():
        body = await _body()
        adapter = plugin.router.adapter
        if not adapter or plugin.router.active.type != "tts_serve":
            return error_response("ASR 仅直连 tts_serve 网关时可用")
        audio_b64 = str(body.get("audio", "") or "")
        if not audio_b64:
            return error_response("缺少音频数据")
        if "," in audio_b64 and audio_b64.startswith("data:"):
            audio_b64 = audio_b64.split(",", 1)[1]
        try:
            audio = base64.b64decode(audio_b64)
        except Exception:
            return error_response("音频 base64 解码失败")
        try:
            text = await adapter.asr(audio, str(body.get("filename") or "audio.wav"),
                                     str(body.get("language") or "zh"))
            return json_response({"text": text})
        except TTSError as e:
            return error_response(str(e))
    return handler


def _server_backend(plugin):
    async def handler():
        body = await _body()
        adapter = plugin.router.adapter
        if not adapter or plugin.router.active.type != "tts_serve":
            return error_response("仅直连 tts_serve 网关时可用")
        try:
            return json_response(await adapter.switch_backend(str(body.get("backend") or "qwen3")))
        except TTSError as e:
            return error_response(str(e))
    return handler


def _server_vram(plugin):
    async def handler():
        body = await _body()
        adapter = plugin.router.adapter
        if not adapter or plugin.router.active.type != "tts_serve":
            return error_response("仅直连 tts_serve 网关时可用")
        try:
            return json_response(await adapter.vram(str(body.get("action") or "unload")))
        except TTSError as e:
            return error_response(str(e))
    return handler


# ---------- 翻译 ----------
def _translate(plugin):
    async def handler():
        if request.method == "POST":
            body = await _body()
            plugin.translator.config.update({
                k: v for k, v in body.items() if k in TRANSLATE_DEFAULT
            })
            plugin.translator.save()
            return json_response({"ok": True, "config": plugin.translator.config})
        return json_response({"config": plugin.translator.config})
    return handler


def _translate_test(plugin):
    async def handler():
        body = await _body()
        text = str(body.get("text", "") or "")
        lang = detect_language(text)
        translated = await plugin.translator.translate(text) if text else ""
        return json_response({
            "detected": lang,
            "should_translate": plugin.translator.should_translate(text),
            "translated": translated,
        })
    return handler


# ---------- 配置 ----------
def _config(plugin):
    async def handler():
        return json_response({
            "config": {k: v for k, v in plugin.config.items() if k != "config"},
            "schema_groups": plugin._CONFIG_GROUPS,
        })
    return handler


# ---------- 日志 ----------
def _events(plugin):
    async def handler():
        body = {}
        try:
            body = await _body() or {}
        except Exception:
            pass
        limit = int(body.get("limit", 200))
        events = plugin.store.recent_events(limit)
        ok_n = sum(1 for e in events if e.get("ok"))
        return json_response({
            "events": events,
            "stats": {"total": len(events), "ok": ok_n, "failed": len(events) - ok_n},
        })
    return handler
