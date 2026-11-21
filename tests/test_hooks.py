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

    # 守卫「补发正文保留完整原文」：
    # 文字气泡必须显示完整原文（含括号语气描写，括号在前、正文在后），
    # 语音侧才剥括号。曾错误地在单段时剥括号，导致顺序变成「正文+括号」两条。
    seg_fn = extract_methods(src, ["_seg_text_for"]).get("_seg_text_for")
    check("抠到 _seg_text_for", seg_fn is not None)
    if seg_fn:
        class P:
            _seg_text_for = seg_fn
        class Eng:
            def _segment(self, t): return [t]
        p = P(); p.engine = Eng()
        raw = "（迷迷糊糊，声音很轻）\n吃的什么。"
        one = p._seg_text_for(raw, 0, 1, {"skip_bracket_tts": True})
        check("单段补发正文保留原文括号", one == raw, repr(one))
        many = p._seg_text_for(raw, 0, 2, {"skip_bracket_tts": True})
        check("多段补发正文保留原文括号", many == raw, repr(many))

    # 守卫「both 模式不单独补发括号」：括号补发条件必须限定 voice_only，
    # 否则正文（完整原文含括号）+ 括号补发 = 重复两条。
    import ast as _ast
    tree = _ast.parse(src)
    cls = next((n for n in tree.body
                if isinstance(n, _ast.ClassDef) and n.name == "MoeTtsPlugin"), None)
    dtts = next((n for n in cls.body if isinstance(n, (_ast.FunctionDef, _ast.AsyncFunctionDef))
                 and n.name == "_do_tts"), None) if cls else None
    bracket_guarded = False
    if dtts:
        for node in _ast.walk(dtts):
            if isinstance(node, _ast.If):
                cond = _ast.unparse(node.test)
                # 找到「括号补发」那个 if：条件里同时出现 brackets / res.brackets
                body_src = _ast.unparse(node)
                if "brackets" in cond and "voice_only" in cond:
                    bracket_guarded = True
    check("括号补发仅限 voice_only", bracket_guarded,
          "both 模式正文已含括号，不能再单独补发")

    # 守卫「文字补发不按语音段数截断」：
    # 语音侧剥括号后段数常少于完整原文，旧实现把 _seg_text_for 的 total
    # 传成 len(res.files)，尾部文字（括号描写段 + 末段）永远发不出去。
    dtts_src = _ast.unparse(dtts) if dtts else ""
    check("文字段数不按语音段数截断",
          "len(text_segs)" in dtts_src and "_seg_text_for(full, i, len(res.files)" not in dtts_src,
          "补发必须按原文分段发完，不能按语音段数截断")
    cancel_blocks = [n for n in _ast.walk(dtts)
                     if isinstance(n, _ast.ExceptHandler)
                     and "CancelledError" in (_ast.unparse(n.type) if n.type else "")] if dtts else []
    check("取消时补发文字",
          bool(cancel_blocks) and all("Plain(full)" in _ast.unparse(b) for b in cancel_blocks),
          "取消时文字已从结果链移除，必须补发完整原文")
    # 守卫「文字按换行独立分段」：文字气泡不能受语音侧 newline_min_len 合并影响，
    # 必须走 split_text_by_newline，而不是 engine._segment。
    check("文字段走独立按换行分段",
          "split_text_by_newline" in dtts_src,
          "文字气泡按原文换行逐段发，语音才按配置合并短行")
    # 守卫「发送原因写入日志」：detail 必须统计语音/文字条数，并记录失败原因与取消阶段
    check("日志 detail 记录发送统计",
          "voice_ok" in dtts_src and "text_ok" in dtts_src and "detail()" in dtts_src,
          "任务日志要说清语音/文字各发了几条")
    check("取消/失败写明语音未发原因",
          "语音未发出" in dtts_src and "stage" in dtts_src,
          "被取消时要说明语音为何没发出来（合成/发送阶段）")
    check("_realtime_send 收集失败原因",
          "errors.append" in open(MAIN, encoding="utf-8").read(),
          "发送失败要把异常原因回填到任务日志")

    # 守卫「语音概率」：概率判定必须存在且只作用于非 want（明确关键词触发不抽概率）
    src_full = open(MAIN, "r", encoding="utf-8").read()
    check("概率判定存在", "tts_probability" in src_full and "random.random()" in src_full)
    should_fn = extract_methods(src_full, ["_should_tts"]).get("_should_tts")
    check("抠到 _should_tts", should_fn is not None)
    prob_src = ""
    if cls:
        node = next((n for n in cls.body
                     if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                     and n.name == "_should_tts"), None)
        if node is not None:
            prob_src = ast.unparse(node)
    prob_lines = [l for l in prob_src.splitlines() if "random.random" in l]
    check("明确触发不受概率影响",
          bool(prob_lines) and "not want" in prob_lines[0],
          "关键词/工具触发必须始终发声")
    check("概率会话优先全局兜底",
          "prob_for" in prob_src and "tts_probability" in open(os.path.join(ROOT, "store.py"), encoding="utf-8").read(),
          "_should_tts 用 store.prob_for，会话级优先")
    # 守卫「指令卡片可回退」与「新模块进热重载」
    check("指令卡片可回退文本", "_card_comps" in src_full and "render_kv_card" in src_full)
    check("卡片用 chain_result 发出",
          "yield event.chain_result(comps)" in src_full,
          "yield 裸 Comp.Image 不会被框架 set_result，指令会没反应")
    check("新模块进热重载列表",
          '"display"' in src_full and '"card_render"' in src_full,
          "display/card_render 必须加入 _RELOAD_MODULES")

    print(f"\nRESULT: PASS={PASS} FAIL={FAIL}")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
