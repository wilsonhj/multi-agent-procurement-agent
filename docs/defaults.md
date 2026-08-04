# Evidence corrections and residual defaults

**Most of this document has been superseded.** It was written before the
implementation spec landed, and `specs/001-procurement-agent/` now decides most of
what it proposed — in several cases identically, having been researched
independently. What is left here is the part that does not live anywhere else: a
record of claims that were **checked and found false**, so they do not come back.

| Was proposed here | Now decided in |
|---|---|
| Per-field conflict tolerance table | `clarifications.md` D-2 |
| Confidence as a precision target, not a fixed float | `clarifications.md` D-3 |
| Deterministic supplier/model identity, no fuzzy matching | `clarifications.md` D-4, plus `ComponentInstance.ordering_key()` |
| Power tolerance parsed per supplier | `clarifications.md` D-2 and the contract's *Declared bands*. The `declared_tolerance` key proposed here was **rejected**: the contract types `power_tolerance` and `bifaciality_tolerance` *as* `DeclaredBand`, so a band carries its own provenance and there is no second copy to sync |
| Propose/commit split for concurrent writers | `tasks.md` contract C8 |
| Async ports | `plan.md` Decision 10 — **decided sync**, see below |
| LangGraph orchestration, `max_concurrency` placement | `plan.md` Decision 1 — **no workflow framework**, so the nesting trap is moot. The underlying question was answered rather than dropped: `Settings.max_concurrent_parse`, `max_concurrent_llm` and `web_search_rate_limit_per_minute` |
| HNSW `m`/`ef_construction` tuning | `plan.md` Decision 3a — **no ANN index**, so moot |

Two of those reverse recommendations made here. Both reversals are accepted:

- **Async ports.** This document argued async was free now and breaking later.
  That overweighted coroutine fan-out a process-pool runner never needs: under
  Decision 1a's single-process driver, concurrency is per-process across
  `max_concurrent_parse`, parse and OCR are CPU-bound, embedding and reranking
  batch inside the payload, and Protocols are structural so an async variant
  stays additive. This bullet originally cited Decision 1's `SELECT … FOR UPDATE
  SKIP LOCKED` loop; A-45 retired the loop and the reversal is unaffected,
  because it rested on the work being CPU-bound and process-distributed rather
  than on the queue. Revisit only if Decision 10 is reversed.
- **ANN index.** Superseded by a measurement this document did not have —
  pgvector silently under-returning on a filtered top-k.

---

## Corrections worth keeping

Each of these was asserted somewhere, checked, and found wrong. They are recorded
because the wrong version is the one that circulates.

### Transformer loss tolerance is not `±7.5%`, and is not a conflict tolerance

Two distinct errors, and the second is subtler than the first.

**The figure.** `±7.5% / ±10%` is the **impedance** tolerance, not losses.
⚠️ Attributed to IEEE C57.12.00 clause 9.2 in an earlier draft; the repo's own
primary-verified source is **IEC 60076-1 Table 1 item 3a**, which is what
`clarifications.md` D-2 and `conflict_hitl/tolerance.py` cite. C57.12.00 is
paywalled and has never been read here, so no clause of it should be cited as
though it had been. The loss tolerance is **one-sided**: no-load `+10%`,
total `+6%`; IEC 60076-1 Table 1 gives total `+10%`, component `+15%`. There is
also **no C57.12.00-2020 edition** — 2015 and 2021; `C57.12.01-2020` is the
dry-type standard, which is where the bad suffix comes from. The source of the
error was a vendor content-marketing page; treat that lineage as poisoned.

**The category.** Those are **guarantee** tolerances, between a *specified* value
and a *tested* one. They are not a band between two declared datasheet figures.
Adopting them as the conflict tolerance would let two datasheets declaring 100 kW
and 109 kW no-load loss compare as non-conflicting — precisely the disagreement a
reviewer needs. The band applies only when one side is a factory test report;
declared-vs-declared compares at datasheet precision.

✅ **Now implemented.** `_compare_one_sided` shipped applying the allowance
symmetrically between two same-tier candidates, which absorbed exactly the
100-vs-109 kW case above. Corrected: where neither side is identifiable as the
measurement, the comparison falls back to printed precision.

Because the tolerance is one-sided, the loss conflict test should be one-sided
too: a value *below* a guarantee is never a nonconformity.

Confidence: **reasoned**. Corroborated across an OEM functional spec, utility
purchase specs and an ex-ABB SME article, but through search snippets only —
IEEE is paywalled and egress returned 403. Someone with Xplore access should read
C57.12.00-2021 clause 9 before these are settled.

### `jina-embeddings-v4` is not CC-BY-NC-4.0

Its `LICENSE` file is the **Qwen Research License Agreement**, inherited from its
Qwen2.5-VL-3B base; the HF repo carries no `license:` field at all. Non-commercial
still holds, so the exclusion stands — but a commercial licence is requested from
**Alibaba Cloud**, not Jina, derived models must display "Built with Qwen", and it
is governed by Chinese law. The licence *name* matters once it reaches procurement
paperwork. Confidence: **firm** — read from the `LICENSE` file.

Commercially usable alternatives, licences read from their model cards:
**BGE-M3** (MIT, 1024-dim, 8192 context, dense + sparse + ColBERT from one model)
and **bge-reranker-v2-m3** (Apache-2.0). **Qwen3-Embedding-8B** is Apache-2.0.

### Size a parse pool off Docling's mean, not its median

Median **0.79 s/page** on x86 CPU, but the **mean is 3.1 s/page** — the
distribution is heavily right-skewed (5th percentile 0.6 s, 95th 16.3 s; OCR pages
average ~13 s). Sizing off the median understates CPU need by roughly 4×. GPU
speedups vs x86 CPU: 8× OCR, 14× layout, 4.3× table structure. Measured on AWS
`g6.xlarge` over 89 PDFs / 4,008 pages, Docling **v2** technical report.
Confidence: **reasoned** — arXiv returned 403, read via snippets.

### LLM overconfidence is not a general law, and self-consistency is a weak signal

Calibration is **field-type dependent** rather than uniformly bad: the same study
reports numeric fields well-calibrated and free-text fields overconfident. That is
not a general reversal for structured extraction, and an earlier draft here
overstated it as one. On
DocILE (55-field invoices, 26% failure rate): logprob-mean 0.705 ROC AUC,
verbalized 0.692, self-consistency k=5 **0.744**, multi-signal fusion **0.928**.
So self-consistency buys ~+0.05 AUC at exactly 5× cost (five calls), while the
0.928 figure is a **trained heterogeneous model** combining OCR confidence,
cross-call disagreement, spatial layout and field type — not a deterministic
signal used alone. The mechanism still holds: extraction errors come from what the
model *cannot observe*, and a model confidently transcribing OCR noise has high
logprobs *and* high self-agreement. Every figure is ROC AUC — *discrimination*,
not calibration. Confidence: **reasoned** (arXiv, 403).

D-3 reaches the same destination by a different route.

### Flash-test uncertainty exceeds the entire declared power tolerance

Expanded uncertainty (k=2) is **±1.1% monofacial / ±1.4% bifacial** at Fraunhofer
ISE CalLab, within 2.5% for TÜV Rheinland's mobile lab, looser on production
lines. That is larger than `0~+5 W` (+0.77% on 650 W). So nameplate-vs-nameplate
and nameplate-vs-measured need different rules — the same distinction as the
transformer row above. Also: **IEC 60904-9 classifies solar simulators and
specifies no uncertainty**; the relevant standard is **IEC TR 60904-14:2020**.
Confidence: **reasoned** — lab figures from vendor pages, not scope certificates.

### `pgvector`'s `ef_construction >= 2*m` is enforced, not advisory

`src/hnswbuild.c:714` raises `ERROR: ef_construction must be greater than or equal
to 2 * m` and `CREATE INDEX` fails outright. At the default `ef_construction=64`
this bites above `m=32`. Retained only because it would bite anyone who reaches
for an ANN index later; Decision 3a means it does not apply today. Confidence:
**firm** — read from cloned source.

---

## Sourcing

Egress returned HTTP 403 for manufacturer domains, arxiv.org and IEEE hosts
throughout, so **no datasheet PDF or standard was opened verbatim**. Evidence is
search-indexed PDF text, `LICENSE` and model-card files read through an
authenticated API, and cloned source repositories — the last two stronger than
rendered pages. Claims are marked **firm** only where a primary artifact was read
directly.

- IEEE C57.12.00-2021 † — https://ieeexplore.ieee.org/document/9690124
- IEC 60076-1 Ed. 3.0 † — https://cdn.standards.iteh.ai/samples/15220/af5a58a20abc42fba16f84723a77111d/IEC-60076-1-2011.pdf
- IEC 60904-9:2020 † / IEC TR 60904-14:2020 † — https://webstore.iec.ch/en/publication/28973 · https://webstore.iec.ch/en/publication/67058
- Fraunhofer ISE CalLab † — https://www.ise.fraunhofer.de/en/press-media/press-releases/2020/Fraunhofer-ISEs-CalLab-PV-Modules-Improves-Measurement-Uncertainty-to-Record-Value.html
- Docling technical report † — https://arxiv.org/pdf/2501.17887
- Beyond Logprobs (DocILE) † — https://arxiv.org/pdf/2606.24420
- When LLMs Agree, Are They Right? † — https://arxiv.org/pdf/2607.08065
- jina-embeddings-v4 `LICENSE` — https://huggingface.co/jinaai/jina-embeddings-v4/blob/main/LICENSE
- BAAI/bge-m3 · BAAI/bge-reranker-v2-m3 · Qwen/Qwen3-Embedding-8B — https://huggingface.co/BAAI/bge-m3
- pgvector `hnswbuild.c` — https://github.com/pgvector/pgvector/blob/master/src/hnswbuild.c

† not opened directly; cited as the authority to consult.
