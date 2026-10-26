# Evaluador oculto de la refactorización. Uso: python3 grade_refactor.py <dir>
import sys, os, json, ast, importlib.util
d = sys.argv[1]; here = os.path.dirname(os.path.abspath(__file__)); res = {"checks": {}}
def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path); m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m
CASOS = [
    "vendedor,cantidad,precio\nana,2,10.5\nluis,1,100\nana,3,1.25\n",
    "vendedor,cantidad,precio\nzoe,1,0.1\nzoe,2,0.2\n\nbea,10,3.333\n",
    "precio,vendedor,cantidad\n5,carla,4\n2.5,dani,2\n",
]
try:
    orig = load(os.path.join(here, "reporte_original.py"), "orig"); new = load(os.path.join(d, "reporte.py"), "new"); c = res["checks"]
    for i, caso in enumerate(CASOS):
        c[f"mismo_resultado_{i+1}"] = new.generar_reporte(caso) == orig.generar_reporte(caso)
    tree = ast.parse(open(os.path.join(d, "reporte.py"), encoding="utf-8").read())
    funcs = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]
    c["al_menos_3_funciones"] = len(funcs) >= 3
    c["docstrings"] = sum(1 for f in funcs if ast.get_docstring(f)) >= 3
    rd = os.path.join(d, "README.md")
    txt = open(rd, encoding="utf-8").read().lower() if os.path.exists(rd) else ""
    c["readme_con_uso"] = "## uso" in txt and "generar_reporte" in txt
except Exception as e:
    res["error"] = repr(e)[:200]
res["aprobados"] = sum(bool(v) for v in res["checks"].values()); res["total"] = 6
print(json.dumps(res, ensure_ascii=False))
