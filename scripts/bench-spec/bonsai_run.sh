#!/bin/bash
# Bonsai 27B 1-bit: llama-bench y servidor real en :8085, con y sin ngram. Restaura llama-server al final.
D=/root/spec-bench; OUT=$D/bonsai.jsonl; : > $OUT
KEY=$(grep -oE -- '--api-key [^ ]+' /etc/systemd/system/llama-server.service | cut -d' ' -f2)
M=/var/cache/ai/models/Bonsai-27B-Q1_0.gguf
echo "INICIO $(date +%T)"; systemctl stop llama-server; sleep 3
timeout 900 /opt/llama.cpp/build/bin/llama-bench -m $M -ngl 99 -p 512,4096 -n 128 -ub 512,2048 -fa 1 -o jsonl 2>$D/bonsai-bench.err | tee -a $D/bonsai-llamabench.jsonl
for cfg in "none|" "ngram-mod|--spec-type ngram-mod"; do
  name=bonsai-${cfg%%|*}; args=${cfg#*|}
  echo "== $name $(date +%T)"
  /opt/llama.cpp/build/bin/llama-server -m $M --host 127.0.0.1 --port 8085 -ngl 99 -ub 2048 -c 32768 --parallel 1 --threads 6 --reasoning-budget 0 --cache-type-k q8_0 --cache-type-v q8_0 -fa on --jinja --api-key $KEY $args > $D/server-$name.log 2>&1 & pid=$!
  ok=0; for i in $(seq 1 180); do curl -sf http://127.0.0.1:8085/health >/dev/null && { ok=1; break; }; kill -0 $pid 2>/dev/null || break; sleep 1; done
  if [ $ok = 1 ]; then
    echo "VRAM: $(cat /sys/class/drm/card*/device/mem_info_vram_used 2>/dev/null | head -1)"
    python3 -I $D/spec_prompts.py http://127.0.0.1:8085 $name "$KEY" $D/editar.py | tee -a $OUT
  else echo "{\"cfg\":\"$name\",\"error\":\"no arrancó\",\"log\":$(tail -3 $D/server-$name.log | python3 -c 'import json,sys;print(json.dumps(sys.stdin.read()[-400:]))')}" | tee -a $OUT; fi
  kill $pid 2>/dev/null; wait $pid 2>/dev/null; sleep 3
done
systemctl start llama-server; echo "FIN $(date +%T) RESTAURADO"
