#!/bin/bash
# Rondas 2-4: cada modelo x (OpenCode, Hermes) x tareas de la ronda. Evaluación con tests ocultos.
# Uso: hold the ia-local lock first (see README.md), then: OUT=/some/dir ./rondas.sh
# MODELOS y CLIENTES (opencode, hermes) se pueden fijar por entorno. OpenCode >= 2:
# sin --dir, el directorio de trabajo es el cwd; --standalone evita el servicio de fondo.
R=$(cd "$(dirname "$0")" && pwd)
OUT=${OUT:-${XDG_RUNTIME_DIR:-/tmp}/bench-agents}
RES=$OUT/resultados.jsonl; W=$OUT/trabajo; mkdir -p $W
MODELOS=${MODELOS:-"ornith-1.5-9b-q4_k_m ornith-1.5-9b-nothink qwen3-30b-a3b-instruct-2507-q4_k_m qwen3.6-35b-a3b-ud-iq4_xs"}
stats(){ ssh venator-ts "pct exec 103 -- journalctl --no-pager --since '@$1' | grep -E 'prompt eval time|       eval time'" 2>/dev/null | python3 -c "
import sys,re,json
pe=[];ev=[]
for l in sys.stdin:
    m=re.search(r'(prompt eval time|eval time) = +([0-9.]+) ms / +([0-9]+) tokens',l)
    if m: (pe if m.group(1)=='prompt eval time' else ev).append((float(m.group(2)),int(m.group(3))))
print(json.dumps({'peticiones':len(pe),'tok_entrada_1a':pe[0][1] if pe else 0,'pp_1a_tok_s':round(pe[0][1]/(pe[0][0]/1000),1) if pe else 0,'tok_entrada_total':sum(t for _,t in pe),'tok_salida_total':sum(t for _,t in ev),'gen_tok_s':round(sum(t for _,t in ev)/max(1e-9,sum(ms for ms,_ in ev)/1000),1) if ev else 0}))"; }
una(){ ronda=$1; mod=$2; cli=$3; tarea=$4
  d="$W/$ronda-$tarea-$cli-$mod"; mkdir -p "$d"; fx=$(python3 -I $R/tareas.py $tarea fixture); [ -n "$fx" ] && cp $R/fixtures/$fx/* "$d/"
  txt=$(python3 -I $R/tareas.py $tarea texto); sleep 2; s=$(date +%s)
  if [ $cli = opencode ]; then ( cd "$d" && OPENCODE_DISABLE_CLAUDE_CODE_SKILLS=1 timeout 900 opencode run --standalone --agent gentleman -m "ia-local/$mod" --auto "$txt" < /dev/null > "$d.log" 2>&1 ); rc=$?
  else ( cd "$d" && timeout 900 hermes chat --oneshot -Q --provider venator -m "$mod" --in "$d" --max-turns 30 -q "$txt" < /dev/null > "$d.log" 2>&1 ); rc=$?; fi
  e=$(date +%s); g=$(python3 -I $R/graders/grade_$tarea.py "$d" 2>/dev/null | tail -n 1 || echo '{"aprobados":0,"error":"grader"}')
  own=""; ls "$d"/test_*.py >/dev/null 2>&1 && own=$(cd "$d" && timeout 60 python3 -m pytest -q 2>&1 | tail -1)
  echo "{\"ronda\":\"$ronda\",\"modelo\":\"$mod\",\"cliente\":\"$cli\",\"tarea\":\"$tarea\",\"s\":$((e-s)),\"rc\":$rc,\"oculto\":$g,\"tests_propios\":$(python3 -c 'import json,sys;print(json.dumps(sys.argv[1]))' "$own"),\"server\":$(stats $s)}" | tee -a $RES | cut -c1-200; }
for ronda in R2 R3 R4; do
  case $ronda in R2) TS="semver";; R3) TS="bugfix extraccion";; R4) TS="cli refactor";; esac
  for mod in $MODELOS; do
    echo "######## $ronda $mod $(date +%T)"
    [ $ronda = R2 ] && { python3 -I $R/bench_chat.py "$mod" > "$W/R2-chat-$mod.jsonl" 2>&1; cat "$W/R2-chat-$mod.jsonl" | cut -c1-200; }
    for t in $TS; do for cli in ${CLIENTES:-opencode hermes}; do una $ronda $mod $cli $t; done; done
  done
done
echo "######## FIN $(date +%T)"
