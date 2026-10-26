# Evaluador oculto de la tarea de extracción. Uso: python3 grade_extraccion.py <dir>
import sys, os, json
d = sys.argv[1]; res = {"checks": {}}
try:
    j = json.load(open(os.path.join(d, "lead.json"), encoding="utf-8")); c = res["checks"]
    norm = lambda s: str(s or "").strip().lower()
    c["nombre"] = norm(j.get("nombre")) == "mariela contreras"
    c["email"] = norm(j.get("email")) == "mariela.c.prueba@ejemplo.test"
    c["telefono"] = "".join(ch for ch in str(j.get("telefono", "")) if ch.isdigit()).endswith("4145550199")
    c["negocio"] = "pan del abuelo" in norm(j.get("negocio"))
    c["ciudad"] = "valencia" in norm(j.get("ciudad"))
    c["presupuesto_usd"] = j.get("presupuesto_usd") in (450, 450.0)
    c["fecha_limite"] = norm(j.get("fecha_limite")) == "2026-12-15"
    srv = [norm(x) for x in (j.get("servicios") or [])]
    c["servicios_web"] = any("web" in s or "página" in s or "pagina" in s for s in srv)
    c["servicios_instagram"] = any("instagram" in s or "publicidad" in s for s in srv)
    c["sin_pagos_online"] = j.get("pagos_online") is False
except Exception as e:
    res["error"] = repr(e)[:200]
res["aprobados"] = sum(bool(v) for v in res["checks"].values()); res["total"] = 10
print(json.dumps(res, ensure_ascii=False))
