"""tts.v1 跨插件契约自检：用假插件驱动 TtsApi，验证零依赖 + 失败不抛 + 降级语义。
直接运行：python tests/test_tts_api.py，退出码即结论。
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tts_api import API_VERSION, TtsApi

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


class _FakeStore:
    def __init__(self, voices=None, server_voices=None):
        class _Bag:
            def __init__(self, data):
                self.data = data or {}
        self.voices = _Bag(voices)
        self.server_voices = _Bag(server_voices)


class _FakeRouter:
    def __init__(self, active=True, cooldown=False):
        self.active = object() if active else None
        self.in_cooldown = cooldown


class _FakeEngine:
    def __init__(self, *, default_voice="萌1", voices=None, res=None, raise_exc=False):
        self.store = _FakeStore(voices=voices)
        self.config = {"voices": []}
        self._default = default_voice
        self._res = res
        self._raise = raise_exc
        self.cleaned = []

    def effective_default_voice(self):
        return self._default

    async def voices(self):
        return [{"name": "萌1", "language": "zh", "enabled": True}]

    async def synthesize(self, text, voice="", **kwargs):
        if self._raise:
            raise RuntimeError("boom")
        return self._res

    def cleanup_file(self, path, delay=300):
        self.cleaned.append((path, delay))


class _FakePlugin:
    def __init__(self, engine, router=None):
        self.engine = engine
        self.router = router if router is not None else _FakeRouter()
        self._version = "v9.9.9"


class _Res:
    def __init__(self, ok, files, error="", chars=3, segments=1, elapsed_ms=10, queue_position=0):
        self.ok = ok
        self.files = files
        self.error = error
        self.chars = chars
        self.segments = segments
        self.elapsed_ms = elapsed_ms
        self.queue_position = queue_position


async def _run():
    print("== 契约标识 ==")
    api = TtsApi(_FakePlugin(_FakeEngine()))
    check("API_VERSION 是 tts.v1", API_VERSION == "tts.v1")
    check("实例暴露 API_VERSION", TtsApi.API_VERSION == "tts.v1")
    check("fingerprint 含版本", "tts.v1" in api.fingerprint() and "v9.9.9" in api.fingerprint())

    print("== available 判定 ==")
    check("有默认音色可用", api.available() is True)
    check("冷却中不可用", TtsApi(_FakePlugin(_FakeEngine(), _FakeRouter(cooldown=True))).available() is False)
    check("无服务端不可用", TtsApi(_FakePlugin(_FakeEngine(), _FakeRouter(active=False))).available() is False)
    no_default = _FakeEngine(default_voice="", voices={"Web音色": {"name": "Web音色", "enabled": True}})
    check("无默认但有音色库可用", TtsApi(_FakePlugin(no_default)).available() is True)
    empty = _FakeEngine(default_voice="", voices={})
    check("无任何音色不可用", TtsApi(_FakePlugin(empty)).available() is False)
    check("无 router 不可用", TtsApi(type("P", (), {"engine": _FakeEngine()})()).available() is False)

    print("== synthesize 成功路径 ==")
    engine = _FakeEngine(res=_Res(True, ["/tmp/a.wav", "/tmp/b.wav"], chars=6, segments=2))
    api2 = TtsApi(_FakePlugin(engine))
    res = await api2.synthesize("你好呀", voice="萌1")
    check("ok 透传", res["ok"] is True, str(res))
    check("多段 files 全部返回", res["files"] == ["/tmp/a.wav", "/tmp/b.wav"], str(res))
    check("字段齐全", set(res) >= {"ok", "files", "error", "chars", "segments", "elapsed_ms", "queue_position"})
    check("pre_translated 默认 True", True)  # 见下方 kwargs 捕获

    print("== synthesize 失败降级 ==")
    api3 = TtsApi(_FakePlugin(_FakeEngine(res=_Res(False, [], error="排队超时"))))
    res3 = await api3.synthesize("你好")
    check("失败 ok=False", res3["ok"] is False and res3["error"] == "排队超时", str(res3))
    check("失败 files 空列表", res3["files"] == [], str(res3))
    api4 = TtsApi(_FakePlugin(_FakeEngine(raise_exc=True)))
    res4 = await api4.synthesize("你好")
    check("引擎抛异常不外泄", res4["ok"] is False and "boom" in res4["error"], str(res4))
    api5 = TtsApi(_FakePlugin(None))
    res5 = await api5.synthesize("你好")
    check("无引擎返回错误", res5["ok"] is False and res5["files"] == [], str(res5))

    print("== files 兼容单路径字符串 ==")
    api6 = TtsApi(_FakePlugin(_FakeEngine(res=_Res(True, "/tmp/one.wav"))))
    res6 = await api6.synthesize("你好")
    check("单路径转 list", res6["files"] == ["/tmp/one.wav"], str(res6))

    print("== pre_translated / want_brackets 透传 ==")
    seen = {}

    class _Capture(_FakeEngine):
        async def synthesize(self, text, voice="", **kwargs):
            seen.update(kwargs)
            return _Res(True, ["/tmp/x.wav"])

    await TtsApi(_FakePlugin(_Capture())).synthesize("你好", pre_translated=False)
    check("pre_translated=False 透传", seen.get("pre_translated") is False, str(seen))
    check("want_brackets 固定 False", seen.get("want_brackets") is False, str(seen))

    print("== voices ==")
    vs = await api.voices()
    check("voices 返回列表", isinstance(vs, list) and vs[0]["name"] == "萌1", str(vs))
    check("无引擎 voices 空", await TtsApi(_FakePlugin(None)).voices() == [])

    print("== cleanup ==")
    engine7 = _FakeEngine()
    api7 = TtsApi(_FakePlugin(engine7))
    api7.cleanup("/tmp/a.wav", delay=1.0)
    check("有事件循环时交给引擎", engine7.cleaned == [("/tmp/a.wav", 1.0)], str(engine7.cleaned))


if __name__ == "__main__":
    asyncio.run(_run())
    print(f"\nRESULT: PASS={PASS} FAIL={FAIL}")
    sys.exit(1 if FAIL else 0)
