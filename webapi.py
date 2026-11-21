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
        ("/voices/sync", _voice_sync, ["POST"], "从服务端同步音色列表到本地快照"),
        ("/voices/snapshot", _voice_snapshot, ["GET"], "服务端音色快照元信息"),
        ("/voice/audio", _voice_audio, ["GET"], "音色试听：取服务端参考音频（本地缓存优先）"),
        ("/sessions", _sessions, ["GET"], "会话语音状态列表（群/私聊、群名、头像、活跃）"),
        ("/sessions/set", _session_set, ["POST"], "设置会话语音状态"),
        ("/sessions/delete", _session_delete, ["POST"], "删除会话状态"),
        ("/sessions/clear", _session_clear, ["POST"], "清空会话状态"),
        ("/avatars", _avatars, ["GET"], "批量取用户/群头像（data URI）"),
        ("/contacts", _contacts, ["GET"], "全量群/好友联系人快照（从 OneBot 同步）"),
        ("/contacts/sync", _contacts_sync, ["POST"], "手动同步全量群/好友列表"),
        ("/synthesize", _synthesize, ["POST"], "合成试听（返回 WAV data URI）"),
        ("/segment_preview", _segment_preview, ["POST"], "分段试算"),
        ("/servers", _servers, ["GET"], "服务端列表"),
        ("/servers/add", _server_add, ["POST"], "添加服务端"),
        ("/servers/update", _server_update, ["POST"], "编辑服务端"),
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
        ("/config/save", _config_save, ["POST"], "配置保存（写回 AstrBotConfig，热生效）"),
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
        # 真实连通性探测：不能用「配置了服务端」当作「服务端在线」。
        # health() 用 3s 连接 / 6s 读的短超时，连不上会快速失败而不是卡住页面。
        health: dict = {"ok": False, "error": "未配置服务端"}
        if router.adapter is not None:
            try:
                health = await router.adapter.health()
            except Exception as e:  # noqa: BLE001
                health = {"ok": False, "error": str(e)}
        try:
            voices = await plugin.engine.voices()
        except Exception:
            voices = []
        return json_response({
            "ready": bool(health.get("ok")),
            "server": {
                "name": active.name if active else "",
                "type": active.type if active else "",
                "url": active.url if active else "",
                "online": bool(health.get("ok")),
                "health_error": str(health.get("error") or ""),
                "sample_rate": health.get("sample_rate", 24000) or 24000,
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


def _voice_sync(plugin):
    async def handler():
        result = await plugin.engine.sync_server_voices()
        if not result.get("ok"):
            return error_response(result.get("error") or "同步失败")
        return json_response(result)
    return handler


def _voice_snapshot(plugin):
    async def handler():
        return json_response(plugin.store.server_voice_snapshot())
    return handler


def _voice_audio(plugin):
    """音色试听：本地缓存命中直接返回，否则从服务端取参考音频并落盘缓存。

    与合成试听的区别：这里拿到的是服务端已有的原始参考音频，不走 TTS 克隆，
    速度快、不占 GPU。缓存目录 <data_dir>/voice_previews/。
    """
    async def handler():
        import hashlib
        import mimetypes

        name = str(request.query.get("name") or "").strip()
        if not name:
            return error_response("缺少音色名 name")
        force = str(request.query.get("force") or "").lower() in ("1", "true", "yes")
        key = hashlib.sha256(name.encode("utf-8")).hexdigest()[:20]
        cache_dir = os.path.join(plugin.store.data_dir, "voice_previews")
        os.makedirs(cache_dir, exist_ok=True)
        cache_file = os.path.join(cache_dir, key + ".audio")
        meta_file = os.path.join(cache_dir, key + ".meta")
        data: bytes | None = None
        content_type = "audio/wav"
        if not force and os.path.isfile(cache_file):
            try:
                with open(cache_file, "rb") as f:
                    data = f.read()
                if os.path.isfile(meta_file):
                    with open(meta_file, "r", encoding="utf-8") as f:
                        content_type = f.read().strip() or content_type
            except Exception:
                data = None
        if data is None:
            adapter = plugin.router.adapter
            if adapter is None:
                return error_response("未配置语音服务端")
            try:
                got = await adapter.voice_audio(name)
            except Exception as e:  # noqa: BLE001
                return error_response(f"获取参考音频失败: {e}")
            if not got:
                return error_response("服务端没有该音色的参考音频（可能服务端未升级或音色名不匹配）")
            data, content_type = got
            try:
                tmp = cache_file + ".tmp"
                with open(tmp, "wb") as f:
                    f.write(data)
                os.replace(tmp, cache_file)
                with open(meta_file + ".tmp", "w", encoding="utf-8") as f:
                    f.write(content_type or "audio/wav")
                os.replace(meta_file + ".tmp", meta_file)
            except Exception as e:  # noqa: BLE001
                logger.debug(f"[moe_tts] 参考音频缓存写入失败: {e}")
        b64 = base64.b64encode(data).decode("ascii")
        return json_response({
            "audio": f"data:{content_type or 'audio/wav'};base64,{b64}",
            "name": name,
            "cached": os.path.isfile(cache_file),
            "size": len(data),
        })
    return handler


# ---------- 会话 ----------
def _sessions(plugin):
    async def handler():
        from .textutil import parse_origin
        out = []
        for origin, s in plugin.store.sessions.data.items():
            if not isinstance(s, dict):
                continue
            # 兼容旧数据：没有 is_group 字段时按 origin 现解析
            parsed = parse_origin(origin)
            is_group = bool(s.get("is_group", parsed["is_group"]))
            group_id = str(s.get("group_id") or parsed["group_id"])
            user_id = str(s.get("user_id") or parsed["user_id"])
            out.append({
                "origin": origin,
                "on": bool(s.get("on", False)),
                "prob": round(plugin.store.prob_for(origin, plugin.config), 1),
                "has_prob": "prob" in s,
                "voice": str(s.get("voice", "") or ""),
                "send_mode": str(s.get("send_mode", "") or ""),
                "is_group": is_group,
                "group_id": group_id,
                "user_id": user_id,
                "group_name": str(s.get("group_name") or ""),
                "nickname": str(s.get("nickname") or ""),
                "avatar_id": str(s.get("avatar_id") or (group_id if is_group else user_id)),
                "avatar_kind": "group" if is_group else "user",
                "last_active": int(s.get("last_active", 0)),
                "updated": str(s.get("updated", "") or ""),
            })
        # 活跃优先：last_active 降序，其次 updated 字符串降序
        out.sort(key=lambda x: (x.get("last_active", 0), x.get("updated", "")), reverse=True)
        return json_response({"sessions": out})
    return handler


def _avatars(plugin):
    async def handler():
        kind = str(request.query.get("type") or "user").strip().lower()
        if kind not in ("user", "group"):
            kind = "user"
        ids = [s.strip() for s in str(request.query.get("ids") or "").split(",") if s.strip()][:200]
        force = str(request.query.get("force") or "").lower() in ("1", "true", "yes")
        try:
            days = int(request.query.get("days") or 0)
        except (TypeError, ValueError):
            days = 0
        try:
            items = await plugin.avatars.ensure_map(kind, ids, force=force, max_age_days=(days or None))
            return json_response({"items": items, "requested": len(ids), "got": len(items)})
        except Exception as e:  # noqa: BLE001
            return error_response(f"头像获取失败: {e}")
    return handler


def _contacts(plugin):
    async def handler():
        return json_response(plugin.store.contacts_snapshot())
    return handler


def _contacts_sync(plugin):
    async def handler():
        try:
            result = await plugin.contacts_scheduler.sync_once()
            return json_response(result)
        except Exception as e:  # noqa: BLE001
            return error_response(f"同步联系人失败: {e}")
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
        if "prob" in body:
            # 0 / None / 空串 = 跟随全局概率（移除会话级设置）；0<p<=1 视为小数概率。
            raw = body["prob"]
            if raw is None or raw == "" or raw is False:
                s = plugin.store.sessions.data.setdefault(origin, {})
                s.pop("prob", None)
            else:
                try:
                    p = float(raw)
                    if p <= 0:
                        s = plugin.store.sessions.data.setdefault(origin, {})
                        s.pop("prob", None)
                    elif p <= 1:
                        changes["prob"] = p
                    else:
                        changes["prob"] = min(100.0, p) / 100.0
                except (TypeError, ValueError):
                    pass
        if "voice" in body:
            changes["voice"] = str(body["voice"] or "")
        if "send_mode" in body:
            changes["send_mode"] = str(body["send_mode"] or "")
        if "nickname" in body:
            changes["nickname"] = str(body["nickname"] or "")
        if "group_name" in body:
            changes["group_name"] = str(body["group_name"] or "")
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


def _server_update(plugin):
    async def handler():
        body = await _body()
        try:
            index = int(body.get("index", -1))
        except (TypeError, ValueError):
            return error_response("无效的服务端序号")
        servers = plugin.router.servers_view()
        if not (0 <= index < len(servers)):
            return error_response("服务端不存在")
        item = servers[index]
        if "name" in body:
            item["name"] = str(body["name"] or item["name"])
        if "type" in body:
            t = str(body["type"] or "taskhub")
            item["type"] = t if t in ("taskhub", "tts_serve") else "taskhub"
        if "url" in body:
            url = str(body["url"] or "").strip()
            if not url:
                return error_response("服务地址不能为空")
            item["url"] = url
        if "timeout" in body:
            try:
                item["timeout"] = max(1, int(body["timeout"]))
            except (TypeError, ValueError):
                return error_response("超时必须是正整数")
        servers[index] = item
        plugin._save_servers(servers)
        # 编辑的是当前启用项时，重建 adapter 让改动立即生效
        if item.get("enabled"):
            plugin.router.set_servers(servers)
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
_CONF_SCHEMA_CACHE: dict[str, Any] = {}


def _load_conf_schema(plugin) -> dict:
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_conf_schema.json")
    cached = _CONF_SCHEMA_CACHE
    if cached.get("path") == path and cached.get("data") is not None:
        return cached["data"]
    data: dict = {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            loaded = json.load(f)
        if isinstance(loaded, dict):
            data = loaded
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[moe_tts] 读取 _conf_schema.json 失败: {e}")
    cached["path"] = path
    cached["data"] = data
    return data


def _coerce_value(key: str, value, sch: dict):
    """按 schema 类型强转/校验配置值，返回 (ok, value|错误)。"""
    t = str(sch.get("type") or "string").strip().lower()
    if t == "bool":
        if isinstance(value, bool):
            return True, value
        s = str(value).strip().lower()
        if s in ("true", "1", "yes", "on"):
            return True, True
        if s in ("false", "0", "no", "off", ""):
            return True, False
        return False, f"{key}: 无法识别的布尔值 {value!r}"
    if t == "int":
        try:
            return True, int(float(value))
        except (TypeError, ValueError):
            return False, f"{key}: 必须是整数"
    if t == "float":
        try:
            return True, float(value)
        except (TypeError, ValueError):
            return False, f"{key}: 必须是数字"
    if t == "string":
        s = str(value)
        opts = sch.get("options")
        if opts and isinstance(opts, list) and s not in [str(o) for o in opts]:
            return False, f"{key}: 只能是 {'/'.join(map(str, opts))} 之一"
        return True, s
    if t == "list":
        if not isinstance(value, list):
            return False, f"{key}: 必须是数组"
        return True, [str(v) for v in value]
    if t == "template_list":
        if not isinstance(value, list):
            return False, f"{key}: 必须是数组"
        return True, value  # 服务端/音色列表由各自页面维护，这里整段放行
    return True, value


def _config(plugin):
    async def handler():
        plugin._refresh_cfg()
        schema = _load_conf_schema(plugin)
        raw = plugin.config
        # 以 schema 为准组装配置值：缺失的键用 schema.default 填充，
        # 保证页面即使配置文件缺项也不会全空（default 才是该键的真实生效值）。
        values: dict[str, Any] = {}
        from_schema: set[str] = set()
        for key, sch in schema.items():
            if key in raw:
                values[key] = raw.get(key)
            elif isinstance(sch, dict) and "default" in sch:
                values[key] = sch["default"]
                from_schema.add(key)
        # schema 之外的键也带出来（如历史遗留），但不参与编辑
        for key, value in raw.items():
            if key not in schema and key != "config":
                values[key] = value
        return json_response({
            "config": values,
            "schema_groups": plugin._CONFIG_GROUPS,
            "schema": schema,
            "from_default": sorted(from_schema),
        })
    return handler


def _config_save(plugin):
    async def handler():
        payload = await _body()
        if not payload:
            return error_response("缺少要保存的配置键值对")
        schema = _load_conf_schema(plugin)
        if not schema:
            return error_response("无法读取配置 schema", status_code=500)
        coerced: dict = {}
        for key, value in payload.items():
            key = str(key)
            sch = schema.get(key)
            if sch is None:
                return error_response(f"未知配置键「{key}」")
            if key in ("servers", "voices"):
                return error_response(f"{key} 请在对应管理页维护，不能通过配置接口修改")
            ok, result = _coerce_value(key, value, sch)
            if not ok:
                return error_response(str(result))
            coerced[key] = result
        conf = plugin._injected_config
        if conf is None or not isinstance(conf, dict):
            return error_response("插件配置对象不可用", status_code=500)
        conf.update(coerced)
        try:
            save_async = getattr(conf, "save_config_async", None)
            if save_async is not None:
                await save_async()
            else:
                conf.save_config()
        except Exception as e:  # noqa: BLE001
            try:
                conf.save_config()
            except Exception as e2:  # noqa: BLE001
                logger.error(f"[moe_tts] 配置落盘失败: {e2}（首次: {e}）")
                return error_response(f"配置已热生效但落盘失败：{e2}", status_code=500)
        plugin._refresh_cfg()
        plugin._sync_runtime_config()
        logger.info(f"[moe_tts] WebUI 保存配置 {list(coerced)}")
        return json_response({"ok": True, "values": {k: plugin.config.get(k) for k in coerced}})
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
