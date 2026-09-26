# North Star

## The product in one sentence

A short-video feed where **the user holds the dial**: one control, "Fun ↔ Learn",
moves the feed's content mix visibly and reliably, and the feed stays personally
relevant at every setting.

## Why

Engagement-trained feeds drift toward whatever holds attention: fast, meme-heavy
"brain-rot". Users who want something else can only scroll past it. steerrec
gives them a direct lever, and it keeps the promise the lever makes, instead of
nudging a hidden score and hoping.

## Promises the system keeps

These hold at every layer, now and later. A change that breaks one of them is a
change to the product, not an implementation detail.

1. **The slider never moves the feed the wrong way.** A steered page has at
   least as much of the pushed-up kind, and no more *pure* pushed-down content,
   than the neutral page this request would have got. There is no stored
   baseline that can drift.
2. **The mix is guaranteed or the gap is reported.** Each page meets its targets
   or returns a `Shortfall` saying by how much it missed. It never fails
   silently, and it never returns an empty page.
3. **The mix comes first, relevance second, and no weight trades one for the
   other.** Within the mix, the page is the most relevant one available.
4. **Edutainment is not punished.** "More learning" suppresses content that is
   *only* light, not fun content that also teaches, and vice versa.
5. **Units that humans can check.** A page's "educational share" is the expected
   fraction of human annotators who would call its items educational. Every
   target and every measurement uses that unit.
6. **Content, not behavior, decides what an item is.** A new video can be steered
   as soon as it is scored, before anyone has watched it.
7. **N dimensions, not two.** "Calm", "local", "original" are registry entries,
   not re-architectures.

## What success looks like

- **Mechanical**: across a slider sweep, every page meets its bound or reports a
  shortfall, and the mean realized share per slider point is monotone within
  0.03. (Tested today on synthetic users.)
- **Valid**: humans labeling served pages see the mix move with the slider, in
  their own judgement, at five slider points.
- **Relevant**: relevance falls gracefully as the slider moves away from neutral,
  and the cost is measured and shown, not hidden.
- **Fast**: a 10-item page in under 300 ms at p95 on one node at 20 QPS. A slider
  change takes effect on the next request, not after retraining.

## Where we are

| Area | Status |
|---|---|
| Steering core: neutral page, one-sided targets, staged ILP assembler, shortfall, fallback, page ordering | **Built** (`steerrec/`), on synthetic items |
| Service contract (`GetNextBatch`, `ReportImpressions`) | **Specified** (`proto/steerrec/v1/recommender.proto`); not served yet |
| Item dimension scoring (rubric, gold set, MLLM teacher, calibrated student heads) | Not started |
| Retrieval sources, seen set, cold start | Not started |
| Ranker (calibrated relevance `p`) | Not started |
| Relevance floor, safety filters, near-duplicate collapse | Not started |
| Supply widening and shortfall reasons | Not started |
| Exploration slots and logging | Not started |
| Offline evaluation, human-labeled steerability, user study | Not started |

[`docs/`](docs/README.md) explains what is built. The rest of this file describes
where the system is heading.

## The shape of the full system

```
upload ──► feature extraction ──► calibrated dimension scores q_d      (content, per item)

request ──► retrieval sources ──► filters + relevance floor ──► ranker p ──► assembler ──► page
            (general, per-dimension,  (safety, seen set,                    (neutral page U0,
             low-d, fresh)             near-duplicates)                      one-sided bounds,
                                                                             staged ILP)
                ▲                                                                 │
                └────────────── supply widening on shortfall ◄────────────────────┘

watched videos ──► ReportImpressions ──► seen set, logs, retraining
```

The user's control acts at two points:

1. **Retrieval quotas** make sure the candidate pool contains enough of the
   wanted kind.
2. **The assembler** picks the page with per-dimension bounds relative to the
   neutral page. This is the part that exists today.

## Direction for the parts not yet built

- **Scoring**: an operational rubric per dimension; a gold set with human
  agreement measured (α ≥ 0.6 before going on); a multimodal LLM as teacher,
  accepted only when it agrees with humans nearly as well as humans agree with
  each other; small per-dimension student heads on frozen content features
  (transcript, keyframes, pacing, creator prior), calibrated so that `q` is
  "probability a random annotator says yes".
- **Retrieval**: one item matrix with per-request masks. Every source excludes
  the seen set. Per-dimension sources are sized from the |s| = 1 target so the
  pool does not depend on the slider's magnitude.
- **Ranker**: a calibrated probability of engagement, comparable across
  requests. The control setting is **not** a feature: relevance must not depend
  on steering.
- **Shortfall**: before reporting, widen supply and re-solve once. Report the
  remaining gap with a reason (`low_supply`, `pool_exhausted`,
  `below_relevance`, `creator_diversity`, `conflicting_targets`).
- **Exploration**: a small share of pages carry one slider-independent sampled
  slot with a logged propensity. Only those slots are used for unbiased
  learning.
- **Language and build**: Python and Bazel for the whole proof of concept. If the
  online path becomes the bottleneck, move only the `GetNextBatch` handler to Go
  or Rust behind the same proto.

## Open questions we know about

- **Solver latency.** The staged ILP takes about 20–150 ms per stage on a
  300-item pool. Meeting 300 ms p95 at about 500 candidates needs pool pruning,
  warm starts, or a faster formulation.
- **Per-user monotonicity.** With two bounds moving at once, one user's share can
  dip about 0.04 against the slider while staying inside its bound. Only the
  mean is monotone. Is that acceptable to users?
- **Stage 2 switches on as a step.** The clarity preference is fully on at any
  s ≠ 0. Scaling it by |s| is a candidate change.
- **Independence.** The "pure light" mass assumes the dimensions are
  conditionally independent. Check against joint human labels.
- **Label validity.** "Brain-rot" differs from person to person. Per-item
  feedback in `ReportImpressions` is the first step toward per-user calibration.
- **Supply.** Educational content may be scarce, and heavy users may exhaust it.
  Shortfall makes this visible. Whether it is acceptable is a product question.

## Non-goals

- The application backend and client: UI, auth, sessions, profile storage.
  steerrec is the service behind the proto.
- Deciding for the user what is good for them. Both ends of the slider are
  legitimate choices, and safety filters apply at every setting.
