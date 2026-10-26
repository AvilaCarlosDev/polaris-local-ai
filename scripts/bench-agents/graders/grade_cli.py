# Evaluador oculto de la CLI de notas. Uso: python3 grade_cli.py <dir>
import sys, os, json, subprocess, tempfile, shutil
d = sys.argv[1]; res = {"checks": {}}
def run(cwd, *args):
    p = subprocess.run([sys.executable, os.path.join(cwd, "notas.py"), *args], cwd=cwd, capture_output=True, text=True, timeout=20)
    return p.returncode, p.stdout.strip(), p.stderr.strip()
try:
    t = tempfile.mkdtemp(); shutil.copy(os.path.join(d, "notas.py"), t); c = res["checks"]
    r1 = run(t, "add", "Comprar harina", "--tag", "compras")
    r2 = run(t, "add", "Llamar a Mariela por la web")
    r3 = run(t, "add", "Comprar levadura", "--tag", "compras")
    c["add_ok"] = all(r[0] == 0 for r in (r1, r2, r3))
    c["guarda_json"] = os.path.exists(os.path.join(t, "notas.json")) and len(json.load(open(os.path.join(t, "notas.json")))) == 3
    rc, out, _ = run(t, "list"); lines = [l for l in out.splitlines() if l.strip()]
    c["list_formato"] = rc == 0 and lines == ["1. Comprar harina [compras]", "2. Llamar a Mariela por la web", "3. Comprar levadura [compras]"]
    rc, out, _ = run(t, "search", "comprar"); lines = [l for l in out.splitlines() if l.strip()]
    c["search_insensible_mayus"] = rc == 0 and lines == ["1. Comprar harina [compras]", "3. Comprar levadura [compras]"]
    rc, out, _ = run(t, "list", "--tag", "compras"); lines = [l for l in out.splitlines() if l.strip()]
    c["filtro_tag"] = rc == 0 and len(lines) == 2
    rc, out, _ = run(t, "search", "xyz")
    c["search_sin_resultados"] = rc == 0 and out == "Sin resultados"
    rc, _, _ = run(t, "borrar-todo")
    c["comando_invalido_falla"] = rc != 0
    shutil.rmtree(t, ignore_errors=True)
except Exception as e:
    res["error"] = repr(e)[:200]
res["aprobados"] = sum(bool(v) for v in res["checks"].values()); res["total"] = 7
print(json.dumps(res, ensure_ascii=False))
