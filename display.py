"""展示层纯函数：给用户看的文案清洗与中文化。

口径：音色在服务端本来就是带 .wav/.mp3 的文件名，合成/存储一律用原名；
只有发给用户的文案才去掉后缀、把 zh/ja 与 both 换成中文说法。
"""
from __future__ import annotations

import re

_VOICE_EXT_RE = re.compile(r"\.(mp3|wav|ogg|m4a|aac|flac|opus|wma|aiff)$", re.I)

_LANGUAGE_NAMES = {
    "zh": "中文", "zh-cn": "中文", "zh_cn": "中文", "cmn": "中文",
    "en": "英语", "en-us": "英语", "en_us": "英语",
    "ja": "日语", "jp": "日语",
    "ko": "韩语", "kr": "韩语",
    "ru": "俄语", "fr": "法语", "de": "德语", "es": "西班牙语",
}

_SEND_MODE_NAMES = {
    "both": "语音+文本",
    "voice_only": "仅语音",
}

_SERVER_TYPE_NAMES = {
    "taskhub": "任务中转站",
    "tts_serve": "直连网关",
}


def strip_voice_ext(name: str) -> str:
    """去掉音色名末尾的音频后缀，仅用于展示。"""
    return _VOICE_EXT_RE.sub("", str(name or "").strip())


def language_display(code: str) -> str:
    """语种代号转中文名；未知代号原样返回。"""
    s = str(code or "").strip()
    if not s:
        return ""
    return _LANGUAGE_NAMES.get(s.lower(), s)


def send_mode_display(mode: str) -> str:
    """发送方式代号转中文说法。"""
    s = str(mode or "").strip()
    return _SEND_MODE_NAMES.get(s, s)


def server_type_display(t: str) -> str:
    """服务端类型代号转中文名。"""
    s = str(t or "").strip()
    return _SERVER_TYPE_NAMES.get(s.lower(), s)


def voice_label(name: str, language: str = "") -> str:
    """一条音色的展示文案：去掉后缀 + 语种中文。"""
    label = strip_voice_ext(name) or str(name or "")
    lang = language_display(language)
    return f"{label}（{lang}）" if lang else label


def match_voice(query: str, voices: list[dict]) -> dict | None:
    """按用户输入匹配音色，支持不带后缀。

    先精确匹配原名，再去后缀精确匹配，最后去后缀子串匹配。
    返回原始条目（name 仍是带后缀的真实名，供合成使用）。
    """
    q = str(query or "").strip()
    if not q:
        return None
    for v in voices:
        if str(v.get("name", "")) == q:
            return v
    q_plain = strip_voice_ext(q).lower()
    for v in voices:
        if strip_voice_ext(v.get("name", "")).lower() == q_plain:
            return v
    if q_plain:
        for v in voices:
            if q_plain in strip_voice_ext(v.get("name", "")).lower():
                return v
    return None
