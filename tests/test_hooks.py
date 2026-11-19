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

    print(f"\nRESULT: PASS={PASS} FAIL={FAIL}")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
