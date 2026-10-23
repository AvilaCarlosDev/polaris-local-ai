# Release comparison on Venator — 2026-10-22

The release changes memory fitting, image residency and deferred cache recovery.
This report separates same-day paired measurements from historical context.
The paired run preserves dense-model decode performance and fixes lost cache
when text arrives after an image restart has become healthy: about 208–210 seconds
became 1.83–2.12 seconds in this controlled case. No general inference speedup is claimed.

## Text generation and latency

Decode tok/s: median [minimum–maximum], n=2 per state. Historical values are
references from the October 6–8 table; only Before and After are the paired A/B.

| Model | Historical tok/s | Before tok/s | After tok/s |
|---|---:|---:|---:|
| Qwen Coder 1.5B | 99.2 | 98.68 [98.26–99.11] | 98.60 [98.45–98.75] |
| Qwen VL 3B | 66.4 | 65.59 [65.58–65.59] | 65.61 [65.59–65.63] |
| Qwen 7B | 34.2 | 34.11 [34.01–34.21] | 34.09 [34.04–34.14] |
| Qwen Coder 7B | 34.3 | 34.02 [33.96–34.07] | 33.99 [33.95–34.04] |
| Ornith 9B | 28.0 | 27.79 [27.78–27.79] | 27.80 [27.73–27.87] |
| Qwen3 MoE 30B | 21.3 | 19.53 [18.41–20.64] | 21.09 [21.08–21.10] |

The five dense-model medians differ by less than 0.1% in this sample. The MoE
sample is faster, but n=2 does not establish a speedup. No large decode regression
was observed. The earlier three-token MoE result was not a throughput benchmark.

Wall time in seconds (median, n=2). Cold includes swaps and unflushed OS caches;
load-time differences must not be attributed solely to this router change.

| Model | Cold before → after | Warm before → after |
|---|---:|---:|
| Qwen Coder 1.5B | 9.79 → 8.22 | 3.05 → 3.07 |
| Qwen VL 3B | 12.95 → 14.97 | 4.58 → 4.60 |
| Qwen 7B | 24.60 → 19.11 | 8.81 → 8.83 |
| Qwen Coder 7B | 20.59 → 20.67 | 8.83 → 8.85 |
| Ornith 9B | 25.90 → 25.40 | 10.96 → 10.96 |
| Qwen3 MoE 30B | 55.58 → 54.91 | 15.46 → 14.27 |

## Delayed text after image generation

This deliberately waits for upstream health **before** sending the next text
request. It tests the formerly skipped deferred-restore branch, not total
image-to-chat time from the instant an image request ends. Each arm uses the same
23,026-token prompt; n=1 per image model.

| Image backend | Image request s, before → after | Subsequent text s, before → after | Cached input tokens, before → after |
|---|---:|---:|---:|
| sd15 | 34.68 → 34.36 | 207.98 → 1.83 | 0 → 23025 |
| sd35 | 72.73 → 72.41 | 209.68 → 2.12 | 0 → 23025 |

Both old transitions left an image backend active. Both new transitions left
both image backends inactive. The generated PNG SHA-256 matches before/after for
each model; all four files are nonconstant 512×512 PNGs.

The older `bench-slots.py` image check sent text immediately after the image,
while the server could still be starting. That exercised a different branch and
recorded approximately 8 seconds. These results do not invalidate that historical
measurement: waiting until healthy exposed the deferred-restore bug. The new
HTTP regression test covers that ordering and complete 503 error responses.

For SD 3.5 → text, sampled peak VRAM during the subsequent text call fell from
7.84 to 6.13 GiB, and GTT from 4.04 to 0.09 GiB. These are phase-specific peaks:
the transient GTT peak during image generation itself remained about 5.58 GiB.
No OOM or OOM-kill event was recorded by the container. Cgroup page-cache charge
moves across service restarts, so cgroup memory is retained as raw evidence and
is not presented as a physical-RAM saving.

## Protocol

- Baseline router: commit `9e11cc9`; candidate: `0acf95a`.
- Same CT 103, models, engine binary and host kernel for both arms. Model file
  sizes and timestamps, engine version and Mesa version are recorded in evidence.
- Benchmark requests explicitly select local model IDs. Normal OpenCode usage
  keeps all providers available and allows switching between local and cloud models.
- Six model IDs, two cold/warm pairs each, one request at a time. Temperature 0,
  maximum 300 generated tokens. Exact prompt and its SHA-256 are in every run's
  metadata. Cold includes the model swap; warm is the immediate identical request.
- A model's saved slot file is preserved outside the active slot directory before
  each cold call. Existing user caches are restored after the experiment.
- The first baseline 1.5B cold row was collected before startup readiness was
  explicitly checked. It is retained in raw data but replaced in cold statistics
  by `before-startup-supplement`; the original warm row remains valid. The
  candidate startup attempt that refused a connection produced no samples and
  is recorded separately. The driver now waits for router and upstream health.
- Cold means a model swap, not a flush of OS page cache or shader caches. Those
  caches are not cleared; load-time variation is reported rather than attributed
  solely to router code.
- VRAM/GTT and llama-server cgroup memory are sampled every 250 ms. Cold peaks
  include the departing model; cgroup memory also includes charged page cache.
  These are workflow peaks, not model tensor sizes or physical RAM-only measures.
- Image checks use SD 1.5 and SD 3.5 separately, 512×512, 20 steps, the same fox
  prompt, one generation per image model per arm. The router does not fix a seed;
  these are transition/caching checks, not an image quality A/B.
- A frozen 70,000-character corpus primes Qwen 2.5 7B, followed by image generation,
  an explicit wait for llama-server health, and the identical long-prompt request.
  The reported after-image chat latency excludes that explicit readiness wait.
- Repetitions are n=2 per text state and n=1 per image transition. Report medians
  and ranges as descriptive measurements; do not claim statistical significance.

## Reproduction

Run `scripts/bench-release.py` on an isolated CT with each router revision deployed
in turn. It reads the API key from `/etc/ia/api-key` and never prints it. Pause
other clients, preserve service configuration and slot files, and restore the
candidate plus normal services afterwards. Do not run both arms concurrently.

```bash
python3 scripts/bench-release.py --label before-9e11cc9 --reps 2 --out before-text.jsonl
python3 scripts/bench-release.py --label after-0acf95a --reps 2 --out after-text.jsonl
```

Create the exact source corpus by concatenating `docs/BENCHMARKS.md` and
`docs/TROUBLESHOOTING.md` from commit `9e11cc9`, in that order, without separators.
The driver repeats/truncates it to 70,000 characters and records the effective hash.
For each deployed arm:

```bash
python3 scripts/bench-release.py --label before-9e11cc9 --mode image --corpus corpus.txt --out before-image.jsonl
```

## Historical interpretation

The October 8 table used approximately 300 generated tokens, but its exact text
prompt was not retained. Those published numbers remain historical references.
The earlier October 22 smoke replies generated only 3–4 tokens and must not be
used as throughput benchmarks. Likewise, the 134.4-second Hermes tool check and
the 252.6-second synthetic compression check used different workloads from the
historical agent runs; they demonstrate successful execution, not speedup.

## Evidence and verification

- [Before text](evidence/2026-10-22-release-before-text.jsonl),
  [startup supplement](evidence/2026-10-22-release-before-startup-supplement.jsonl),
  [after text](evidence/2026-10-22-release-after-text.jsonl).
- [Before images](evidence/2026-10-22-release-before-image.jsonl),
  [after images](evidence/2026-10-22-release-after-image.jsonl).
- [Environment and model inventory](evidence/2026-10-22-release-environment.json),
  [PNG and final service validation](evidence/2026-10-22-release-artifacts.json).
- [Candidate startup attempt](evidence/2026-10-22-release-after-text-startup-race.jsonl)
  contains metadata only; no measurement was collected in that failed attempt.

The engine was llama.cpp 0.5.0-dev, commit 0c1e570, Mesa 25.0.7, kernel
7.0.14-22-pve. All recorded GGUF sizes and modification times remained unchanged.
Final services: router and Ornith active at 64K/one slot, both image services
inactive, Whisper CPU service active. The Hermes gateway was resumed afterwards.

Checks: 40 pytest tests, ruff, ShellCheck and Bash syntax verification. An idle
PCIe observation was recorded as idle; no active-link throughput conclusion is drawn.

## Review boundaries

The prepared local branches form three review slices, in this order. No branch
has been pushed and no PR has been opened.

| Slice | Branch | Base | Scope |
|---|---|---|---|
| 1 | `fix/local-agent-stability-20261022` | `main` at `9e11cc9` | Runtime fixes, regression tests and client guidance; ends at `6a07f7f` |
| 2 | `bench/release-validation-20261022` | Slice 1 | Reproduction driver and raw evidence; commit `15ef9cd` |
| 3 | `docs/release-comparison-20261022` | Slice 2 | This report, historical interpretation, changelog and documentation links |

```text
main → repair → benchmark evidence → comparison documentation
```

Validation: the runtime passed 40 pytest checks and repository lint/shell checks;
the driver completed both controlled arms. Evidence parses successfully, report
links resolve locally, and the changed artifacts contain no credential-shaped
literals. OpenCode lists 42 `opencode`, 28 `opencode-go`, and seven `ia-local`
models after removing the local-only provider allowlist. Cloud inference was not
invoked for this catalog check.

Rollback boundaries follow the slices: the report can be removed without changing
the evidence or runtime; the benchmark driver and dated raw files can be removed
without changing runtime behavior. Runtime rollback is documented in
[LOCAL-STABILITY.md](LOCAL-STABILITY.md).
