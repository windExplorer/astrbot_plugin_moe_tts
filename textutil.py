"""文本处理纯函数：净化、分段、括号剥离、副语言标记、语种检测。

全部为无副作用的纯函数，便于独立测试。不依赖 astrbot。
"""
from __future__ import annotations

import re
import unicodedata
from typing import Iterable

# 副语言标记白名单：这些 [] 内容不是「括号备注」，不能当作不朗读内容删掉。
MARKUP_TOKENS = (
    "breath", "quick_breath", "laughter", "laugh", "sigh", "cough", "chuckle",
    "gasp", "groan", "hum", "cry", "sob", "whisper", "shout", "pause",
)
_MARKUP_ALT = "|".join(MARKUP_TOKENS)
MARKUP_WHITELIST_RE = re.compile(rf"\[\s*(?:{_MARKUP_ALT})\s*\]", re.IGNORECASE)
_BRACKET_RE = re.compile(r"[（(\[](.*?)[）)\]]", re.DOTALL)

# 媒体占位符（陪伴插件等注入），不当正文朗读。
_MEDIA_TAG_RE = re.compile(r"<[a-zA-Z_][\w-]*(?:\s[^<>]*?)?/?>")
# 常见错误回显：上游限流/超时/Traceback，不朗读。
_ERROR_RE = re.compile(
    r"(Traceback \(most recent call last\)|错误代码\s*\d+|error\s*code|"
    r"request\s*id[:：]|429\s*too\s*many|ratelimit|内部服务器错误)",
    re.IGNORECASE,
)
# Markdown 噪声：代码块围栏、图片语法、链接 URL、加粗星号。
_CODE_FENCE_RE = re.compile(r"```.*?```", re.DOTALL)
_INLINE_CODE_RE = re.compile(r"`[^`]*`")
_IMAGE_MD_RE = re.compile(r"!\[[^\]]*\]\([^)]*\)")
_LINK_MD_RE = re.compile(r"(?<!!)\[[^\]]*\]\(([^)]+)\)")
_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+", re.MULTILINE)


def strip_markups(text: str) -> str:
    """移除所有副语言标记，得到『纯正文』（用于字数统计/翻译）。"""
    if not text:
        return text
    return MARKUP_WHITELIST_RE.sub("", text)


def clean_tts_text(text: str) -> str:
    """综合净化：剔除媒体占位符、工具调用残留与 Markdown 噪声，保留正文与标记。

    不改动原文语义；仅供语音侧使用，展示侧一律原样透传。
    """
    if not text:
        return ""
    if isinstance(text, (list, tuple)):
        text = "".join(str(x) for x in text)
    s = str(text)
    s = _CODE_FENCE_RE.sub("", s)
    s = _INLINE_CODE_RE.sub("", s)
    s = _IMAGE_MD_RE.sub("", s)
    s = _LINK_MD_RE.sub(r"\1", s)
    s = _HEADING_RE.sub("", s)
    s = _MEDIA_TAG_RE.sub("", s)
    return s.strip()


def is_speakable(text: str) -> bool:
    """文本是否含可朗读内容（排除空、纯空白、纯标记、[] 占位符）。"""
    if not text or not text.strip():
        return False
    plain = strip_markups(text).strip()
    plain = re.sub(r"[\s\[\]（）()]+", "", plain)
    return bool(plain)


def is_error_text(text: str) -> bool:
    """是否为上游/框架错误回显（不该朗读）。"""
    return bool(text and _ERROR_RE.search(text))


def collapse_adjacent_repeats(text: str, min_len: int = 8) -> str:
    """折叠紧邻且完全相同的长块（上游合并中间轮/模型复述开场白导致）。

    只认「A+A」整块重复且 A 足够长；不做全局去重。用逐个候选长度验证，
    避免正则回溯把整段当成一块。
    """
    if not text:
        return text
    cur = text
    for _ in range(12):
        n = len(cur)
        found = -1
        # 候选半块长度从大到小：只可能是 n/2 及更短的整除长度
        for half in range(n // 2, min_len - 1, -1):
            if cur[:half] == cur[half:half * 2]:
                # 验证重复覆盖到结尾（可能是多份）
                unit = cur[:half]
                if unit * (n // half) == cur and n % half == 0:
                    found = half
                    break
        if found < 0:
            break
        cur = cur[:found]
    return cur


def strip_brackets(text: str) -> str:
    """剥离被 （）() [] 包裹的普通内容，但保留副语言标记。"""
    if not text:
        return text
    if not MARKUP_WHITELIST_RE.search(text):
        return _BRACKET_RE.sub("", text)
    ph: dict[str, str] = {}
    counter = [0]

    def _protect(m: re.Match) -> str:
        key = f"\x00MTT{counter[0]}\x00"
        counter[0] += 1
        ph[key] = m.group(0)
        return key

    tmp = MARKUP_WHITELIST_RE.sub(_protect, text)
    tmp = _BRACKET_RE.sub("", tmp)
    for k, v in ph.items():
        tmp = tmp.replace(k, v)
    return tmp


def extract_brackets(text: str) -> str:
    """提取普通括号内容（供 voice_only 时单独补发可见文字）。"""
    if not text:
        return ""
    parts = [m.group(1) for m in _BRACKET_RE.finditer(text) if m.group(1).strip()]
    return "\n".join(parts)


# ---------------- 语种检测 ----------------

def detect_language(text: str) -> str:
    """按 Unicode 脚本检测主要语种，零 API 消耗。返回 zh/ja/ko/ru/th/ar/hi/en 等。"""
    if not text:
        return ""
    counts: dict[str, int] = {}
    for ch in text:
        cp = ord(ch)
        lang = ""
        if 0x4E00 <= cp <= 0x9FFF:
            lang = "zh"
        elif 0x3040 <= cp <= 0x30FF:
            lang = "ja"
        elif 0xAC00 <= cp <= 0xD7AF or 0x1100 <= cp <= 0x11FF:
            lang = "ko"
        elif 0x0400 <= cp <= 0x04FF:
            lang = "ru"
        elif 0x0E00 <= cp <= 0x0E7F:
            lang = "th"
        elif 0x0600 <= cp <= 0x06FF:
            lang = "ar"
        elif 0x0900 <= cp <= 0x097F:
            lang = "hi"
        elif 0x0370 <= cp <= 0x03FF:
            lang = "el"
        elif "A" <= ch <= "Z" or "a" <= ch <= "z":
            lang = "en"
        if lang:
            counts[lang] = counts.get(lang, 0) + 1
    if not counts:
        return ""
    # 日文常混汉字，假名权重更高；中文纯汉字。
    return sorted(counts.items(), key=lambda kv: kv[1], reverse=True)[0][0]


# ---------------- 副语言标记注入 ----------------

def inject_breath(text: str, enabled: bool) -> str:
    """句末插 [breath]、句中（逗号/顿号）插 [quick_breath]。幂等：已有标记不重复插。"""
    if not enabled or not text:
        return text
    base = strip_markups(text)
    # 只处理没有标记的文本，避免叠加
    if base != text:
        return text
    end_punct = "。！？!?…"
    mid_punct = "，,、；;"
    out: list[str] = []
    for ch in base:
        out.append(ch)
        if ch in end_punct:
            out.append("[breath]")
        elif ch in mid_punct:
            out.append("[quick_breath]")
    return "".join(out)


# 按语种的效果词典
_EFFECT_WORDS: dict[str, dict[str, list[str]]] = {
    "zh": {
        "laughter": ["哈哈", "嘿嘿", "呵呵", "笑死", "哈哈哈"],
        "sigh": ["唉", "叹气", "唉声叹气", "无奈"],
        "cough": ["咳咳", "咳嗽"],
    },
    "en": {
        "laughter": ["haha", "lol", "hahaha"],
        "sigh": ["sigh", "sadly"],
        "cough": ["cough", "ahem"],
    },
    "ja": {"laughter": ["哈哈", "ww", "笑"]},
}


def inject_effects(text: str, enabled: bool, intensity: str = "medium") -> str:
    """按语种词典在句末追加音效标记。带上限，避免整段全是标记。"""
    if not enabled or not text:
        return text
    if MARKUP_WHITELIST_RE.search(text):
        return text  # 已有标记则不叠加
    limit = {"light": 1, "medium": 3, "strong": 5}.get(intensity, 3)
    lang = detect_language(text)
    words = _EFFECT_WORDS.get(lang, _EFFECT_WORDS["zh"])
    inserted = 0
    out: list[str] = []
    for ch in text:
        out.append(ch)
        if ch in "。！？!?" and inserted < limit:
            # 用最近 6 个字符做关键词命中判断
            recent = "".join(out[-8:])
            for token, hits in words.items():
                if any(h in recent for h in hits):
                    out.append(f"[{token}]")
                    inserted += 1
                    break
    return "".join(out)


# ---------------- 分段 ----------------

def _parse_len(value: str | int | None) -> tuple[int, int]:
    """解析 'min,max' / 'max' / 数字；返回 (min, max)，0 表示未设。"""
    if value is None or value == "" or value == 0 or value == "0":
        return (0, 0)
    s = str(value).strip()
    if "," in s:
        a, b = s.split(",", 1)
        try:
            return (max(0, int(a)), max(0, int(b)))
        except ValueError:
            return (0, 0)
    try:
        return (0, max(0, int(s)))
    except ValueError:
        return (0, 0)


def split_segments(
    text: str,
    *,
    split_by_newline: bool = True,
    newline_min_len: int = 10,
    segment_len: str | int = "0",
    segment_first_len: str | int = "0",
    segment_punct: str = "。！？.!?",
    max_text_len: int = 200,
) -> list[str]:
    """把长文本切成适合合成的小段。规则：

    1. split_by_newline：先按一个或多个换行切行，短行（< newline_min_len）与相邻行合并；
    2. 段长窗口：在 punct 处切，窗口 = 首段 first_len / 其余 segment_len；
    3. 无标点兜底：按 max_text_len 硬切（0=不限制）。

    返回非空片段列表；输入为空返回 []。保留标记不丢。
    """
    if not text or not text.strip():
        return []

    # 1. 按换行预切
    if split_by_newline and "\n" in text:
        lines = [ln.strip() for ln in re.split(r"\n+", text) if ln.strip()]
        if newline_min_len > 0 and len(lines) > 1:
            # 短行（<阈值）无论出现在开头/中间/结尾，都并入相邻行：
            # 优先并入上一行，没有上一行则并入下一行。
            merged: list[str] = []
            for ln in lines:
                short = len(strip_markups(ln)) < newline_min_len
                if merged and short:
                    merged[-1] = merged[-1] + "\n" + ln
                elif merged and len(strip_markups(merged[-1])) < newline_min_len:
                    # 上一行是短行：把当前行并上来
                    merged[-1] = merged[-1] + "\n" + ln
                else:
                    merged.append(ln)
            lines = merged
        units = lines
    else:
        units = [text.strip()]

    puncts = set(segment_punct or "。！？.!?")
    seg_min, seg_max = _parse_len(segment_len)
    first_min, first_max = _parse_len(segment_first_len)
    results: list[str] = []
    is_first = True

    for unit in units:
        # 首段窗口未设（0）时沿用普通段窗口；两者都未设才回退硬切。
        if is_first and first_max:
            lo, hi = first_min, first_max
        else:
            lo, hi = seg_min, seg_max
        if not hi:
            # 段长切分关闭：仅做 max_text_len 硬切兜底
            pieces = _hard_split(unit, max_text_len)
            results.extend(pieces)
            is_first = False
            continue
        pieces = _window_split(unit, lo, hi, puncts, max_text_len)
        results.extend(pieces)
        is_first = False

    return [p for p in results if p and p.strip()]


def _hard_split(text: str, max_len: int) -> list[str]:
    """按字数硬切（0=不切）。尽量不在标记中间切。"""
    if max_len <= 0 or len(text) <= max_len:
        return [text]
    out: list[str] = []
    buf = ""
    for ch in text:
        buf += ch
        # 避免在标记 [xxx] 中间断开
        if len(strip_markups(buf)) >= max_len and not _inside_markup(buf):
            out.append(buf)
            buf = ""
    if buf:
        out.append(buf)
    return out


def _inside_markup(buf: str) -> bool:
    """buf 末尾是否处于未闭合的 [] 标记内部。"""
    last_open = buf.rfind("[")
    last_close = buf.rfind("]")
    return last_open > last_close


def _window_split(
    text: str, min_len: int, max_len: int, puncts: set[str], hard_limit: int
) -> list[str]:
    """在 [min,max] 窗口内取最后一个句末标点切分；短段与下段合并。"""
    if not text:
        return []
    if max_len <= 0:
        return _hard_split(text, hard_limit)
    out: list[str] = []
    start = 0
    n = len(text)
    while start < n:
        window_end = min(start + max_len, n)
        cut = -1
        # 从窗口末尾往前找句末标点
        for i in range(window_end - 1, start, -1):
            if text[i] in puncts:
                cut = i + 1
                break
        if cut == -1:
            if window_end >= n:
                cut = n
            elif hard_limit > 0:
                cut = _hard_split(text[start:], hard_limit)[0]
                cut = start + len(cut)
            else:
                cut = window_end
        piece = text[start:cut]
        # 过短且与后面还有内容：尝试并入下一段（若合并后不超 hard_limit）
        if min_len > 0 and len(strip_markups(piece)) < min_len and cut < n:
            # 简单处理：把 delimiter 后紧接着的一小段并上来
            nxt = min(cut + min_len, n)
            merged = text[start:nxt]
            if hard_limit <= 0 or len(strip_markups(merged)) <= hard_limit:
                piece = merged
                cut = nxt
        if piece.strip():
            out.append(piece)
        start = cut
    return out


def preview_segments(text: str, **kwargs) -> list[dict]:
    """分段试算（WebUI 用）：返回 [{index, text, chars}]。"""
    segs = split_segments(text, **kwargs)
    return [
        {"index": i + 1, "text": s, "chars": len(strip_markups(s))}
        for i, s in enumerate(segs)
    ]


def pcm_to_wav(pcm: bytes, sample_rate: int = 24000, channels: int = 1, sample_width: int = 2) -> bytes:
    """裸 int16 PCM → 标准 WAV 字节（内存）。"""
    import io
    import wave

    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(sample_width)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm)
    return buf.getvalue()


def wav_duration_ms(wav_bytes: bytes) -> int:
    """读 WAV 时长（毫秒）；失败返回 0。"""
    import io
    import wave

    try:
        with wave.open(io.BytesIO(wav_bytes), "rb") as wf:
            frames = wf.getnframes()
            rate = wf.getframerate()
            return int(frames / rate * 1000) if rate else 0
    except Exception:
        return 0
