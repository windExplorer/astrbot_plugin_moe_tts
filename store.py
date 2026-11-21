"""持久化存储：会话语音状态 / 音色库 / 默认音色 / 任务日志。

全部落在插件 data_dir 的 JSON 文件，重启不丢。线程安全用简单锁（async 事件循环内串行）。
"""
from __future__ import annotations

import json
import os
import threading
import time
from typing import Any


class JsonStore:
    """单个 JSON 文件的读写封装：内存缓存 + 原子落盘。"""

    def __init__(self, path: str, default: Any):
        self.path = path
        self.default = default
        self._lock = threading.Lock()
        self.data = self._load()

    def _load(self) -> Any:
        if not os.path.exists(self.path):
            return _clone(self.default)
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data
        except Exception:
            return _clone(self.default)

    def save(self) -> None:
        with self._lock:
            tmp = self.path + ".tmp"
            try:
                os.makedirs(os.path.dirname(self.path), exist_ok=True)
                with open(tmp, "w", encoding="utf-8") as f:
                    json.dump(self.data, f, ensure_ascii=False, indent=2)
                os.replace(tmp, self.path)
            except Exception:
                # 落盘失败不影响主流程
                pass

    def get(self, key: str, fallback: Any = None) -> Any:
        return self.data.get(key, fallback)

    def set(self, key: str, value: Any, *, save: bool = True) -> None:
        self.data[key] = value
        if save:
            self.save()


def _clone(v: Any) -> Any:
    import copy
    return copy.deepcopy(v)


class PluginStore:
    """聚合插件所有持久化状态。"""

    MAX_EVENTS = 200

    def __init__(self, data_dir: str):
        os.makedirs(data_dir, exist_ok=True)
        self.data_dir = data_dir
        # 会话：origin -> {on: bool, voice: str, send_mode: str, nickname: str, group: str, ...}
        self.sessions = JsonStore(os.path.join(data_dir, "sessions.json"), {})
        # 音色库：name -> {name, file, text, language, enabled, markup}
        self.voices = JsonStore(os.path.join(data_dir, "voices.json"), {})
        # 默认音色覆盖（WebUI 设置，优先于配置项）
        self.default_voice = JsonStore(os.path.join(data_dir, "default_voice.json"), {"name": ""})
        # 全量联系人快照：从 aiocqhttp(OneBot) 拉取的群/好友列表，离线也能读。
        self.contacts = JsonStore(os.path.join(data_dir, "contacts.json"),
                                  {"friends": [], "groups": []})
        self.contacts_meta = JsonStore(os.path.join(data_dir, "contacts_meta.json"),
                                       {"synced_at": "", "platforms": 0, "friends": 0, "groups": 0,
                                        "error": ""})
        # 服务端音色快照：从服务端 /voices 同步后落盘，离线也能读。
        # {name: {name, file, text, language, enabled, markup, source, synced_at}}
        self.server_voices = JsonStore(os.path.join(data_dir, "server_voices.json"), {})
        self.server_voices_meta = JsonStore(os.path.join(data_dir, "server_voices_meta.json"),
                                             {"synced_at": "", "source_url": "", "count": 0})
        # 任务日志（环形，最新在前）
        self.events = JsonStore(os.path.join(data_dir, "events.json"), [])

    # ---------- 会话 ----------
    def session(self, origin: str) -> dict:
        s = self.sessions.data.get(origin)
        return dict(s) if isinstance(s, dict) else {}

    def session_set(self, origin: str, key: str, value: Any, *, remember_name: bool = True) -> None:
        s = self.sessions.data.setdefault(origin, {})
        s[key] = value
        self.sessions.save()

    def session_update(self, origin: str, changes: dict) -> dict:
        s = self.sessions.data.setdefault(origin, {})
        s.update(changes)
        self.sessions.save()
        return dict(s)

    def session_delete(self, origin: str) -> None:
        self.sessions.data.pop(origin, None)
        self.sessions.save()

    def sessions_clear(self) -> None:
        self.sessions.data.clear()
        self.sessions.save()

    def is_on(self, origin: str, cfg: dict | None = None) -> bool:
        s = self.session(origin)
        if "on" in s:
            return bool(s["on"])
        return bool((cfg or {}).get("auto_tts", False))

    def voice_for(self, origin: str) -> str:
        return str(self.session(origin).get("voice", "") or "")

    def send_mode_for(self, origin: str, cfg: dict | None = None) -> str:
        s = self.session(origin)
        return str(s.get("send_mode") or (cfg or {}).get("send_mode", "both"))

    # ---------- 音色库 ----------
    def voice(self, name: str) -> dict | None:
        v = self.voices.data.get(name)
        return dict(v) if isinstance(v, dict) else None

    def voice_set(self, name: str, info: dict) -> None:
        self.voices.data[str(name)] = dict(info)
        self.voices.save()

    def voice_delete(self, name: str) -> bool:
        if name in self.voices.data:
            del self.voices.data[name]
            self.voices.save()
            return True
        return False

    def voice_default(self) -> str:
        return str(self.default_voice.get("name", "") or "")

    def set_voice_default(self, name: str) -> None:
        self.default_voice.set("name", str(name or ""))

    # ---------- 任务日志 ----------
    def log(self, *, ok: bool, msg: str, origin: str = "", voice: str = "",
            chars: int = 0, elapsed_ms: int = 0, queue_position: int = 0,
            kind: str = "auto", segments: int = 0, text: str = "",
            text_state: str = "", detail: str = "") -> None:
        event = {
            "time": time.strftime("%Y-%m-%d %H:%M:%S"),
            "ts": int(time.time() * 1000),
            "ok": bool(ok),
            "msg": str(msg)[:300],
            "text": str(text)[:500],
            "text_state": str(text_state)[:40],
            "detail": str(detail)[:200],
            "origin": str(origin)[:120],
            "voice": str(voice)[:80],
            "chars": int(chars),
            "elapsed_ms": int(elapsed_ms),
            "queue_position": int(queue_position),
            "kind": str(kind),
            "segments": int(segments),
        }
        data = self.events.data
        if not isinstance(data, list):
            data = self.events.data = []
        data.insert(0, event)
        if len(data) > self.MAX_EVENTS:
            del data[self.MAX_EVENTS:]
        self.events.save()

    def recent_events(self, limit: int = 200) -> list[dict]:
        data = self.events.data
        return list(data[:limit]) if isinstance(data, list) else []

    def event_stats(self) -> dict:
        events = self.recent_events()
        ok = sum(1 for e in events if e.get("ok"))
        return {"total": len(events), "ok": ok, "failed": len(events) - ok}

    # ---------- 服务端音色快照 ----------
    def set_server_voices(self, voices: dict[str, dict], *, source_url: str = "") -> None:
        """整批替换服务端音色快照（同步时调用）。

        策略：服务端有值的字段一律覆盖（含后来补上的 prompt_text / language），
        只有服务端没提供时才保留本地旧值（language/markup 这类本地标注）。
        快照里不存在于本次服务端列表的音色会被删除（整批覆盖语义）。
        """
        import time as _time
        old = self.server_voices.data
        merged: dict[str, dict] = {}
        for name, info in voices.items():
            item = dict(info)
            prev = old.get(name, {}) if isinstance(old.get(name), dict) else {}
            # 本地备注（语种/markup）若服务端没有则以本地为准
            if not item.get("language") and prev.get("language"):
                item["language"] = prev["language"]
            if "markup" not in item and "markup" in prev:
                item["markup"] = prev["markup"]
            item["source"] = "server"
            item["synced_at"] = _time.strftime("%Y-%m-%d %H:%M:%S")
            merged[name] = item
        self.server_voices.data = merged
        self.server_voices.save()
        self.server_voices_meta.set("synced_at", _time.strftime("%Y-%m-%d %H:%M:%S"), save=False)
        self.server_voices_meta.set("source_url", str(source_url or ""), save=False)
        self.server_voices_meta.set("count", len(merged), save=False)
        self.server_voices_meta.save()

    def server_voice_snapshot(self) -> dict:
        return {
            "voices": list(self.server_voices.data.values()),
            "meta": dict(self.server_voices_meta.data),
        }

    # ---------- 全量联系人快照 ----------
    def set_contacts(self, friends: list[dict], groups: list[dict], *,
                     synced_at: str = "", platforms: int = 0) -> None:
        self.contacts.data = {
            "friends": list(friends or []),
            "groups": list(groups or []),
        }
        self.contacts.save()
        self.contacts_meta.set("synced_at", synced_at, save=False)
        self.contacts_meta.set("platforms", int(platforms), save=False)
        self.contacts_meta.set("friends", len(friends or []), save=False)
        self.contacts_meta.set("groups", len(groups or []), save=False)
        self.contacts_meta.set("error", "", save=False)
        self.contacts_meta.save()

    def contacts_snapshot(self) -> dict:
        data = self.contacts.data
        return {
            "friends": list(data.get("friends") or []) if isinstance(data, dict) else [],
            "groups": list(data.get("groups") or []) if isinstance(data, dict) else [],
            "meta": dict(self.contacts_meta.data),
        }
