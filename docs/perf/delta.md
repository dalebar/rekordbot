# Delta — Baseline 2 (Martyn N=52) vs Post-Scope-Reduction (Josey N=40)

**Pre:** `docs/perf/baseline-03-martyn.md` — build `18d74a0` (pre-6d.1 develop HEAD)
**Post:** `docs/perf/post-scope-reduction-04-josey-rebelle.md` — build `2826625` (6d.1 Commit 5 HEAD)
**Phase 6d Decision Point prediction:** ~25× speedup on analysis-per-track wall-clock by retiring `analysis_detect_key`.
**Actual:** 19.5× speedup on per-track mean, with the shortfall explained by I/O-bound variance on cold-cache external storage.

This delta confirms the Phase 6d Decision Point. The bottleneck was real and was retired cleanly; the analysis stage now operates at the speed predicted by the residual non-key inner stages, with the new ceiling being librosa's audio-decode I/O rather than computation.

## Headline

The analysis-per-track wall-clock mean dropped by an order of magnitude, from ~12 seconds to under one second. Across a corpus, this is the difference between "process new music while you make a coffee" and "process new music in the time it takes to switch windows."

| Metric | Pre (Martyn N=52) | Post (Josey N=40) | Change |
|---|---:|---:|---:|
| `analysis_track` mean | 11.8726 s | 0.6096 s | **−95% (19.5× faster)** |
| `analysis_track` total stage time | 617.38 s | 24.38 s | −95% |
| `analysis_track` p95 | 18.29 s | 0.77 s | −96% |
| `analysis_detect_key` | 11.40 s mean × 52 = 593 s | (stage removed) | gone |
| Analysis stage as % of session wall-clock | ~57% of 17m 55s | ~20% of 2m 3s | structurally smaller |

The 19.5× per-track speedup is the empirical confirmation. The Decision Point's 25× prediction was based on subtracting `analysis_detect_key`'s mean from `analysis_track`'s mean and assuming the residual stages would behave as they did under the pre-6d.1 distribution. The actual residual distribution is different in shape — see below — but the overall direction and magnitude match.

## Per-stage shift

The dominance pattern flipped. Pre-6d.1, key detection was 96% of analysis time and everything else was rounding error. Post-6d.1, the load is more evenly distributed across the surviving stages, with librosa audio decode taking over the lead role.

### Analysis pipeline

| Stage | Pre mean (s) | Pre share | Post mean (s) | Post share | Notes |
|---|---:|---:|---:|---:|---|
| `analysis_read_tags` | 0.0066 | 0.1% | 0.0044 | 0.7% | Faster on Josey; tag-read variance dominated by track-file complexity |
| `analysis_librosa_load` | 0.2203 | 1.9% | 0.3564 | 58.5% | **New ceiling.** Same absolute work; share rose because key detection no longer absorbs the variance |
| `analysis_detect_bpm` | 0.2416 | 2.0% | 0.2466 | 40.5% | Essentially identical absolute cost; share rose for the same reason |
| `analysis_detect_key` | 11.4012 | 96.0% | — | — | **Gone.** Stage no longer emitted |
| `analysis_db_update` | 0.0014 | 0.0% | 0.0014 | 0.2% | Unchanged |
| `analysis_track` (outer) | 11.8726 | 100% | 0.6096 | 100% | **−95%** |

The librosa_load max went from 1.49s (Martyn) to 6.78s (Josey). This is reproducible-in-kind across all three runs — the Lakuti baseline had a 6.24s outlier in the same stage. Cold-cache I/O on `/Volumes/collection/` external USB-C is the dominant variance source. Post-6d.1, this variance is no longer hidden behind key detection's 11s mean — it's the visible ceiling. On warmer storage, the post-6d.1 floor would drop further toward the BPM-plus-overhead theoretical minimum (~0.25s/track).

### XML export — Commit 2 verified

The reporter shows 4 `xml_export` inner-stage record types post-6d.1, vs 6 pre-6d.1. The two missing rows are `xml_export_load_crates` and `xml_export_load_sets`, both of which were removed from the exporter in Commit 2. The stage constants remain in `backend/services/perf.py` for historical JSONL parsing; they no longer emit because the exporter no longer reads crates or sets. The outer `xml_export` total wall-clock is coincidentally identical to 4 decimal places (28.1ms in both runs); the exporter writes the same kind of XML with the same kind of overhead, just without two trivial DB queries.

### Ingestion — unchanged, as expected

Phase 6d.1 did not touch ingestion. The per-file shape is consistent across both runs:

| Stage | Pre mean (s) | Post mean (s) |
|---|---:|---:|
| `ingestion_inspect` | 0.0290 | 0.0287 |
| `ingestion_hash` | 0.0402 | 0.0427 |
| `ingestion_convert_ffmpeg` | 0.2015 | 0.1920 |
| `ingestion_file` (outer) | 0.2732 | 0.2681 |

Modest differences attributable to corpus composition (Josey's files average slightly smaller than Martyn's based on the per-file ingestion mean). No meaningful change.

### AI tagging — cost-neutral, sample size too small for latency signal

| Metric | Pre (Martyn) | Post (Josey) | Change |
|---|---:|---:|---:|
| Batches | 5 (mixed 83-track corpus) | 2 (40-track) | scale only |
| Mean per-batch wall-clock | 22.63 s | 28.61 s | +26% but n=2 is noise |
| Input tokens per track | 179 | 159 | **−11%** |
| Output tokens per track | 98 | 102 | +4% |
| Cost per track | $0.00201 | $0.00200 | flat |

The prompt slimming from Commit 4 (removed key field from track summaries, removed key reference from the system prompt) achieved the predicted input-token reduction. Output tokens crept up slightly, washing out the cost benefit at the per-track level. The 26% per-batch wall-clock increase on n=2 is not a meaningful signal; Claude API latency varies more than this between any two same-day batches.

**Quality smoke check:** the AI-tagged genres on the 40 Josey tracks were eyeballed in the track table for obvious misclassification, particularly in the 120–126 BPM band where the removed "minor-key suggests deep/tech house" disambiguation hint would matter. No obvious regressions observed. Operator verdict: "looks fine at this stage." This is a real-world sanity check, not a formal evaluation against a labelled set.

## What this confirms

1. **The Phase 6d Decision Point was correctly identified.** Key detection was the dominant cost, and removing it produced the predicted order-of-magnitude per-track speedup.
2. **The Phase 6d.1 commits landed cleanly in the packaged binary.** Three independent signals corroborate: `analysis_detect_key` stage absent from emitted JSONL, `xml_export_load_crates` and `xml_export_load_sets` stages absent, AI tagging input tokens reduced.
3. **Cost-neutrality on AI tagging held.** Prompt slimming did not visibly degrade Claude's output quality (smoke check) and did not save per-track cost in dollars — Claude wrote marginally more reasoning to compensate for the missing key signal. Equal-cost-better-speed is the right framing.

## What this changes for the future

1. **The next bottleneck is I/O, not computation.** `analysis_librosa_load` is now 58.5% of analysis time. On internal SSD storage this share would drop sharply; on USB-C external the cold-cache decode is the ceiling. Any further analysis speedup would target I/O strategy (caching, prefetch, sequential reads) rather than algorithms. Whether to pursue this is a Phase 6e or future-phase decision; at 0.6s/track the absolute savings are small.

2. **BPM detection is now the largest *computational* cost.** At 40.5% of post-6d.1 analysis time, it is no longer rounding error. The Phase 6d brief's candidate (b) "concurrent analysis workers" would scale BPM linearly across cores and produce meaningful absolute savings on large libraries. The brief's candidate (c) "share the librosa decode" — formerly capped at ~2% — would now save ~20–30% if pursued, because the decode is no longer shared with key detection (it's used by BPM only). Neither is in scope right now.

3. **Per-track at scale.** A 100-track new-music batch would take ~60 seconds of analysis time post-6d.1, vs ~20 minutes pre-6d.1. A 500-track library catch-up would take ~5 minutes vs ~100 minutes. The realistic-DJ-workflow framing from the Phase 6d.1 brief ("a handful of new tracks at a time against a much larger Rekordbox-managed library") now describes a tool that completes analysis fast enough to be effectively instant in normal use.

## Caveats

- **N=40 not N=52.** The Josey Rebelle folder is 40 audio files, not 52. The Phase 6d.1 brief and the perf README's "Future runs" section inferred parity with Martyn from sequential numbering. The brief's inference was wrong; no code or measurement defect. Per-track numbers remain comparable; per-stage totals scale to N=40.
- **Cold-cache external USB-C variance.** Both runs were on `/Volumes/collection/` cold cache for the run-specific corpus. Librosa_load outliers are real and reproducible across all three baselines (Lakuti 6.24s max, Martyn 1.49s max, Josey 6.78s max). The 19.5× number is a *lower bound* on the speedup; a warm-cache or internal-SSD run would show higher.
- **n=2 AI tagging batches.** Per-batch latency variance at this sample size is dominated by Claude API and rate-limiter noise. The +26% per-batch wall-clock figure is not informative; the per-track cost figure is.
