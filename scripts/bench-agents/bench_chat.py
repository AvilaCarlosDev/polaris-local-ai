import json, os, sys, time, urllib.request
key = [l.split('=',1)[1].strip().strip('"\'') for l in open(os.path.expanduser('~/.config/ia/secrets.env')) if l.startswith('IA_API_KEY=')][0]
BASE = 'http://100.97.88.59:8090/v1/chat/completions'
# Prompt largo tipo OpenCode: contexto de ~7k tokens (el AGENTS.md real repetido) + pregunta de código
ctx = open(os.path.expanduser('~/.config/opencode/AGENTS.md')).read()
long_prompt = ("Contexto del proyecto:\n" + ctx + "\n\n" + ctx[:9000] +
  "\n\nTarea: escribe una función en Python `parse_semver(s)` que devuelva una tupla (major, minor, patch) y lance ValueError si el formato es inválido. Solo el código y 2 líneas de explicación.")
short_prompt = "Escribe una función en Python `parse_semver(s)` que devuelva (major, minor, patch) y lance ValueError si el formato es inválido. Solo el código y 2 líneas de explicación."
def run(model, prompt, label):
    body = json.dumps({"model": model, "messages": [{"role":"user","content":prompt}], "max_tokens": 4096, "temperature": 0.2, "stream": True, "stream_options": {"include_usage": True}}).encode()
    req = urllib.request.Request(BASE, body, {"Content-Type":"application/json","Authorization":"Bearer "+key})
    t0 = time.time(); first_any = first_content = None; reasoning = content = ""; usage = timings = None
    with urllib.request.urlopen(req, timeout=900) as r:
        for line in r:
            line = line.decode().strip()
            if not line.startswith("data:") or line == "data: [DONE]": continue
            d = json.loads(line[5:])
            usage = d.get("usage") or usage; timings = d.get("timings") or timings
            for ch in d.get("choices", []):
                dl = ch.get("delta", {})
                rc, c = dl.get("reasoning_content") or "", dl.get("content") or ""
                if (rc or c) and first_any is None: first_any = time.time()-t0
                if c and first_content is None: first_content = time.time()-t0
                reasoning += rc; content += c
    tot = time.time()-t0
    res = {"modelo": model, "prueba": label, "total_s": round(tot,1), "primer_token_s": round(first_any or -1,1), "primera_respuesta_util_s": round(first_content or -1,1),
           "tok_entrada": (usage or {}).get("prompt_tokens"), "tok_salida": (usage or {}).get("completion_tokens"),
           "chars_pensando": len(reasoning), "chars_respuesta": len(content),
           "pp_tok_s": round(timings["prompt_per_second"],1) if timings else None, "gen_tok_s": round(timings["predicted_per_second"],1) if timings else None}
    print(json.dumps(res, ensure_ascii=False), flush=True)
    open(os.path.join(os.path.dirname(__file__), f"{model}-{label}.txt"), "w").write("### PENSANDO\n"+reasoning+"\n### RESPUESTA\n"+content)
model = sys.argv[1]
run(model, "Hola, responde solo: OK", "calentar")
run(model, short_prompt, "corta")
run(model, long_prompt, "larga")
