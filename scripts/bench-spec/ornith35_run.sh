#!/bin/bash
# Ornith 1.5 35B-A3B: ajuste de --n-cpu-moe con -c 65536 y prueba de MTP/ngram. Restaura llama-server.
D=/root/spec-bench; OUT=$D/ornith35.jsonl; : > $OUT
KEY=$(grep -oE -- '--api-key [^ ]+' /etc/systemd/system/llama-server.service | cut -d' ' -f2)
M=/var/cache/ai/models/Ornith-1.5-35B-A3B-AD-IQ4_XS-IQ3_S.gguf
COMMON="-m $M --host 127.0.0.1 --port 8085 -ngl 99 -ub 2048 -c 65536 --parallel 1 --threads 6 --cache-type-k q8_0 --cache-type-v q8_0 --jinja --api-key $KEY"
vram(){ cat /sys/class/drm/card*/device/mem_info_vram_used 2>/dev/null | sort -n | tail -1; }
echo "INICIO $(date +%T)"; systemctl stop llama-server; sleep 3
for cfg in "ncmoe32|--n-cpu-moe 32" "ncmoe30|--n-cpu-moe 30" "ncmoe28|--n-cpu-moe 28" "ncmoe30-mtp|--n-cpu-moe 30 --spec-type draft-mtp --spec-draft-n-max 3" "ncmoe30-ngram|--n-cpu-moe 30 --spec-type ngram-mod"; do
  name=${cfg%%|*}; args=${cfg#*|}
  echo "== $name $(date +%T)"
  /opt/llama.cpp/build/bin/llama-server $COMMON $args > $D/server-o35-$name.log 2>&1 & pid=$!
  ok=0; for i in $(seq 1 180); do curl -sf http://127.0.0.1:8085/health >/dev/null && { ok=1; break; }; kill -0 $pid 2>/dev/null || break; sleep 1; done
  if [ $ok = 1 ]; then
    echo "{\"cfg\":\"$name\",\"vram_bytes\":$(vram)}" | tee -a $OUT
    python3 -I $D/spec_prompts.py http://127.0.0.1:8085 $name "$KEY" $D/editar.py | tee -a $OUT
  else echo "{\"cfg\":\"$name\",\"error\":\"no arrancó\",\"log\":$(grep -v api-key $D/server-o35-$name.log | tail -4 | python3 -c 'import json,sys;print(json.dumps(sys.stdin.read()[-500:]))')}" | tee -a $OUT; fi
  kill $pid 2>/dev/null; wait $pid 2>/dev/null; sleep 3
done
grep -hiE "nextn|mtp" $D/server-o35-ncmoe30.log | grep -v api-key | head -3
systemctl start llama-server; echo "FIN $(date +%T) RESTAURADO"
