#!/usr/bin/env python3
"""Mide generación con y sin decodificación especulativa contra un llama-server local."""
import json, sys, time, urllib.request
URL = sys.argv[1]; CFG = sys.argv[2]; KEY = sys.argv[3]
codigo = open(sys.argv[4]).read()
PROMPTS = {
    "tetris": "Escribe el juego Tetris completo en un solo archivo HTML con JavaScript. Solo el código.",
    "editar": "Devuelve este archivo COMPLETO, idéntico, salvo que la función `run` se llame `generar` "
              "(actualiza también donde se llama). Solo el código, sin explicaciones.\n\n```python\n" + codigo + "\n```",
    "chat": "Explica en 5 frases por qué el cielo es azul.",
}
for name, p in PROMPTS.items():
    body = json.dumps({"messages": [{"role": "user", "content": p}], "max_tokens": 2048,
                       "temperature": 0, "seed": 1}).encode()
    req = urllib.request.Request(URL + "/v1/chat/completions", data=body,
                                 headers={"Content-Type": "application/json", "Authorization": "Bearer " + KEY})
    t0 = time.time()
    try:
        d = json.load(urllib.request.urlopen(req, timeout=900))
    except Exception as e:
        print(json.dumps({"cfg": CFG, "prompt": name, "error": repr(e)[:200]}), flush=True); continue
    t = d.get("timings", {})
    out = d["choices"][0]["message"]["content"]
    print(json.dumps({"cfg": CFG, "prompt": name, "s": round(time.time() - t0, 1),
                      "tok_salida": t.get("predicted_n"), "gen_tok_s": round(t.get("predicted_per_second", 0), 1),
                      "pp_tok_s": round(t.get("prompt_per_second", 0), 1),
                      "draft_n": t.get("draft_n"), "draft_aceptados": t.get("draft_n_accepted"),
                      "renombro_ok": ("def generar(" in out and "def run(" not in out) if name == "editar" else None}),
          flush=True)
