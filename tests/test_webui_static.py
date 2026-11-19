"""WebUI 静态契约守卫：产物结构 + 单文件 + 禁止 i18n + 关键文案。
直接运行：python tests/test_webui_static.py，退出码即结论。
"""
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PASS = 0
FAIL = 0


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  OK  {name}")
    else:
        FAIL += 1
        print(f"FAIL  {name}  {detail}")


def main():
    page_dir = os.path.join(ROOT, "pages", "moe-tts")
    check("pages/moe-tts 存在", os.path.isdir(page_dir))
    index = os.path.join(page_dir, "index.html")
    check("index.html 存在", os.path.isfile(index))
    if not os.path.isfile(index):
        print(f"\nRESULT: PASS={PASS} FAIL={FAIL}")
        return 1

    html = open(index, "r", encoding="utf-8").read()
    check("标题为萌萌语音", "<title>萌萌语音</title>" in html)
    check("viewport 含 viewport-fit=cover", "viewport-fit=cover" in html)

    # 单文件产物：index.html 只引用一个 js，无跨 chunk import
    scripts = re.findall(r'<script[^>]*src="([^"]+)"', html)
    check("入口仅一个 script", len(scripts) == 1, str(scripts))
    assets_dir = os.path.join(page_dir, "assets")
    js_files = [f for f in os.listdir(assets_dir) if f.endswith(".js")] if os.path.isdir(assets_dir) else []
    check("assets 仅一个 JS（单文件产物）", len(js_files) == 1, str(js_files))
    check("无 CSS 外链（已注入 JS）", ".css" not in html)

    # 插件 Logo：根目录 logo.png（AstrBot 插件列表认这个固定文件名），且已内联进 JS
    check("插件根目录有 logo.png", os.path.isfile(os.path.join(ROOT, "logo.png")))

    # JS 里含所有页面关键文案（确认源码已编进产物）
    if js_files:
        js = open(os.path.join(assets_dir, js_files[0]), "r", encoding="utf-8").read()
        check("Logo 已内联进 JS（单文件产物）", "data:image/png;base64" in js)
        for token in ["总览", "音色库", "会话管理", "合成实验室", "服务端", "任务日志", "萌萌语音",
                      "分段试算", "极速克隆", "浅色主题", "深色主题", "从服务端同步", "保存更改",
                      "群聊", "私聊", "刷新头像", "刚刚", "同步列表", "联系人快照", "未启用",
                      "帮助", "使用帮助", "聊天指令", "重要说明", "语音 + 文字", "跟随默认"]:
            check(f"产物含文案「{token}」", token in js)
        # 浅色主题令牌与切换逻辑
        for token in ["data-theme", "moe-tts-theme", "--surface-solid", "light"]:
            check(f"产物含主题机制「{token}」", token in js)

    # 禁止 i18n（工作区红线）
    i18n_dir = os.path.join(ROOT, ".astrbot-plugin", "i18n")
    check("无 i18n 目录", not os.path.exists(i18n_dir))
    check("源码无 vue-i18n 依赖",
          "vue-i18n" not in open(os.path.join(ROOT, "webui-src", "package.json"), "r", encoding="utf-8").read())

    # metadata pages 声明
    meta = open(os.path.join(ROOT, "metadata.yaml"), "r", encoding="utf-8").read()
    check("metadata 声明 pages moe-tts", "name: moe-tts" in meta)
    check("metadata 展示名萌萌语音", "display_name: 萌萌语音" in meta)

    print(f"\nRESULT: PASS={PASS} FAIL={FAIL}")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
