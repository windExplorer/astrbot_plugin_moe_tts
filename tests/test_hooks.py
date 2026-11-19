"""钩子辅助方法自检：从 main.py 用 AST 原样抠出 _flag/_set_flag/_get_flag/_clear
并 exec 到一个假类上，验证真实调用链不会因参数签名不一致抛 TypeError。

本地没有 astrbot 运行时，无法实例化 Star；但这类 bug（方法签名与调用不符）
只要按磁盘上的真代码驱动一遍就能发现，无需真环境。
直接运行：python tests/test_hooks.py。
"""
import ast
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
MAIN = os.path.join(ROOT, "main.py")
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


def extract_methods(source: str, names: list[str]) -> dict:
    tree = ast.parse(source)
    cls = next((n for n in tree.body
                if isinstance(n, ast.ClassDef) and n.name == "MoeTtsPlugin"), None)
    if cls is None:
        raise RuntimeError("找不到 MoeTtsPlugin 类")
    out = {}
    for node in cls.body:
        if isinstance(node, ast.FunctionDef) and node.name in names:
            # 去掉装饰器（这些方法没有，但保险起见）
            node.decorator_list = []
            mod = ast.Module(body=[node], type_ignores=[])
            ast.fix_missing_locations(mod)
            ns = {}
            exec(compile(mod, "<ast>", "exec"), ns)
            out[node.name] = ns[node.name]
    return out


def main():
    with open(MAIN, "r", encoding="utf-8") as f:
        src = f.read()
    methods = extract_methods(src, ["_flag", "_set_flag", "_get_flag", "_clear"])
    check("四个方法都抠到", set(methods) == {"_flag", "_set_flag", "_get_flag", "_clear"},
          str(list(methods)))

    class Fake:
        pass

    for name, fn in methods.items():
        setattr(Fake, name, fn)

    obj = Fake()
    obj._flags = {}

    class Ev:
        message_id = "msg-001"

    ev = Ev()
    errors = []
    try:
        obj._set_flag(ev, "is_llm", True)
        v = obj._get_flag(ev, "is_llm", False)
        check("_set_flag/_get_flag 往返", v is True, f"got {v!r}")
    except Exception as e:  # noqa: BLE001
        errors.append(f"set/get: {e!r}")
    try:
        obj._set_flag(ev, "suppress", True)
        obj._clear(ev)
        check("_clear 清除标记", obj._get_flag(ev, "suppress", False) is False)
    except Exception as e:  # noqa: BLE001
        errors.append(f"clear: {e!r}")

    if errors:
        for e in errors:
            check("钩子辅助方法无参数错误", False, e)
    else:
        check("钩子辅助方法无参数错误", True)

    # 守卫「_refresh_cfg 不得用全局 context.get_config() 覆盖插件配置」：
    # 这个 bug 曾导致 WebUI 配置保存后仍显示为空。
    refresh = extract_methods(src, ["_refresh_cfg"]).get("_refresh_cfg")
    check("抠到 _refresh_cfg", refresh is not None)
    if refresh:
        class Ctx:
            def get_config(self):
                return {"global_cmd": "not plugin config"}  # 模拟全局配置

        class P:
            _refresh_cfg = refresh

        p = P()
        p.context = Ctx()
        p.config = {"auto_tts": True, "timeout": 250}  # 插件自己的配置
        got = p._refresh_cfg()
        check("_refresh_cfg 返回插件配置不变",
              got == {"auto_tts": True, "timeout": 250} and p.config is got,
              f"got={got!r}")
        # 静态守卫（AST）：_refresh_cfg 的真实调用里不应有 context.get_config(...)
        # 用 AST 遍历才不会被 docstring/注释里的字样误伤。
        import ast as _ast
        tree = _ast.parse(src)
        cls = next((n for n in tree.body
                    if isinstance(n, _ast.ClassDef) and n.name == "MoeTtsPlugin"), None)
        fn = next((n for n in cls.body if isinstance(n, _ast.FunctionDef)
                   and n.name == "_refresh_cfg"), None) if cls else None
        bad_calls = []
        if fn:
            for node in _ast.walk(fn):
                if (isinstance(node, _ast.Call) and isinstance(node.func, _ast.Attribute)
                        and node.func.attr == "get_config"):
                    bad_calls.append(node.lineno)
        check("_refresh_cfg 不调用 context.get_config", fn is not None and not bad_calls,
              f"bad call lines={bad_calls}")

    # 守卫「主动发送必须包 MessageChain」：
    # 曾因直接传 list 给 send_message 报 'list' object has no attribute 'chain'
    import ast as _ast
    tree = _ast.parse(src)
    cls = next((n for n in tree.body
                if isinstance(n, _ast.ClassDef) and n.name == "MoeTtsPlugin"), None)
    rsend = next((n for n in cls.body if isinstance(n, (_ast.FunctionDef, _ast.AsyncFunctionDef))
                  and n.name == "_realtime_send"), None) if cls else None
    has_send = False
    has_wrap = False
    if rsend:
        for node in _ast.walk(rsend):
            if isinstance(node, _ast.Call):
                f = node.func
                if isinstance(f, _ast.Attribute) and f.attr == "send_message":
                    has_send = True
                if isinstance(f, _ast.Name) and f.id == "MessageChain":
                    has_wrap = True
    check("_realtime_send 主动发送包 MessageChain",
          rsend is not None and has_send and has_wrap,
          f"send={has_send} wrap={has_wrap}")

    # 守卫「补发正文不重复带括号」：
    # 单段时曾直接 return full，导致文字气泡带括号 + 括号又单独补发一次
    import sys as _sys
    _sys.path.insert(0, ROOT)
    import textutil as _tu
    seg_fn = extract_methods(src, ["_seg_text_for"]).get("_seg_text_for")
    check("抠到 _seg_text_for", seg_fn is not None)
    if seg_fn:
        # 给 exec 出来的函数补上它依赖的全局名
        seg_fn.__globals__["textutil_mod"] = _tu
        class P:
            _seg_text_for = seg_fn
        class Eng:
            def _segment(self, t): return [t]
        p = P(); p.engine = Eng()
        cfg_on = {"skip_bracket_tts": True}
        cfg_off = {"skip_bracket_tts": False}
        raw = "（迷迷糊糊，声音很轻）吃的什么。"
        one = p._seg_text_for(raw, 0, 1, cfg_on)
        check("单段补发正文剥离括号", one == "吃的什么。", repr(one))
        many = p._seg_text_for(raw, 0, 2, cfg_on)
        check("多段补发正文剥离括号", "迷迷糊糊" not in many, repr(many))
        keep = p._seg_text_for(raw, 0, 1, cfg_off)
        check("关闭剥离时保留括号", keep == raw, repr(keep))

    print(f"\nRESULT: PASS={PASS} FAIL={FAIL}")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
