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
MAX_ROWS = 16  # 音色很多时截断，避免卡片过长

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
