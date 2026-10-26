#!/bin/bash
# Corre en el LXC 103 como unidad aparte. Para llama-server, prueba configs en :8085 y restaura.
D=/root/spec-bench; OUT=$D/resultados.jsonl; : > $OUT
KEY=$(grep -oE -- '--api-key [^ ]+' /etc/systemd/system/llama-server.service | cut -d' ' -f2)
M=/var/cache/ai/models/Qwen3.6-35B-A3B-UD-IQ4_XS.gguf
BASE="-m $M --host 127.0.0.1 --port 8085 -ngl 99 --n-cpu-moe 30 -ub 2048 -c 65536 --parallel 1 --threads 6 --reasoning-budget 0 --cache-type-k q8_0 --cache-type-v q8_0 --jinja --api-key $KEY"
echo "INICIO $(date +%T)"; systemctl stop llama-server; sleep 3
for cfg in "none|" "ngram-mod|--spec-type ngram-mod" "ngram-simple|--spec-type ngram-simple" "mtp|--spec-type draft-mtp --spec-draft-n-max 3"; do
  name=${cfg%%|*}; args=${cfg#*|}
  echo "== $name $(date +%T)"
  /opt/llama.cpp/build/bin/llama-server $BASE $args > $D/server-$name.log 2>&1 & pid=$!
  ok=0; for i in $(seq 1 120); do curl -sf http://127.0.0.1:8085/health >/dev/null && { ok=1; break; }; kill -0 $pid 2>/dev/null || break; sleep 1; done
  if [ $ok = 1 ]; then python3 -I $D/spec_prompts.py http://127.0.0.1:8085 $name "$KEY" $D/editar.py | tee -a $OUT
  else echo "{\"cfg\":\"$name\",\"error\":\"no arrancó\",\"log\":$(tail -3 $D/server-$name.log | python3 -c 'import json,sys;print(json.dumps(sys.stdin.read()[-400:]))')}" | tee -a $OUT; fi
  kill $pid 2>/dev/null; wait $pid 2>/dev/null; sleep 3
done
systemctl start llama-server; echo "FIN $(date +%T) RESTAURADO"
