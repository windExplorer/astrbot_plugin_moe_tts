"""萌萌语音核心自检：textutil 纯函数 + schema 装载期约束 + 服务端路由。
直接运行：python tests/test_core.py，退出码即结论。
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from textutil import (
    clean_tts_text,
    collapse_adjacent_repeats,
    detect_language,
    extract_brackets,
    inject_breath,
    is_error_text,
    is_speakable,
    pcm_to_wav,
    parse_origin,
    split_segments,
    strip_brackets,
    strip_markups,
)

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
    print("== 文本净化 ==")
    check("clean 去媒体标签", clean_tts_text("你好<pc_history_media images=\"1\" />世界") == "你好世界")
    check("clean 去代码块", "```" not in clean_tts_text("前```code```后"))
    check("is_speakable 空", not is_speakable("[]"))
    check("is_speakable 标记", not is_speakable("[breath]"))
    check("is_speakable 正文", is_speakable("你好[breath]"))
    check("error 回显", is_error_text("错误代码 429, request id: abc"))

    print("== 括号 / 标记 ==")
    check("剥离括号", strip_brackets("你好（这是备注）世界") == "你好世界")
    check("保留标记", "[breath]" in strip_brackets("你好（备注）[breath]"))
    check("提取括号", "这是备注" in extract_brackets("你好（这是备注）世界"))
    check("strip_markups", strip_markups("你好[breath]呀") == "你好呀")
    b = inject_breath("你好。今天好吗？", True)
    check("换气注入", b.count("[breath]") == 2, repr(b))
    check("换气幂等", inject_breath(b, True) == b)

    print("== 语种 ==")
    check("中文", detect_language("你好世界") == "zh")
    check("日文", detect_language("こんにちは") == "ja")
    check("英文", detect_language("hello world") == "en")
    check("韩文", detect_language("안녕하세요") == "ko")

    print("== 分段 ==")
    segs = split_segments("第一句。第二句！第三句？",
                          split_by_newline=False, segment_len="0", max_text_len=0)
    check("单段无切分关闭", len(segs) == 1, repr(segs))
    segs2 = split_segments("第一句话很短。第二句话也很短。第三句话收尾啦。",
                           split_by_newline=False, segment_len="6,12", max_text_len=30)
    check("窗口分段", len(segs2) >= 2, repr(segs2))
    segs3 = split_segments("嗯\n今天天气不错我们出去玩吧",
                           split_by_newline=True, newline_min_len=10,
                           segment_len="0", max_text_len=0)
    check("短行合并", len(segs3) == 1, repr(segs3))
    segs4 = split_segments("a" * 500, split_by_newline=False, segment_len="0", max_text_len=200)
    check("硬切上限", len(segs4) == 3 and all(len(x) <= 200 for x in segs4),
          f"len={len(segs4)} sizes={[len(x) for x in segs4]}")

    print("== 重复折叠 ==")
    _dup = "好嘞，我这就给你画一张超好看的专属画像吧！"
    check("折叠紧邻重复", collapse_adjacent_repeats(_dup + _dup) == _dup)
    check("短重复不折叠", collapse_adjacent_repeats("哈哈哈哈") == "哈哈哈哈")

    print("== 会话来源解析 ==")
    g = parse_origin("aiocqhttp:GroupMessage:123456")
    check("群聊识别", g["is_group"] and g["group_id"] == "123456" and g["user_id"] == "", str(g))
    f = parse_origin("aiocqhttp:FriendMessage:10001")
    check("私聊识别", (not f["is_group"]) and f["user_id"] == "10001" and f["group_id"] == "", str(f))
    check("头像 id 群取群号", g["group_id"] == "123456")
    check("头像 id 私聊取 QQ", f["user_id"] == "10001")

    print("== PCM -> WAV ==")
    wav = pcm_to_wav(b"\x00\x00" * 24000, sample_rate=24000)
    check("WAV 头", wav[:4] == b"RIFF" and wav[8:12] == b"WAVE")
    check("WAV 采样率", int.from_bytes(wav[24:28], "little") == 24000)

    print("== _conf_schema.json 装载期约束 ==")
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    with open(os.path.join(root, "_conf_schema.json"), "r", encoding="utf-8") as f:
        schema = json.load(f)
    VALID = {"int", "float", "bool", "string", "text", "list", "file",
             "object", "template_list", "dict"}

    def walk(node, path=""):
        if not isinstance(node, dict):
            return
        if "type" in node:
            check(f"type 合法 {path}", node["type"] in VALID, f"type={node['type']}")
        if node.get("type") == "object" and isinstance(node.get("items"), dict):
            for k, v in node["items"].items():
                walk(v, path + "." + k)
        if isinstance(node.get("items"), dict) and "type" not in node.get("items", {}):
            # template_list 的 items 是子项描述 dict-of-dict，递归检查每个子项
            for k, v in node["items"].items():
                if isinstance(v, dict):
                    walk(v, path + ".items." + k)

    for key, node in schema.items():
        walk(node, key)
        # template_list 的 templates 每项 items 每个子节点必须有 type
        if node.get("type") == "template_list":
            for tname, tmpl in (node.get("templates") or {}).items():
                for k, sub in (tmpl.get("items") or {}).items():
                    check(f"template {tname}.{k} 有 type", isinstance(sub, dict) and "type" in sub)

    print("== 服务端路由（单选）==")
    from server import TTSRouter
    r = TTSRouter([
        {"name": "A", "type": "taskhub", "url": "http://a:9000", "enabled": True},
        {"name": "B", "type": "tts_serve", "url": "http://b:50001", "enabled": False},
    ])
    check("默认启用第一个", r.active.name == "A" and r.active.type == "taskhub")
    r.set_active(1)
    check("切换单选", r.active.name == "B" and r.active.type == "tts_serve")
    check("只启用一个", sum(1 for s in r.specs if s.enabled) == 1)
    check("tts_serve 支持 ASR", callable(r.adapter.asr))
    check("冷却初始 False", not r.in_cooldown)

    print(f"\nRESULT: PASS={PASS} FAIL={FAIL}")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
