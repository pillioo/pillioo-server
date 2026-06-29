import marshal

with open(r"scripts\rag\chunking\__pycache__\document.cpython-311.pyc", "rb") as f:
    f.read(16)
    code = marshal.loads(f.read())


def dump_code(co, indent=0):
    prefix = "  " * indent
    print(prefix + "co_name=" + repr(co.co_name))
    print(prefix + "co_consts=" + repr([c for c in co.co_consts if isinstance(c, str)]))
    print(prefix + "co_names=" + repr(list(co.co_names)))
    for c in co.co_consts:
        if hasattr(c, "co_name"):
            dump_code(c, indent+1)


dump_code(code)
