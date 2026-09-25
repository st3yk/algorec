# Implementation Plan: User-Steerable Short-Video Recommender ("Brain-rot ↔ Educational")

_Status: final after 5 adversarial review rounds (loop cap). Round-5 findings are applied below but were **not** re-reviewed — see the Review Status section at the end._

## Problem Statement

Build a proof-of-concept recommender for short-form video (TikTok/Reels/Shorts-style vertical feed) in which the **user explicitly controls the content mix** along two dimensions:
- **"Brain-rot"**: low-informational, high-stimulation, meme/trend content.
- **"Educational"**: content whose main value is that the viewer learns something.

Moving the control must visibly and reliably change the feed. The feed must also stay personally relevant: an educational feed about topics the user doesn't care about is a failure too. After the PoC, the design must extend from 2 dimensions to N (e.g. "calm", "local", "original vs. repost") without re-architecting.

**Scope**: this plan covers the **recommendation algorithm only**: item scoring, retrieval, ranking, steered page assembly, and their evaluation. The application backend and the client (UI, auth, sessions, rate limiting, storage of user profiles) are out of scope. The boundary between them is one RPC service, specified in Steps 21–22: the backend calls `GetNextBatch` to get the next batch of video IDs, and reports what the user actually watched with `ReportImpressions`.

Two further deliverables are at the end: a **programming-language recommendation** and a **required-background profile** for the engineer.

## Constraints & Success Criteria

- **Scale**: PoC with ~20k–100k items and ~1k–10k real or simulated users. MicroLens-100K has 100k users; a random 10k-user subsample is used for iteration speed, and full-set numbers are reported at the end. At this size, exact (brute-force) vector search and a per-request small ILP are both fast enough. (assumed)
- **Latency**: a `GetNextBatch` call (P = 10 video IDs) returns in under 300 ms at p95 on one node **at 20 QPS**. A control change takes effect **on the next `GetNextBatch` call**, not after a retrain. (assumed)
- **Data**: no existing platform. See Step 3 for the datasets and their known limitations. (assumed)
- **Team/timeline**: 1–2 engineers, ~14 weeks, with a cut list if behind. (assumed)
- **Build**: everything — the service, offline jobs, evaluation, and tests — builds with **Bazel**. This is a deliberate choice (see "Build System (Bazel)"): more setup than a PoC strictly needs, in exchange for cached, reproducible builds that anyone can run with one command.
- **Unit of "mix"**: throughout, the **share of dimension d** of a page is its **expected human-judged share**: `m_d = (1/P)·Σ_i q_d,i`.
  - `q_d,i` is item i's calibrated probability that a randomly chosen annotator rates it ≥ 3 on dimension d (Step 7).
  - Humans measure the same quantity directly: the fraction of (item, annotator) labels with a rubric score ≥ 3.
  - The **exclusive share** `x_d` counts mass that is d and *not* the pushed-up dimension: per item `e_d,i = q_d,i·Π_{k∈D⁺}(1 − q_k,i)`. The human equivalent is the fraction of (item, annotator) labels with d ≥ 3 and every pushed-up dimension < 3; each annotator labels both dimensions, so this is directly measurable.
  - **The slider's promise**: pushing d **up** raises its *total* share `m_d`. Pushing d **down** lowers its *exclusive* share `x_d` (edutainment is not suppressed). Both are used consistently in Steps 14–15 and in criteria 1–2.
  - The threshold τ_d ("strongly d") is used only for display ("why this?" labels) and for retrieval masks, never for the mix constraints.

**Success looks like:**
1. **Mechanical steerability** (a **system/regression test** of the assembler, not evidence of steerability):
   - Sweep 11 slider points, with 20 consecutive pages per point per test user. Each point starts from a **snapshot** of the user's state (seen set, pass-through stats), so points don't drain each other's supply.
   - Offline, every served item counts as an impression (it enters the seen set).
   - Every page without shortfall meets its bound within 0.01 (Steps 14–15).
   - The mean realized share per point (`m` for pushed-up, `x` for pushed-down) is monotone in s within ε = 0.03. Target: zero violations.
   - Pages containing an exploration slot are flagged and reported separately.
   - Shortfall pages (Step 18) are reported separately with their slack and reason, not silently included or excluded.
2. **Valid steerability** (human units — the **primary** criterion):
   - Human-labeled served pages at 5 slider points (Step 25).
   - **Monotone in human units, with 95% cluster-bootstrap CIs, within ε**:
     - human total edu share `m_edu` is non-decreasing in s;
     - human exclusive light share `x_light` is non-increasing in s;
     - the mirror-image holds for s < 0.
   - **Spread**: `m_edu(+1) − m_edu(−1) ≥ 0.3`, and `x_light(−1) − x_light(+1) ≥ 0.3`.
     - This is **provisional** and lower than a naive 0.4, because edutainment is allowed at both ends and annotator disagreement caps q (Step 8).
     - Step 26 checks by week 10 whether it is reachable, and the criterion is re-set from that evidence rather than silently missed.
     - Total light share is reported as a secondary result.
   - **Units check**: the predicted `m_d` / `x_d` match the human-measured quantities within 0.08 at every point. This confirms that the slider's promise is in human units.
3. **Relevance under steering**:
   - A **relevance-vs-s curve**: Recall@K / NDCG@K on *all* held-out positives at each of the 11 slider points. The drop is at most 15% at |s| = 0.5 (provisional) and is reported at |s| = 1.
     - This is a pessimistic bound: the logs were collected unsteered.
   - A **human relevance judgement**: the served pages in criterion 2 are also rated "fits this user's interests?" (0–2) against the user's last min(20, available) positives. Users are sampled at random from those with ≥ 5 positives; this heavy-ish-user bias is stated with the results. The mean drops by at most 0.3 at |s| = 0.5.
   - Within-dimension relevance (Step 24b) is secondary and reported with the number of qualifying users.
4. **Label quality relative to the human ceiling**:
   - On the gold *test* split, the mean of model-vs-**single-annotator** quadratic-weighted κ (averaged over annotators) is ≥ 0.9 × annotator-vs-annotator κ.
   - κ is reported on the stratified split and reweighted to catalog prevalence.
5. The `GetNextBatch` / `ReportImpressions` service implemented, and the offline evaluation (Steps 24–26) driven through the **same** entry point the backend calls. A small user study (Step 27) is run through whatever client the backend team provides.

## Options Considered

### A. Where does the user's control enter the system?

| Option | Summary | Pros | Cons | Verdict |
|---|---|---|---|---|
| A1. Filter only | Hard-filter items by label thresholds | Trivial, legible | Binary, brittle; empties the pool for niche users | Rejected |
| A2. Re-rank an engagement-only pool with a score bonus | Add `λ·score_d` to the final score | Cheap, standard multi-objective fusion | Too few wanted items in an engagement-only pool; a single λ trades off differently per request, so the mix is not guaranteed | Rejected |
| A3. Per-dimension retrieval quotas + **exact per-page constrained assembly (small ILP)** | Retrieval guarantees supply; the assembler picks the most relevant page that satisfies one-sided per-dimension expected-share bounds | Mix guaranteed by construction (or explicit shortfall); handles items in both dimensions and upper/lower bounds; extends to N dimensions | Needs a solver (a scipy dependency, ms per request) | **Chosen** |
| A3′. Greedy with a soft-share penalty (Steck-style calibration) | Greedy maximization of relevance minus mix deviation | Simple | Settles below target, and its trade-off depends on how relevance is scaled per request, so the mix can't be guaranteed | Rejected (was the round-1 choice) |
| A4. End-to-end control-conditioned ranking | The model learns the trade-off with the control as input | Direction of recent industrial research | Needs lots of data logged under varied control settings; the model can learn to ignore the input | Rejected for PoC; revisit once Step 19–20 logs exist |

### B. How do items get dimension scores?

| Option | Summary | Verdict |
|---|---|---|
| B1. Creator tags / hashtags | Gamed, sparse | Used only as a feature |
| B2. Behavior-derived | Circular; new items have no score | Rejected |
| B3. Multimodal LLM labels every item | High quality, costly per item | Used as **teacher** only |
| B4. Teacher–student distillation onto frozen content features | Cheap, scores items at upload, new dimension = new head | **Chosen** |

### C. One bipolar axis vs. independent dimensions

Content can be both (edutainment) or neither (a cooking vlog, a sports clip). So:
- Items get **independent calibrated scores per dimension**.
- Targets are per dimension and **don't sum to 1**.
- "Neither" content fills whatever the bounds leave.

A client can still expose one "Fun ↔ Learn" slider; Steps 13–15 and the RPC's `control` field define how it maps to the per-dimension targets.

## Chosen Approach

A multi-stage pipeline (retrieve → rank → assemble). The user's control acts at two points:
1. **Retrieval quotas**, which make sure the candidate pool contains enough content of the wanted kind.
2. **Per-page one-sided bounds** on each dimension's *expected human-judged share*, set relative to this request's unsteered page: at least this much more educational, or at most this much pure light content. The assembler meets them exactly by solving a small integer program that maximizes relevance subject to the bounds.

A steered page therefore never moves against the slider relative to what the user would have seen at neutral.

Relevance and content kind are modeled separately. The control is therefore a transparent, deterministic lever with an explicit shortfall signal when supply runs out. Dimension scores come from content, not behavior, so a new item can be steered as soon as it is uploaded.

## Step-by-Step Implementation Plan

### Phase 0 — Definitions and data (weeks 1–3)

1. **Labeling rubric per dimension.**
   - "Brain-rot" is defined operationally: low informational density, rapid cuts or high stimulation, a meme/trend template, no transferable takeaway. In code it is named neutrally: `dim.light_entertainment`.
   - `dim.educational` means a viewer could state one fact or skill they learned.
   - Include borderline examples and **adversarial negatives** (e.g. "LEARN THIS" overlays on non-educational content).
2. **Lightweight extraction pass** (needed to sample the gold set): title/ASR text embeddings and CLIP/SigLIP cover embeddings for the whole catalog. This is reused by Step 5.
3. **Gold set.**
   - **Composition**: ~3,000 items, 0–4 scale per dimension, ≥ 2 annotators. It has two parts:
     - (a) a **uniform random** sample of ~600 items, used for prevalence and for calibration against the real catalog;
     - (b) a **stratified** sample that oversamples likely-educational and borderline items, chosen by zero-shot similarity to the rubric. Each item records its stratum's **sampling rate**.
   - **Agreement**: measure human-vs-human κ and Krippendorff's α. If α < 0.6, revise the rubric before continuing.
   - **Split once**: 20% *dev* (teacher prompt iteration), 30% *calibration*, 50% *test*, stratified by sampling stratum.
4. **Datasets, pinned, with limitations stated.**
   - **Primary: MicroLens-100K** (~19.7k items with raw video, audio, cover and title, plus user interactions).
     - Its interactions are **comments**: there is no watch time, like, or impression/negative log.
     - Relevance therefore trains on "commented = positive" with sampled negatives. This is a sparse, exposure-biased proxy.
   - **Language**: check the language mix of the content. Use multilingual models (Whisper large-v3, bge-m3 text embeddings, a multilingual SigLIP 2 variant), and use annotators who can read the content or have reliable translations.
   - **Secondary: KuaiRec** (small fully-observed matrix, 1,411 × 3,327, with watch ratio). It has no raw video, so its dimension labels come from caption+category-only heads (validated on a small labeled caption sample) or are synthetic. Both are stated as weaker proxies. KuaiRec is used only for simulation and unbiased relevance evaluation (Step 26).
   - All interactions are split **by time**.

### Phase 1 — Item dimension scoring (weeks 3–6)

5. **Full feature extraction per item** (offline batch; the same code runs at upload):
   - ASR transcript (Whisper) and OCR on keyframes.
   - 8 keyframe SigLIP embeddings.
   - A text embedding of title + transcript + OCR.
   - **Pacing features**: shot-cut rate (PySceneDetect), variance of audio energy, speech rate.
   - **Creator features**: the creator's leave-one-out mean teacher score per dimension, with empirical-Bayes shrinkage by item count. This damps single-item gaming.
6. **Teacher labels.**
   - Iterate the MLLM rubric prompt on *dev* only.
   - Accept the teacher when its κ on *calibration* is ≥ 0.9 × human κ.
   - Run a 500-item pilot to measure cost and throughput, then label ~15k items. Hold out **~2k random catalog items** from student training as the "teacher holdout" used in evaluation.
7. **Student heads**: one small MLP per dimension on the Step 5 features (creator features included *as inputs*), trained on teacher labels and excluding gold and holdout items.
   - **Ordinal output**: cumulative logits over 0–4. This gives an expected score (for κ) and P(score ≥ 3).
   - **Calibration**: fit isotonic regression of P(≥3) on the *calibration* split.
     - Each (item, annotator) label is a separate sample, so `q_d,i` = P(a random annotator rates ≥3).
     - Samples carry **inverse-sampling-rate weights**, so probabilities reflect the real catalog. Calibration is applied to the final head output, and that calibrated score is the one used downstream.
   - **Reporting**: on *test*, report κ and binary F1 at "≥3", both stratified and reweighted.
8. **Dimension registry**: a config table
   `{dim_id, display_name, head_artifact, calibrator, τ_d, T_min_d, T_max_d, priority_d}`.
   - τ_d is the "strongly d" threshold on `q_d` (e.g. 0.6), used for retrieval masks and display labels only.
   - `priority_d ≥ 1` weights slack across dimensions (Step 17).
   - `T_max_d` / `T_min_d` are **product end points**, in expected-share units, for how far the slider can push. They are set in week 5 from measured limits, not guessed:
     - `T_max_d` is at most the median `q_d` of gold items that **all** annotators rated ≥ 3. Annotator disagreement caps q, so clear items may top out near 0.8.
     - `T_min_d` is at least the mean `e_d` of the lowest-`e_d` decile of catalog items. Calibrated q never reaches 0, so this is the q noise floor.
     - Starting guesses: 0.6 / 0.1. They are *not* derived from the natural spread of users' mixes, since that would cap "max educational" at what an already-educational user gets unsteered.
     - Whether a given user can reach them depends on supply in that user's per-dimension source above the relevance floor. When they can't, the result is reported as shortfall (Step 18) rather than hidden by a lower ceiling.
     - Step 26 measures the distribution of achievable share per user, so the end points can be tuned with evidence.
   - Everything downstream iterates over the registry. Adding a dimension means adding a rubric, gold labels, a teacher prompt, a head, and a registry row.

### Phase 2 — Relevance (weeks 5–8)

9. **Retrieval.**
   - Start with baselines: item-kNN / co-engagement and popularity.
   - Then a two-tower model:
     - User tower: recent positives.
     - Item tower: content embedding + ID embedding.
     - Training: in-batch negatives with logQ popularity correction (Yi et al. 2019).
   - At PoC scale, retrieval is an **exact dot product** over the full item matrix (a few ms). Move to FAISS HNSW with `IDSelector` filtered search only past ~1M items.
10. **Sources = one item matrix + per-request boolean masks.**
    - Every source excludes the user's **seen set**, which the recommender maintains from `ReportImpressions` (Step 22), plus any `exclude_video_ids` in the request. A per-user set in memory is enough for the PoC; switch to a Bloom filter at scale.
    - **General source**: the top `K_gen = 200` by user-item score.
    - **Low-d source** (for pushed-down dimensions): among the top-1,000 items by user score, the K with the **lowest exclusive mass `e_d`**. It relieves upper-bound shortfalls (Step 18).
    - **Per-dimension source d**: the top-K_d among items with `q_d ≥ τ_d`.
      - `K_d = clip(ceil(need_d / pass_d · 1.5), 50, 400)`.
      - For any s ≠ 0, `need_d` uses the |s| = 1 target, so the **pool doesn't depend on the slider magnitude** (this is what makes Step 15's argument hold). At neutral, and for dimensions not being pushed up, K_d falls back to 50.
      - `pass_d` is the fraction of this source's items that passed the relevance floor and safety filter on the user's previous request (default 0.3).
      - K_d therefore adapts to supply, not just to the target.
    - **Fresh/popular source**: a small one, for cold users and new items.
11. **Cold-start users.**
    - The user embedding starts from the mean content embedding of the topics passed in the request's `cold_start.topic_ids`, or of the first 3–5 watches.
    - Until the user has ≥ 5 positives, it is blended with the population mean.
12. **Ranker.**
    - A LightGBM model that outputs a **calibrated probability** of the dataset's positive signal (comment on MicroLens; watch ratio above the median on KuaiRec).
    - Features: user features, item features (including dimension scores), cross features, and the two-tower score.
    - Its output `p_i` is comparable across requests, so no per-request normalization is needed.
    - The **control setting is not a feature** in the PoC: it has no variance in the bootstrap data, and relevance must not depend on steering.

### Phase 3 — Control and page assembly (weeks 7–10)

13. **Neutral = this request's unsteered page.**
    - On every request, build the **unsteered page** `U0`: the top-P by `p_i` over the **whole filtered pool**, with the creator rule. This is the unconstrained optimum, so no steered page can have higher relevance than neutral.
    - Its expected share `u_d = (1/P)·Σ_{i∈U0} q_d,i` is the reference point for this request.
    - At s = 0, `U0` *is* the served page: there are no dimension constraints. The pool at s = 0 is built with the same sources and K as at s ≠ 0, so neutral and steered pages are compared on the same pool.
    - There is **no stored baseline**: no EMA and no frozen state. The reference therefore can't drift or lag, and a cold user who moves the slider on request 1 is handled the same way as everyone else.
14. **Control → one-sided targets (monotone relative to neutral, per page).**
    - The slider is `s ∈ [−1, +1]` (−1 = more fun, 0 = neutral, +1 = more learning). New users start at 0.
    - The dimension being pushed up is D⁺ (edu when s > 0, light when s < 0); the other is D⁻.
    - **Pushed up — lower bound only.** For d ∈ D⁺:
      - `t_d = u_d + |s|·(max(T_max_d, u_d) − u_d)`
      - Constraint: `Σ x_i q_d,i ≥ t_d·P`.
      - Because `t_d ≥ u_d`, a steered page never has *less* of d than the unsteered page would.
    - **Pushed down — upper bound only, on "exclusive" mass.** For d ∈ D⁻:
      - The bound counts `e_d,i = q_d,i · Π_{k∈D⁺}(1 − q_k,i)`, i.e. mass that is d and *not* the pushed-up dimension.
      - `t_d = ū_d − |s|·(ū_d − min(T_min_d, ū_d))`, where `ū_d` is the exclusive share of `U0`.
      - Constraint: `Σ x_i e_d,i ≤ t_d·P`.
      - **Product decision**: "more learning" suppresses *pure* light content, not edutainment. An engaging educational item that is also fun is not penalized, and vice versa.
    - **N dimensions**: one slider `s_d` per dimension, each with the same formulas. Dimensions at 0 are unconstrained. The "exclusive" mass for pushed-down dimensions is taken with respect to all pushed-up dimensions.
    - **Single-slider mapping (PoC)**: `s_edu = s`, `s_light = −s`.
    - **Conflicts**: there is no static feasibility check. Conflicts (e.g. several pushed-up dimensions, or pushed-up items carrying pushed-down exclusive mass) show up as slack with reason `conflicting_targets`, returned in the response's `shortfalls`.
15. **Why this is monotone (and where it isn't guaranteed).**
    - **Guaranteed**: the realized share is always ≥ `t_d` (pushed up, `m`) or ≤ `t_d` (pushed down, `x`), except where slack is reported. So a steered page never moves *against* the slider relative to that request's neutral page.
    - **Monotone in |s| for a fixed pool**: larger |s| gives a tighter one-sided bound, so the feasible sets are nested, and if the optimum at s1 already satisfies the bound at s2 it is also optimal at s2.
      - Step 10 keeps the pool independent of |s|, so the argument holds except when Step 18's widening fires. Criterion 1 tests this empirically.
    - The share is continuous (a sum of probabilities), so no integer rounding or carry-over accumulator is needed.
16. **Candidate pool, filters, relevance floor.**
    - Pool = the union of all sources (~400–600 items). **Near-duplicates are collapsed** first (cosine > 0.95 on the mean SigLIP keyframe embedding; the item with the best `p` is kept).
    - Apply **safety/integrity filtering** at **every** slider setting (moderation labels, removed or age-restricted content).
    - Apply a **relevance floor** as a hard filter: keep `p_i ≥ max(p_abs, 0.5 · p_(P))`.
      - `p_(P)` is the P-th best `p_i` in the general source (a pre-filter estimate of U0's relevance).
      - `p_abs` is the user's median `p` over a random 1,000-item catalog sample, **cached per user per day**.
17. **Assembler = small ILP, solved lexicographically** (scipy `milp` / HiGHS, ~500 binary variables, a few ms per stage).
    - **Variables and constraints (all stages)**:
      - `Σ x_i + σ_card = P`.
      - The Step 14 bounds, each with a continuous slack `σ_d ≥ 0`.
      - Per creator c: `Σ_{i∈c} x_i ≤ 1 + σ_c`.
      - If this page has an exploration slot (Step 19), that item is fixed at `x = 1`.
      - x = 0 is always a solution (all slack), so the model is **always feasible**.
    - **Stage 0 — minimize shortfall**: minimize `Σ_d priority_d·σ_d + Σ_c σ_c + σ_card`, giving σ*.
      - Slack below 1e-6 counts as zero.
      - The slacks *are* the shortfall report. Because this is a separate stage, no relevance weight can make the solver prefer a small slack over a feasible page.
    - **Stage 1 — relevance**: maximize `Σ x_i p_i` with every slack ≤ its σ* + 1e-6. Call the resulting relevance R₁.
    - **Stage 2 — clarity tie-break**: maximize `Σ_i x_i Σ_{d∈D⁺} q_d,i·(q_d,i − 0.5)`, i.e. prefer items that are *clearly* d over borderline ones without rewarding overshoot, subject to:
      - all previous constraints;
      - `Σ x_i p_i ≥ (1 − δ)·R₁`, with δ = 0.02.
      - D⁻ is not in the objective, so edutainment is not penalized.
    - **Solver limits**: if a stage hits its time limit or the default MIP gap, the next stage's constraints use the **incumbent's** values plus the tolerance. That is always consistent.
    - **Order within the page**: *steered items* are those not in `U0`. Place them at evenly spaced positions (e.g. slots 2, 5, 8 for 3 items) and fill the rest by `p_i` descending.
    - **Fallback** if the solver errors or exceeds 50 ms, a swap-greedy:
      1. Start from `U0`.
      2. Repeatedly swap the lowest-`p` page item for the candidate that most reduces the total bound violation (respecting the creator rule), until the bounds hold or no swap helps.
      3. Report any remaining violation as shortfall, with `slot type = fallback`.
18. **Shortfall → widen supply first, then report, never silently.** When stage 1 needs non-zero slack, widen supply and re-solve once:
    - Lower-bound slack on d: grow that dimension source's `K_d` (up to 1,000), and relax the relative part of the relevance floor for its items to `0.25·p_(P)`. `p_abs` still applies, so items must still beat a random item.
    - Upper-bound slack on d: grow the low-d source.
    - Cardinality or creator slack: grow `K_gen`.

    Remaining slack is returned in the response's `shortfalls` as `{dim, amount, reason}`, so the backend can tell the user.
    - The reason is attributed by counting the qualifying mass dropped at each filter stage: `pool_exhausted` (seen set), `below_relevance` (floor), `low_supply` (little such content in the catalog/index at all), `creator_diversity`, `conflicting_targets`.
### Phase 4 — Exploration, logging, and the service interface (weeks 9–11)

19. **Exploration slice** (mainly infrastructure for post-PoC online learning; in an offline PoC only the user study generates such logs): in ~5% of pages, one slot is sampled from the **general source ∪ a uniform catalog sample** (independent of the slider), and its propensity is logged. The sampled item is fixed inside the ILP (Step 17), so the bounds still hold for the rest of the page. IPS-weighted relevance training uses **only these slots**. Assembled slots are down-weighted (e.g. 0.3) when retraining, so that items the mix forced into the feed aren't learned as "user likes X". No IPS claim is made for deterministic slots.
20. **Logging**: every returned item records `(request_id, batch_id, control, t, u, bounds, slacks, source, position, p_i, dimension scores, slot type ∈ {assembled, exploration, fallback}, propensity if exploration, shortfall)`. `ReportImpressions` later joins outcomes to it by `batch_id`.
21. **RPC: `GetNextBatch`** — the one call the backend makes to get the next batch of video IDs.
    - The recommender is a standalone gRPC service; the protobuf is below.
    - **Control is a per-request input**, not stored state. A slider change needs no separate API: the backend discards any prefetched batch and calls `GetNextBatch` with the new `control`.

    ```proto
    syntax = "proto3";
    package steerrec.v1;

    service Recommender {
      // Next batch of video IDs for this user under the given control setting.
      rpc GetNextBatch(GetNextBatchRequest) returns (GetNextBatchResponse);
      // What the user actually watched; feeds the seen set, logging, and retraining.
      rpc ReportImpressions(ReportImpressionsRequest) returns (ReportImpressionsResponse);
    }

    message GetNextBatchRequest {
      string user_id = 1;
      string request_id = 2;                  // idempotency key: a retry returns the same batch
      uint32 batch_size = 3;                  // P; default 10, max 50
      map<string, float> control = 4;         // dim_id -> s_d in [-1, 1]; a missing dim means 0 (neutral)
      repeated string exclude_video_ids = 5;  // served but not yet reported (e.g. still on the device)
      ColdStartHints cold_start = 6;          // optional, only used while the user has < 5 positives
    }

    message ColdStartHints {
      repeated string topic_ids = 1;          // e.g. topics picked at onboarding
    }

    message GetNextBatchResponse {
      string batch_id = 1;                    // echo this in ReportImpressions
      repeated RecommendedVideo videos = 2;   // in display order; may be shorter than batch_size (see shortfalls)
      repeated Shortfall shortfalls = 3;      // empty when every bound was met
      string registry_version = 4;            // dimension registry / model version used
    }

    message RecommendedVideo {
      string video_id = 1;
      uint32 position = 2;
      SlotType slot_type = 3;
      map<string, float> dimension_scores = 4; // calibrated q_d, for "why this?" display
      repeated string strong_dims = 5;         // dims with q_d >= tau_d
    }

    enum SlotType {
      SLOT_TYPE_UNSPECIFIED = 0;
      ASSEMBLED = 1;
      EXPLORATION = 2;
      FALLBACK = 3;
    }

    message Shortfall {
      string dim_id = 1;
      float amount = 2;                       // missing expected-share mass, in items
      Reason reason = 3;
      enum Reason {
        REASON_UNSPECIFIED = 0;
        LOW_SUPPLY = 1;
        POOL_EXHAUSTED = 2;
        BELOW_RELEVANCE = 3;
        CREATOR_DIVERSITY = 4;
        CONFLICTING_TARGETS = 5;
      }
    }
    ```

    - **Control mapping**: for the PoC single slider the backend sends `{"educational": s, "light_entertainment": -s}`. With N dimensions it sends one entry per slider; the keys are `dim_id`s from the registry (Step 8).
    - **Validation**:
      - `s_d` values outside [−1, 1] are clamped.
      - An unknown `dim_id` returns `INVALID_ARGUMENT`.
      - An unknown `user_id` is served as a cold user, not rejected.
    - **Deadline and fallback**: the server keeps an internal budget below the caller's deadline. If the solver can't finish in time, it returns the Step 17 fallback page (`slot_type = FALLBACK`), not an error.
    - **Idempotency**: responses are cached briefly by `(user_id, request_id)`, so retries don't consume new videos or double-log.
    - **Concurrency**: the service runs several worker processes, because the ranker and solver hold Python's GIL. Load-test at 20 QPS.
    - **Offline evaluation** calls the same handler in-process, so Steps 24–26 test exactly what the backend will call.
22. **RPC: `ReportImpressions`** — the companion call. Without it, the recommender can't know what was actually watched.

    ```proto
    message ReportImpressionsRequest {
      string user_id = 1;
      repeated Impression impressions = 2;
    }

    message Impression {
      string batch_id = 1;
      string video_id = 2;
      int64 viewed_at_unix_ms = 3;
      float watch_seconds = 4;
      bool commented = 5;
      bool liked = 6;
      repeated DimensionFeedback feedback = 7; // optional "not educational / not fun to me"
    }

    message DimensionFeedback {
      string dim_id = 1;
      bool disagrees = 2;
    }

    message ReportImpressionsResponse {}
    ```

    - A video enters the seen set only when reported with `watch_seconds ≥ 1`. Served-but-unwatched videos therefore don't drain supply; in-flight ones are covered by `exclude_video_ids`.
    - Outcomes are the positives for retraining (Steps 9, 12) and are joined to the Step 20 log by `batch_id`.
    - `feedback` is stored as extra label data for future per-user calibration.
    - The call is idempotent per `(batch_id, video_id)`.
23. **Item ingestion**: a new video is scored by the Step 5–7 pipeline as an async batch job and becomes retrievable once its dimension scores exist. Until then it is never returned.

### Phase 5 — Evaluation (weeks 10–14)

24. **Offline** (MicroLens time-split test):
    - (a) **Relevance-vs-s curve** (criterion 3) at 11 slider points, from state snapshots.
    - (b) **Within-dimension relevance at the extremes**: do the user's held-out positives in dimension d rank highly when steering toward d?
      - Report the number of qualifying users (those with ≥ 2 held-out positives in d) and **cluster-bootstrap-by-user** CIs. MicroLens has only ~7 interactions per user, so **estimate the qualifying count in week 1**.
      - If fewer than ~200 users qualify, treat this as indicative only.
    - (c) **Mechanical steerability** (criterion 1, system test): 11 points × 20 pages, each point from a state snapshot, measured against targets, with shortfall users and slack amounts broken out by reason.
    - (d) **Coverage**: catalog coverage, creator Gini, and repeat rate (it should be 0 because of the seen-set filter).
    - (e) **Pool exhaustion**: over multi-page sessions, the page number at which each dimension first reports shortfall.
25. **Valid steerability** (criterion 2):
    - Setup: 5 slider points × 40 served pages from 40 test users, labeled by humans with the rubric plus the "fits this user's interests?" judgement (~2,000 item labels; fewer after deduplication).
    - **20% are double-labeled**, to estimate the label noise in the primary criterion.
    - CIs use a cluster bootstrap by user.
    - Secondary cross-check: served items that happen to fall in the teacher holdout are compared against their teacher labels.
26. **Simulation** (KuaiRec, caption-based or synthetic labels, stated as such):
    - Unbiased relevance at every slider setting.
    - The **consumed** mix (watch-ratio-weighted).
    - Multi-round retraining loops, measuring how far user embeddings (and so `U0`) drift after long steering. Some drift is expected ("taste changes as you watch"); it is reported, not constrained.
    - **Achievable spread**: the per-user distribution of the maximum reachable expected share at s = ±1 (with no slack). This decides by week 10 whether criterion 2's ≥ 0.4 spread and the `T_max`/`T_min` end points are realistic.
27. **User study** (10–30 people): perceived control, satisfaction, whether the effect "feels right", and label validity from the user's view.

## Budget and cut list

- **Week 1 engineering overhead**: ~2 days for the Bazel setup (toolchain, both PyPI hubs, proto/gRPC rules, `.bazelrc`, `BUILDING.md`).
- **Estimate in week 1, with current provider pricing:**
  - Annotation: ~3,000 gold items × 2 annotators × 2 dimensions, **plus ~2,000 served-item labels** for criterion 2.
  - MLLM teacher: ~15k items (the pilot gives the per-item cost).
  - GPU time for Whisper, SigLIP and PySceneDetect over ~20k videos. MicroLens videos average about 2.7 minutes, longer than typical short-form, so budget ≈ 1–2 GPU-days. The same length raises MLLM teacher cost (sample frames and truncate transcripts).
- **Cut first, in order:**
  1. The two-tower model (keep item-kNN plus content-embedding retrieval).
  2. The multi-round retraining loops in the KuaiRec simulation. **Keep** its steered-relevance and achievable-spread parts, because criteria 2 and 3 depend on them.
  3. The user study, reduced to 5 hallway tests.
- **Never cut:** the gold set with its splits and weights, calibration, the human-measured steerability evaluation, the seen-set filter, exploration logging.
- **If the Bazel GPU hub fights back** (CUDA wheel resolution): run `//jobs:extract_features` from the notebook venv as a one-off, and keep everything else in Bazel. Features are cached artifacts, so this doesn't affect reproducibility of the rest.

## Language Recommendation

**Python** for the whole PoC.
- Every critical library is Python-first:
  - Training: PyTorch, LightGBM.
  - Content extraction: Whisper, SigLIP, PySceneDetect, MLLM SDKs.
  - Vector math: NumPy, FAISS.
  - The ILP: `scipy.optimize.milp` (HiGHS).
  - Evaluation, and serving the RPC (`grpcio`).
- The hot path fits the latency budget: an exact dot product over ~100k items, GBDT scoring of ~500 candidates, and an ILP with ~500 binary variables.

After the PoC, if the online path becomes the bottleneck, move only that path to **Go** (simple concurrency, easy ops) or **Rust/C++** (if per-request CPU is the limit):
- Moves: the `GetNextBatch` handler — retrieval fan-out, feature fetch, assembly. The protobuf contract stays the same, so the backend doesn't notice. OR-Tools CP-SAT and HiGHS both have native bindings.
- Stays: models are exported (ONNX / LightGBM native), and training stays in Python.

Starting in a systems language would slow the iteration that the PoC exists for.

## Build System (Bazel)

**Decision**: build and test everything with Bazel from day one.

- **Why, despite being heavy for a PoC**:
  - One documented way to build, test and run every component.
  - Hermetic Python toolchain and locked dependencies, so "works on my machine" problems don't happen.
  - Build and test results are cached, so incremental runs are fast.
  - A later move of the `GetNextBatch` handler to Go or Rust (see "Language Recommendation") stays in the same build graph and reuses the same `.proto`.
- **Cost**: about 2 days of setup in week 1. There is ongoing friction with large ML wheels (PyTorch/CUDA) and with notebooks; the mitigations are below.

### Setup

- **Version pinning**: pin Bazel with a `.bazelversion` file (Bazel 8.x) and run it through **Bazelisk**, so everyone gets the same version.
- **Dependencies**: use **Bzlmod** only (`MODULE.bazel`, no `WORKSPACE`). Commit `MODULE.bazel.lock`.
- **Modules from the Bazel Central Registry**, each pinned to a version:
  - `rules_python`: a hermetic Python 3.12 toolchain, plus `pip.parse` for PyPI dependencies.
  - `protobuf`: `proto_library` and `py_proto_library`.
  - `grpc`: `py_grpc_library` for the service stubs.
- **Two PyPI "hubs"**, each with its own lock file generated by `compile_pip_requirements`:
  - `@pypi`, CPU-only: the service, ranker/head training, ILP, evaluation, tests. This keeps the service build small and fast.
  - `@pypi_gpu`: the CUDA builds of PyTorch, Whisper and SigLIP, used only by the feature-extraction and embedding jobs. The CUDA wheels are large and platform-specific, and keeping them out of the default hub keeps `bazel test //...` fast.
- **`.bazelrc`**:
  - `build --disk_cache=~/.cache/bazel-disk` gives a local cache that survives `bazel clean`.
  - `test --test_output=errors`.
  - GPU-only targets (those depending on `@pypi_gpu`) are tagged `manual`. `bazel build //...` and `bazel test //...` skip them, so a laptop without CUDA can build and test everything else. They build or run only when named explicitly.
  - Add a shared remote cache later if the team grows.
- **Kept outside Bazel**: datasets, raw videos and trained model artifacts are too large. Targets receive them through flags (`--data_dir`, `--artifact_dir`). Artifacts are versioned by `registry_version` (Step 8), which the RPC also returns.
- **Notebooks** live outside the build, in a virtualenv installed from the **same** lock file (`uv pip sync requirements_lock.txt`). Exploration code therefore runs against the same dependency versions. The same venv serves the IDE.

### Target layout

| Package | Targets | Contents |
|---|---|---|
| `//proto` | `recommender_proto`, `recommender_py_pb2`, `recommender_py_grpc` | The Step 21–22 contract |
| `//steerrec/registry` | `py_library` | Dimension registry (Step 8) |
| `//steerrec/scoring` | `py_library` + `py_test` | Features, teacher prompt, student heads, calibration (Steps 5–7) |
| `//steerrec/retrieval` | `py_library` + `py_test` | Sources, masks, seen set (Steps 9–11) |
| `//steerrec/ranking` | `py_library` + `py_test` | LightGBM ranker (Step 12) |
| `//steerrec/assembly` | `py_library` + `py_test` | Targets, ILP stages, fallback, shortfall (Steps 13–18) |
| `//steerrec/service` | `py_binary` `server` + `py_test` | The gRPC handlers (Steps 19–22) |
| `//jobs` | `py_binary`s: `extract_features` (GPU, tagged `manual`), `label_teacher`, `train_heads`, `train_ranker`, `score_new_items` | Offline pipeline (Steps 2, 5–7, 12, 23) |
| `//eval` | `py_binary`s: `offline`, `simulate`, `sweep` | Evaluation (Steps 24–26), calling the service handler in-process |

**Fast tests that run on every build**:
- `//steerrec/assembly` property tests on synthetic pools:
  - monotonicity in |s|;
  - bound met or slack reported;
  - the ILP is always feasible;
  - the fallback respects the creator rule.
- `//steerrec/service` contract tests that go through the generated stubs.

These guard the control math (Steps 14–18), the part of the plan with the least review.

### How to build and run (for everyone on the team)

```sh
# Once: install Bazelisk (it reads .bazelversion and fetches the right Bazel).

bazel build //...                      # build everything except GPU-only targets
bazel test //...                       # all unit, property and contract tests (cached)

bazel run //steerrec/service:server -- --port=50051 --artifact_dir=/path/to/artifacts

bazel run //jobs:extract_features -- --data_dir=/path/to/microlens --out=/path/to/features
bazel run //jobs:train_heads   -- --features=/path/to/features --gold=/path/to/gold --artifact_dir=/path/to/artifacts
bazel run //eval:offline       -- --data_dir=/path/to/microlens --artifact_dir=/path/to/artifacts

bazel run //:requirements.update       # after editing requirements.in: re-lock the CPU hub
bazel run //:requirements_gpu.update   # same for the GPU hub
```

A `BUILDING.md` at the repo root repeats this block. Adding a dependency is: edit `requirements.in`, re-lock, then reference it as `requirement("name")` in the target's `deps`.

- **Later, post-PoC**: `rules_oci` can package `//steerrec/service:server` as a container image from the same graph.

## Required Engineer Background

Must-have:
- **Python + ML engineering**: PyTorch basics, training/eval loops, data pipelines (pandas/Polars), vectorized code.
- **Recommender-system fundamentals**:
  - Retrieve → rank → re-rank architecture.
  - Implicit feedback and negative sampling.
  - Two-tower models and vector search.
  - Offline metrics and time-based splits.
  - **Exposure/popularity bias and feedback loops**, and what IPS can and cannot correct.
- **Applied statistics and evaluation**:
  - Calibration, including under non-uniform sampling.
  - Inter-annotator agreement (κ, α).
  - Holding out data properly (the dev/calibration/test discipline).
  - Bootstrap confidence intervals.
  - A/B-test basics, and why offline ≠ online.
- **Basic optimization**: formulating a small integer/linear program and knowing when greedy is not enough.
- **Service basics**: defining and serving an RPC (gRPC/protobuf), idempotency, deadlines, logging schemas.

Strongly helpful:
- **Data-labeling operations**: writing annotation guidelines, annotation tooling (e.g. Label Studio), managing annotators.
- **Multimodal ML and GPU batch processing**: CLIP/SigLIP, ASR, running jobs over tens of thousands of videos.
- **Bazel basics**: Bzlmod, `rules_python` (hermetic toolchain, `pip.parse`, lock files), `proto_library` / `py_grpc_library`, caching. One person should own the build setup in week 1; everyone else only needs the "How to build and run" commands.
- **LLM-as-labeler practice**: prompting, validating against gold data, budgeting.
- **Multi-objective / constrained re-ranking**: MMR, calibrated recommendations, quota-constrained slates.
- **HCI/UX research literacy**: controllable-recommender interfaces.
- **Trust and safety basics**: integrity filters and defaults, including for minors.

Nice-to-have (post-PoC): off-policy evaluation, streaming feature pipelines (Kafka/Flink), Go or Rust for serving.

Suggested reading:
1. Covington et al., "Deep Neural Networks for YouTube Recommendations" (RecSys 2016).
2. Yi et al., "Sampling-Bias-Corrected Neural Modeling for Large Corpus Item Recommendations" (RecSys 2019).
3. Carbonell & Goldstein, "The Use of MMR, Diversity-Based Reranking…" (SIGIR 1998).
4. Steck, "Calibrated Recommendations" (RecSys 2018).
5. Tan et al., "User-Controllable Recommendation via Counterfactual Retrospective and Prospective Explanations" (ECAI 2023; arXiv 2308.00894).
6. "Rethinking User Empowerment in AI Recommender System: Innovating Transparent and Controllable Interfaces" (arXiv 2509.11098).
7. Joachims, Swaminathan & Schnabel, "Unbiased Learning-to-Rank with Biased Feedback" (WSDM 2017).

## Known Risks / Open Questions

- **Label validity**: "brain-rot" differs from person to person. Mitigations: the rubric, the gold set, per-item feedback reported through `ReportImpressions`. Later: per-user calibration.
- **Supply imbalance and exhaustion**: educational content may be scarce, and the ~20k-item PoC catalog makes pool exhaustion likely for heavy users. The seen-set filter plus the `pool_exhausted` shortfall make this visible, and Step 24e measures it.
- **Adversarial creators** gaming the classifier. Mitigations: multimodal + pacing features, adversarial negatives, the creator prior as a feature, periodic teacher audits. These reduce the problem; they don't eliminate it.
- **Weak engagement signal**: MicroLens comments are a sparse proxy. Offline relevance is indicative only; the user study is the ground truth for the PoC.
- **Wellbeing**: the "fun" end is an explicit user choice, and integrity filters still apply there. Post-PoC, consider optional session-time nudges rather than forced mix changes.
- **Expected-share semantics**: a bound can be met with several mid-probability items rather than a few clear ones. Stage 2's clarity tie-break mitigates this, and criterion 2's units check catches it if users disagree.
- **Independence approximation**: the exclusive mass `q_d·(1−q_k)` assumes the two dimensions are conditionally independent. Check it against the gold set's joint labels, and fit a joint head if it's badly off. If users perceive the result as too coarse, revisit with a soft share as a secondary objective.

## Deliberately Not Applied

- *Round 2, M9 alternative "stochastic Plackett-Luce assembly with logged propensities"*: not used. It would give up the exact mix guarantee that is the product's core promise. IPS is restricted to the exploration slots instead.
- *Round 2, M5 option "absolute/hinge or KL penalty in the greedy"*: superseded by the ILP. Round 3 found that a β bonus had brought the scaling problem back, so the tie-break is now lexicographic (stage 2), which is scale-free.
- *Round 3, minor 1 option "enumerate the 4 categories exactly without a solver"*: not used as the primary path, because it doesn't extend to N dimensions. It remains a valid fallback for N = 2 if scipy is unavailable.
- *Round 1, M1 alternative "ILP per window"* was declined in round 1 and **adopted in round 2** after the reviewer showed that the greedy soft-penalty assembler settles below its target.
- *Round 4, M1*: adopted a stronger variant of the reviewer's fix. Bounds are one-sided relative to the *current* unsteered page, and the stored baseline `h` (EMA, freeze, drift clip) was **removed entirely**, which also retires round 3's drift handling.
- *Round 5, m6 alternative "check Σ t_d from the current U0 at control time"*: not used. Slack with the `conflicting_targets` reason already covers it, and a second, approximate feasibility model would be one more thing to keep consistent.

## Review Status

Five adversarial review rounds ran, which is the loop's cap (see `review-log.md`).
- **Round 5**: 0 blockers, 3 majors.
- **The three majors**:
  - big-M slack weighting → now stage 0;
  - inconsistent units on the pushed-down side → exclusive share used everywhere;
  - low-d source targeting the wrong quantity, and unreachable T_min → sources ordered by `e_d`, end points measured.
- All of them, plus the round-5 minors and nits, are applied above, but **no independent reviewer has checked the round-5 fixes**.
- The remaining risk is concentrated in Steps 14–18 (the control math). Everything else has been stable since round 3.
- **After the review loop**, the plan was re-scoped to the algorithm only: the HTTP service, control API and demo client were replaced by the Step 21–22 RPC contract. The algorithm steps themselves did not change.
