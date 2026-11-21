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
    split_text_by_newline,
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
    # 文字展示按换行切，不受语音侧 newline_min_len 合并影响
    shown = split_text_by_newline("很长的第一段文字内容足够多。\n你吃了吗。")
    check("文字按换行不合并短行", len(shown) == 2 and shown[1] == "你吃了吗。", repr(shown))
    check("文字单段无换行", len(split_text_by_newline("只有一段")) == 1)

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

    print("== 标记开关默认关闭（Qwen3 不支持标记）==")
    import json as _j
    _schema = _j.load(open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                        "_conf_schema.json"), "r", encoding="utf-8"))
    check("auto_breath schema 默认 false", _schema["auto_breath"]["default"] is False)
    check("auto_effect schema 默认 false", _schema["auto_effect"]["default"] is False)

    print("== 参考音频接口（试听走文件非克隆）==")
    from server import TaskHubAdapter, TtsServeAdapter, ServerSpec, BaseAdapter
    check("TaskHub 有 voice_audio", callable(TaskHubAdapter.voice_audio))
    check("tts_serve 有 voice_audio", callable(TtsServeAdapter.voice_audio))
    check("基类 voice_audio 可调用", callable(BaseAdapter.voice_audio))

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

    print("== TaskHub 音色解析 ==")
    from server import _parse_voices_taskhub, _text_of
    tv = _parse_voices_taskhub({
        "voices_dir": "voices",
        "files": ["萌1.wav", "飒爽1.wav"],
        "texts": {"萌1.wav": "今天的晚霞超好看的", "飒爽1.wav": {"prompt_text": "我的人生我做主"}},
    })
    check("files 是 list 能解析", len(tv) == 2, str(tv))
    check("文件名做 name/file", tv[0].name == "萌1.wav" and tv[0].file == "萌1.wav")
    check("texts str 值读取", tv[0].text == "今天的晚霞超好看的")
    check("texts 对象值读取 prompt_text", tv[1].text == "我的人生我做主", str(tv[1]))
    # languages 映射（TaskHub 透传上游 tts_serve 的 language 字段）
    tv2 = _parse_voices_taskhub({
        "files": ["达妮娅.mp3"], "texts": {"达妮娅.mp3": "祝你生日快乐"},
        "languages": {"达妮娅.mp3": "zh"},
    })
    check("languages 映射解析语种", tv2[0].language == "zh", str(tv2[0]))
    check("无 languages 时语种空", tv[0].language == "", str(tv[0]))
    from server import _parse_voices_ttsserve
    ts = _parse_voices_ttsserve({"达妮娅.mp3": {"prompt_wav": "达妮娅.mp3",
        "prompt_text": "祝你生日快乐", "enabled": True, "language": "zh"}})
    check("tts_serve 直连解析语种", ts[0].language == "zh", str(ts[0]))
    check("空数据返回空", _parse_voices_taskhub({"files": [], "texts": {}}) == [])
    check("dict 变体兼容", len(_parse_voices_taskhub({"files": {"xiaoyu": "xiaoyu.wav"}, "texts": {}})) == 1)

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

    print("== 服务端连通探测（真实 HTTP）==")
    import asyncio
    import json as _json
    import threading
    import time as _time
    from http.server import BaseHTTPRequestHandler, HTTPServer
    from server import ServerSpec, TaskHubAdapter

    class _H(BaseHTTPRequestHandler):
        def do_GET(self):
            body = _json.dumps({"status": "ok", "sample_rate": 16000}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", 0), _H)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    async def _probe():
        good = TaskHubAdapter(ServerSpec(name="ok", type="taskhub",
                                         url=f"http://127.0.0.1:{port}"))
        h = await good.health()
        check("在线服务探测 ok", h.get("ok") is True, str(h))
        check("采样率从服务读取", h.get("sample_rate") == 16000, str(h))
        # 一个几乎肯定连不上的本地端口（存活服务不会监听），必须快速失败
        bad = TaskHubAdapter(ServerSpec(name="bad", type="taskhub",
                                        url="http://127.0.0.1:1"))
        t0 = _time.monotonic()
        hb = await bad.health()
        elapsed = _time.monotonic() - t0
        check("失联服务探测 fail", hb.get("ok") is False, str(hb))
        check("失联快速失败(<8s)", elapsed < 8.0, f"耗时 {elapsed:.1f}s")

    asyncio.run(_probe())
    srv.shutdown()

    print("== 联系人初始化烟雾测试（防构造期 TypeError）==")
    import tempfile as _tf
    from store import PluginStore
    from contacts import ContactsScheduler, normalize_friends, normalize_groups
    with _tf.TemporaryDirectory() as td:
        st = PluginStore(td)
        try:
            sch = ContactsScheduler(context=None, store=st, interval_min=0)
            check("ContactsScheduler 构造成功", sch.last_result is not None,
                  "contacts_meta 是属性不是方法")
            # 验证快照读写链路
            st.set_contacts([{"id": "1", "name": "好友"}], [{"id": "2", "name": "群"}],
                            synced_at="2026-01-01 00:00:00", platforms=1)
            snap = st.contacts_snapshot()
            check("联系人快照写入/读取", len(snap["friends"]) == 1 and len(snap["groups"]) == 1)

            # 音色二次同步：后端后来补了 text/language，应覆盖旧快照；本地 markup 保留
            st.set_server_voices({
                "萌1.wav": {"name": "萌1.wav", "file": "萌1.wav", "text": "", "language": ""},
                "旧音色.wav": {"name": "旧音色.wav", "file": "旧音色.wav", "text": "旧", "language": ""},
            }, source_url="http://old")
            st.server_voices.data["萌1.wav"]["markup"] = False  # 模拟本地标注
            st.set_server_voices({"萌1.wav": {"name": "萌1.wav", "file": "萌1.wav",
                                              "text": "补上的参考文本", "language": "zh"}},
                                 source_url="http://new")
            v = st.server_voices.data["萌1.wav"]
            check("二次同步覆盖 text", v["text"] == "补上的参考文本", str(v))
            check("二次同步覆盖 language", v["language"] == "zh", str(v))
            check("二次同步保留本地 markup", v.get("markup") is False, str(v))
            check("服务端删除的音色被移除",
                  "旧音色.wav" not in st.server_voices.data)
        except Exception as e:  # noqa: BLE001
            check("ContactsScheduler 构造成功", False, repr(e))

    print("== 联系人字段归一化 ==")
    fs = normalize_friends([
        {"user_id": 10001, "nickname": "小明", "remark": "大明"},
        {"uin": "10002", "nickname": "小红"},
        {"user_id": "", "nickname": "无效"},
    ])
    check("好友归一化数量", len(fs) == 2, str(fs))
    check("好友备注优先", fs[0]["name"] == "大明", str(fs[0]))
    check("好友 uin 兼容", fs[1]["id"] == "10002", str(fs[1]))
    gs = normalize_groups([
        {"group_id": 123, "group_name": "闲聊群", "member_count": 50},
        {"group_id": "456", "name": "备用名"},
    ])
    check("群归一化数量", len(gs) == 2, str(gs))
    check("群名 group_name 优先", gs[0]["name"] == "闲聊群", str(gs[0]))
    check("群名兜底", gs[1]["name"] == "备用名", str(gs[1]))

    print(f"\nRESULT: PASS={PASS} FAIL={FAIL}")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
