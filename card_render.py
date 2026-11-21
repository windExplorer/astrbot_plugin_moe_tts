"""图片卡片渲染：把「语音状态」「音色列表」画成一张 PNG 发给用户。

约束（与 model_panel 同源）：
- Pillow 随 AstrBot 核心安装；缺失时整个模块退化，对外只返回 None。
- 中文字体：配置指定 → data/plugin_data/<插件名>/fonts → data/fonts → 系统字体。
  不往插件包里塞字体（一份全量中文字体 3~25MB，包才 1MB）。
- 画不出来绝不能影响功能：任何异常都返回 None，由调用方降级成纯文本。
"""
from __future__ import annotations

import io
import os
import sys

try:
    from PIL import Image, ImageDraw, ImageFont
except Exception:  # pragma: no cover - 无 Pillow 环境
    Image = None  # type: ignore
    ImageDraw = None  # type: ignore
    ImageFont = None  # type: ignore

W = 900
PAD = 42
RADIUS = 28
HEAD_H = 132
FOOT_H = 60
ROW_H = 64
ROW_GAP = 10
TITLE_SIZE = 38
BODY_SIZE = 26
LABEL_SIZE = 24
FOOT_SIZE = 20
MAX_ROWS = 16  # kv 卡行数上限
VOICE_COLS = 3  # 音色卡一行几个
MAX_VOICES = 60  # 音色卡方块上限，避免卡片过长
VOICE_W_MAX = 1600  # 音色卡自适应宽度上限，再宽发不出去

CARD_BG = (255, 255, 255)
ROW_BG = (247, 248, 252)
TEXT_DARK = (30, 33, 44)
TEXT_BODY = (56, 62, 78)
TEXT_MUTED = (126, 133, 152)
ACCENT = (214, 40, 112)
ACCENT2 = (124, 58, 200)
HEAD_TOP = (255, 229, 243)
HEAD_BOTTOM = (226, 212, 253)
FOOT_BG = (254, 246, 251)
BORDER = (238, 220, 235)


def _font_candidates(configured: str = "", data_dir: str = "") -> list[str]:
    """中文字体候选：配置 → data 投放目录 → 系统字体。"""
    out: list[str] = []
    if configured:
        out.append(configured)
    if data_dir:
        for d in (os.path.join(data_dir, "fonts"),
                  os.path.join(os.path.dirname(data_dir), "fonts")):
            if os.path.isdir(d):
                out += [os.path.join(d, n) for n in sorted(os.listdir(d))
                        if n.lower().endswith((".ttf", ".ttc", ".otf"))]
    if sys.platform.startswith("win"):
        root = os.path.join(os.environ.get("WINDIR", r"C:\Windows"), "Fonts")
        out += [os.path.join(root, n) for n in
                ("msyh.ttc", "msyhbd.ttc", "Noto Sans SC (TrueType).otf",
                 "simhei.ttf", "Deng.ttf", "SourceHanSansCN-Regular.otf")]
    elif sys.platform == "darwin":
        out += ["/System/Library/Fonts/PingFang.ttc",
                "/System/Library/Fonts/Supplemental/Arial Unicode.ttf"]
    else:
        out += ["/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
                "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
                "/usr/share/fonts/google-noto-cjk/NotoSansCJK-Regular.ttc",
                "/usr/share/fonts/wqy-microhei/wqy-microhei.ttc",
                "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc"]
    return out


def _font(size: int, configured: str = "", data_dir: str = ""):
    for path in _font_candidates(configured, data_dir):
        if not os.path.isfile(path):
            continue
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            continue
    return None


def render_kv_card(
    title: str,
    rows: list[tuple[str, str]],
    *,
    subtitle: str = "",
    footnote: str = "",
    font_path: str = "",
    data_dir: str = "",
) -> bytes | None:
    """渲染「标题 + 若干 标签:值 行」的卡片，返回 PNG bytes；失败返回 None。

    rows 为 (标签, 值) 列表；值会按卡片宽度自动截断，保证不溢出。
    """
    if Image is None:
        return None
    try:
        f_title = _font(TITLE_SIZE, font_path, data_dir)
        f_label = _font(LABEL_SIZE, font_path, data_dir)
        f_body = _font(BODY_SIZE, font_path, data_dir)
        f_foot = _font(FOOT_SIZE, font_path, data_dir)
        if not (f_title and f_label and f_body and f_foot):
            return None

        shown = list(rows[:MAX_ROWS])
        body_h = len(shown) * (ROW_H + ROW_GAP) + (ROW_GAP if shown else 0)
        h = HEAD_H + body_h + FOOT_H
        img = Image.new("RGB", (W, h), CARD_BG)
        d = ImageDraw.Draw(img)

        # 头部：粉→紫纵向渐变，底边直角
        for y in range(HEAD_H):
            t = y / max(1, HEAD_H - 1)
            c = tuple(int(HEAD_TOP[i] * (1 - t) + HEAD_BOTTOM[i] * t) for i in range(3))
            d.line([(0, y), (W, y)], fill=c)
        d.rounded_rectangle((0, 0, W - 1, h - 1), radius=RADIUS, outline=BORDER, width=2)
        d.text((PAD, 30), title, font=f_title, fill=TEXT_DARK)
        if subtitle:
            d.text((PAD, 84), subtitle, font=f_body, fill=ACCENT)

        max_value_w = W - 2 * PAD - 210
        y = HEAD_H + ROW_GAP
        for label, value in shown:
            d.rounded_rectangle((PAD, y, W - PAD, y + ROW_H), radius=16, fill=ROW_BG)
            d.text((PAD + 20, y + (ROW_H - LABEL_SIZE) // 2 - 2),
                   str(label), font=f_label, fill=TEXT_MUTED)
            val = _clip(d, str(value), f_body, max_value_w)
            vb = d.textbbox((0, 0), val, font=f_body)
            d.text((W - PAD - 20 - (vb[2] - vb[0]), y + (ROW_H - BODY_SIZE) // 2 - 2),
                   val, font=f_body, fill=TEXT_BODY)
            y += ROW_H + ROW_GAP

        foot_y = h - FOOT_H
        d.rectangle((0, foot_y, W, h), fill=FOOT_BG)
        d.text((PAD, foot_y + (FOOT_H - FOOT_SIZE) // 2 - 2),
               _clip(d, footnote, f_foot, W - 2 * PAD), font=f_foot, fill=TEXT_MUTED)

        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()
    except Exception:
        return None


def render_voices_card(
    title: str,
    voices: list[tuple[str, str]],
    *,
    current: str = "",
    subtitle: str = "",
    footnote: str = "",
    font_path: str = "",
    data_dir: str = "",
    cols: int = VOICE_COLS,
) -> bytes | None:
    """音色列表专用卡：一行 cols 个方块，每块显示音色名 + 语种。

    voices 为 (音色名, 语种) 列表；current 匹配名字时高亮该块。
    cols 限定 2~8（列太多方块太窄会看不清名字）。卡片宽度按音色名实际像素宽度
    自适应（至少 W，最多 VOICE_W_MAX），尽量不让名字被省略。失败返回 None。
    """
    if Image is None:
        return None
    try:
        cols = max(2, min(8, int(cols)))
        f_title = _font(TITLE_SIZE, font_path, data_dir)
        f_name = _font(24, font_path, data_dir)
        f_lang = _font(19, font_path, data_dir)
        f_sub = _font(BODY_SIZE, font_path, data_dir)
        f_foot = _font(FOOT_SIZE, font_path, data_dir)
        if not (f_title and f_name and f_lang and f_sub and f_foot):
            return None

        shown = list(voices[:MAX_VOICES])
        cell_h = 84
        gap = 12
        # 自适应宽度：量出最长音色名的像素宽，反推能完整显示它的卡片宽度。
        probe = ImageDraw.Draw(Image.new("RGB", (1, 1)))
        name_px = max([probe.textbbox((0, 0), str(n), font=f_name)[2]
                       for n, _ in shown] or [0])
        lang_px = max([probe.textbbox((0, 0), str(lg), font=f_lang)[2]
                       for _, lg in shown] or [0])
        need_cell = max(name_px, lang_px) + 40  # 两侧各 16 内边距 + 余量
        card_w = min(VOICE_W_MAX,
                     max(W, need_cell * cols + gap * (cols - 1) + 2 * PAD))
        cell_w = (card_w - 2 * PAD - gap * (cols - 1)) // cols
        rows = (len(shown) + cols - 1) // cols
        body_h = rows * (cell_h + gap) if rows else 0
        h = HEAD_H + body_h + gap + FOOT_H
        img = Image.new("RGB", (card_w, h), CARD_BG)
        d = ImageDraw.Draw(img)

        for y in range(HEAD_H):
            t = y / max(1, HEAD_H - 1)
            c = tuple(int(HEAD_TOP[i] * (1 - t) + HEAD_BOTTOM[i] * t) for i in range(3))
            d.line([(0, y), (card_w, y)], fill=c)
        d.rounded_rectangle((0, 0, card_w - 1, h - 1), radius=RADIUS, outline=BORDER, width=2)
        d.text((PAD, 30), title, font=f_title, fill=TEXT_DARK)
        if subtitle:
            d.text((PAD, 84), subtitle, font=f_sub, fill=ACCENT)

        for i, (name, lang) in enumerate(shown):
            col = i % cols
            row = i // cols
            x0 = PAD + col * (cell_w + gap)
            y0 = HEAD_H + gap + row * (cell_h + gap)
            active = bool(current) and name == current
            fill = (252, 231, 243) if active else ROW_BG
            outline = ACCENT if active else BORDER
            d.rounded_rectangle((x0, y0, x0 + cell_w, y0 + cell_h), radius=14,
                                fill=fill, outline=outline, width=2 if active else 1)
            name_text = _clip(d, name, f_name, cell_w - 32)
            d.text((x0 + 16, y0 + 14), name_text, font=f_name,
                   fill=ACCENT if active else TEXT_DARK)
            if lang:
                d.text((x0 + 16, y0 + 52), _clip(d, lang, f_lang, cell_w - 32),
                       font=f_lang, fill=ACCENT if active else TEXT_MUTED)

        foot_y = h - FOOT_H
        d.rectangle((0, foot_y, card_w, h), fill=FOOT_BG)
        d.text((PAD, foot_y + (FOOT_H - FOOT_SIZE) // 2 - 2),
               _clip(d, footnote, f_foot, card_w - 2 * PAD), font=f_foot, fill=TEXT_MUTED)

        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()
    except Exception:
        return None


def _clip(d, text: str, font, max_w: int) -> str:
    """按像素宽度截断文本，超长加省略号。"""
    if not text:
        return text
    bb = d.textbbox((0, 0), text, font=font)
    if bb[2] - bb[0] <= max_w:
        return text
    s = text
    while s and d.textbbox((0, 0), s + "…", font=font)[2] > max_w:
        s = s[:-1]
    return s + "…"
