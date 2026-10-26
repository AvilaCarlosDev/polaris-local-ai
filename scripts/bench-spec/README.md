# bench-spec — speculative decoding and Bonsai 27B on the RX 580

Run on LXC 103 as a transient unit (they stop `llama-server`, use port 8085 and
start it again at the end). Copy the three files plus `editar.py` (any ~100-line
source file; the 2026-10-25 run used `scripts/bench-images-tasks.py`) to
`/root/spec-bench/`, hold the `ia-local` lock, then:

```bash
systemd-run --unit=specbench  --wait --collect /root/spec-bench/spec_run.sh
systemd-run --unit=bonsaibench --wait --collect /root/spec-bench/bonsai_run.sh
```

Prompts (`spec_prompts.py`, temperature 0): write Tetris in HTML (new code),
return a file with one function renamed (edit), and a 5-sentence chat answer.
Results: `docs/BENCHMARKS.md` → *Speculative decoding and Bonsai 27B*.
