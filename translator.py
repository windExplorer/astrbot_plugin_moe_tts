"""通用翻译适配器：配置存插件自有 JSON，热生效，异常一律回退原文。"""
from __future__ import annotations

import json
import os
from typing import Any

import httpx

from .textutil import detect_language

DEFAULT_CONFIG: dict[str, Any] = {
    "enabled": False,
    "target": "zh",
    "source": [],  # 空 = 除目标语种外全部翻译
    "url": "",
    "method": "POST",
    "content_type": "json",
    "apikey": "",
    "auth_header": "Authorization",
    "auth_scheme": "Bearer",
    "extra_headers": [],
    "params": [],
    "response_path": "",
    "timeout": 10,
}


class Translator:
    def __init__(self, path: str, config: dict | None = None):
        self.path = path
        self.config = dict(DEFAULT_CONFIG)
        if isinstance(config, dict):
            self.config.update(config)
        self._cache: dict[str, str] = {}
        if not os.path.exists(path):
            self.save()

    def load(self) -> dict:
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                self.config.update({k: v for k, v in data.items() if k in DEFAULT_CONFIG})
        except Exception:
            pass
        return self.config

    def save(self) -> None:
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            with open(self.path, "w", encoding="utf-8") as f:
                json.dump(self.config, f, ensure_ascii=False, indent=2)
        except Exception:
            pass
        self._cache.clear()

    def reload(self) -> dict:
        self._cache.clear()
        return self.load()

    def should_translate(self, text: str) -> bool:
        cfg = self.config
        if not cfg.get("enabled") or not cfg.get("url") or not text.strip():
            return False
        src = str(cfg.get("source") or [])
        target = str(cfg.get("target", "zh"))
        lang = detect_language(text)
        if not lang or lang == target:
            return False
        whitelist = cfg.get("source") or []
        if isinstance(whitelist, list) and whitelist and lang not in whitelist:
            return False
        return True

    @staticmethod
    def _get_path(data: Any, path: str) -> str:
        if not path:
            return data if isinstance(data, str) else ""
        cur = data
        for part in str(path).split("."):
            if not part:
                continue
            idx = None
            if part.endswith("]") and "[" in part:
                part, idx_s = part[:-1].rsplit("[", 1)
                try:
                    idx = int(idx_s)
                except ValueError:
                    idx = None
            if isinstance(cur, dict):
                cur = cur.get(part)
            elif isinstance(cur, (list, tuple)) and idx is not None and 0 <= idx < len(cur):
                cur = cur[idx]
            else:
                return ""
            if cur is None:
                return ""
        return str(cur) if isinstance(cur, str) else (cur[0] if isinstance(cur, list) and cur else "")

    def _render(self, template: str, text: str, source: str, target: str) -> str:
        return (str(template or "")
                .replace("{text}", text)
                .replace("{source}", source)
                .replace("{target}", target))

    async def translate(self, text: str) -> str:
        """翻译文本；任何异常回退原文。"""
        if not self.should_translate(text):
            return text
        cfg = self.config
        source = detect_language(text)
        target = str(cfg.get("target", "zh"))
        cache_key = f"{source}->{target}:{text}"
        if cache_key in self._cache:
            return self._cache[cache_key]
        headers: dict[str, str] = {}
        apikey = str(cfg.get("apikey", "") or "")
        if apikey:
            headers[str(cfg.get("auth_header", "Authorization"))] = (
                f"{cfg.get('auth_scheme', 'Bearer')} {apikey}".strip()
            )
        for h in cfg.get("extra_headers") or []:
            if isinstance(h, dict) and h.get("key"):
                headers[str(h["key"])] = self._render(str(h.get("value", "")), text, source, target)
        params: dict[str, str] = {}
        for p in cfg.get("params") or []:
            if isinstance(p, dict) and p.get("key"):
                params[str(p["key"])] = self._render(str(p.get("value", "")), text, source, target)
        body: dict[str, Any] = dict(params)
        if "text" not in body:
            body["text"] = text
        try:
            async with httpx.AsyncClient(timeout=float(cfg.get("timeout", 10) or 10),
                                         trust_env=False) as client:
                method = str(cfg.get("method", "POST")).upper()
                if cfg.get("content_type") == "form":
                    r = await client.request(method, str(cfg["url"]), data=body, headers=headers)
                else:
                    r = await client.request(method, str(cfg["url"]), json=body, headers=headers)
                r.raise_for_status()
                result = self._get_path(r.json(), str(cfg.get("response_path", "")))
                out = result or text
                self._cache[cache_key] = out
                return out
        except Exception:
            return text

    async def translate_for_voice(self, text: str, voice_info: dict | None,
                                  target_lang: str = "zh") -> tuple[str, bool]:
        """返回 (用于合成的文本, 是否发生了翻译)。"""
        # 音色自带语种且与目标一致时不翻译
        if voice_info and voice_info.get("language") and voice_info["language"] == target_lang:
            return text, False
        out = await self.translate(text)
        return out, out != text
