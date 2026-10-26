# Evaluador oculto de semver. Uso: python3 grade_semver.py <dir>
import sys, os, json, importlib.util
d = sys.argv[1]; res = {"checks": {}}
try:
    spec = importlib.util.spec_from_file_location("sv", os.path.join(d, "semver.py")); m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); f = m.parse_semver; c = res["checks"]
    c["valido_basico"] = f("1.2.3") == (1, 2, 3)
    c["valido_ceros"] = f("0.0.0") == (0, 0, 0)
    c["valido_grande"] = f("10.20.300") == (10, 20, 300)
    c["devuelve_enteros"] = all(type(x) is int for x in f("4.5.6"))
    for nombre, mal in [("dos_partes", "1.2"), ("cuatro_partes", "1.2.3.4"), ("letras", "a.b.c"), ("vacio", ""), ("negativo", "-1.2.3"), ("parte_vacia", "1..3")]:
        try: f(mal); c["invalido_" + nombre] = False
        except ValueError: c["invalido_" + nombre] = True
        except Exception: c["invalido_" + nombre] = False
except Exception as e:
    res["error"] = repr(e)[:200]
res["aprobados"] = sum(bool(v) for v in res["checks"].values()); res["total"] = 10
print(json.dumps(res, ensure_ascii=False))
