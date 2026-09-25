# Review Log: User-Steerable Short-Video Recommender

Round-by-round record of the adversarial review loop, so a reader can see what changed and why without re-deriving it.

## Round 1

**Reviewer verdict:** blocker=1, major=7, minor=6, nit=4 → ITERATE

| Severity | Finding | Action |
|---|---|---|
| blocker | Control mapping `c=(1−s,s)` sums to 1, contradicting the independent-dimensions design; "neither" content got 0 slots; no mapping from c to target mix; "neutral" undefined for cold users | Applied — Step 12 rewritten: per-dimension soft-share targets interpolating from the unsteered baseline mix `h` (global prior for cold users) to `T_max`/`T_min`; no Σ constraint; "neither" keeps the remainder |
| major | Deficit assembler inconsistent for items in both dimensions; no upper bounds | Applied — Step 14 is now a Steck-style greedy with a two-sided squared-deviation penalty on soft shares (handles overlap and over-/under-shoot). The ILP alternative was declined (see plan) |
| major | Per-dimension indexes prebuilt at τ_d can't be relaxed at request time | Applied — a single item matrix with exact search and per-request boolean masks (Step 9); FAISS `IDSelector` filtered search noted for >1M items |
| major | MicroLens interactions are comments (no watch/like); KuaiRec has no raw video; language; item count below the assumption | Applied — scale restated (20k–100k); Step 3 pins MicroLens-100K with a comment-positive signal, a multilingual pipeline, and KuaiRec only with caption/synthetic labels, stated as a weaker proxy; ranker target restated |
| major | Steerability metric tautological (same classifier) and coarse (5-point ρ) | Applied — 11-point sweep, MAE + monotonicity violations, realized share measured with held-out teacher labels and human labels on served pages, consumed mix in simulation |
| major | Offline NDCG under steering invalid against unsteered logs | Applied — neutral-only comparison vs. the baseline; within-dimension relevance at the extremes; KuaiRec fully-observed evaluation; user study as ground truth |
| major | Label targets exceed the human ceiling; 0–4 binarization undefined; the gold set is triple-used (leakage) | Applied — targets relative to human κ; positive = ≥3; gold set split once 20/30/50 dev/calibration/test; enlarged to ~3k with oversampling |
| major | Feedback loop: steered data retrains relevance; control as a zero-variance feature; neutral drifts | Applied — control removed from ranker features; 5% exploration slice with propensities; `h` from unsteered traffic only; IPS / down-weighting of assembled slots |
| minor | Window carry-over after a control change causes overcorrection | Applied — window re-seeded at the new target (Step 16) |
| minor | Keyframes miss pacing ("rapid cuts") | Applied — shot-cut rate, audio energy, speech rate (Step 4) |
| minor | No cold-user embedding | Applied — Step 10 |
| minor | No safety/integrity filter; defaults | Applied — filtering at every setting in Step 13; default slider = 0; wellbeing note |
| minor | Control API abuse; creator gaming | Applied — debounce/rate limit (Step 16); creator-level empirical-Bayes prior and adversarial negatives |
| minor | Timeline aggressive; costs unbudgeted | Applied — 14 weeks, cost-estimation step, pilot run, explicit cut list |
| nit | EMER/Pantheon uncited | Applied — reworded generically |
| nit | A2 vs. A3 framing | Applied — A3 described as "A2 plus quotas and assembler" |
| nit | Status line / Not-Applied section | Applied |
| nit | Background misses labeling ops and GPU batch work | Applied |

---

## Round 2

**Reviewer verdict:** blocker=0, major=9, minor=7, nit=2 → ITERATE

| Severity | Finding | Action |
|---|---|---|
| major | Target mapping not monotone when h is outside [T_min, T_max] | Applied — `T_hi = max(T_max, h)`, `T_lo = min(T_min, h)`; monotone by construction (Step 14) |
| major | Fixed soft-share targets may be unattainable; borderline items satisfy the soft share | Applied — the unit of mix is now the hard share (score ≥ τ_d); T_min/T_max set empirically per dimension from the achievable share; β term prefers clearer items |
| major | Calibration fit on an oversampled gold set; the creator prior breaks calibration | Applied — uniform ~600-item subset + inverse-sampling-rate weights; creator prior moved to a head *input*, and the final served score is calibrated; κ reported reweighted |
| major | `h` leaks the slider via quota-dependent pools; exploration too sparse to move it | Applied — `h` computed counterfactually each request from the general source only, EMA-smoothed (Step 13) |
| major | Greedy squared penalty: scale imbalance, steady-state undershoot, per-request min-max normalization | Applied — replaced by a per-page ILP with integer bounds + carry-over accumulator; calibrated `p_i` needs no normalization (Steps 15–17). Reverses the round-1 decline |
| major | "Independent" measurement is correlated with the student; coverage and units unclear | Applied — criterion split into mechanical (classifier units) and valid (human units, primary); ~2k served-item human labels budgeted; teacher holdout of ~2k items is secondary only |
| major | Monotonicity/MAE ill-defined vs. discreteness and noise | Applied — ≥20 pages per point, ε = 0.03 tolerance, shortfall users reported separately |
| major | No seen-set filter; small educational pool will repeat | Applied — seen-set exclusion in all sources, `pool_exhausted` shortfall reason, exhaustion metric (Step 24e) |
| major | IPS impossible on deterministic assembled slots | Applied — IPS only on exploration slots (independent of the slider); assembled slots down-weighted; stochastic assembly declined (see plan) |
| minor | κ on 0–4 needs ordinal output | Applied — cumulative-logit ordinal heads |
| minor | Relevance floor undefined | Applied — `p ≥ max(p_abs, 0.5·p_(P))`, hard filter (Step 16) |
| minor | Window semantics ambiguous | Applied — window removed; per-page accumulator |
| minor | N-dimension conflicting targets | Applied — `priority_d` relaxation order + `conflicting_targets` shortfall |
| minor | Within-dimension NDCG sparse | Applied — qualifying-user count, bootstrap CIs, "indicative" threshold |
| minor | Phase ordering (gold sampling needs embeddings) | Applied — lightweight extraction pass moved to Phase 0 (Step 2) |
| minor | K_d ignores supply | Applied — K_d adaptive from previous pass-through (Step 10) |
| nit | Vague survey reference | Applied — specific arXiv papers cited |
| nit | Base K undefined | Applied — `K_gen = 200`, K_d formula with clip |

---

## Round 3

**Reviewer verdict:** blocker=1, major=4, minor=7, nit=6 → ITERATE

| Severity | Finding | Action |
|---|---|---|
| blocker | T_min/T_max taken from the natural spread (P10/P90 of the unsteered share) cap the slider near the natural mix, so the ≥0.4 spread is unreachable and user agency is defeated | Applied — T_max/T_min are product end points (e.g. 0.8 / 0.05); unreachability surfaces as shortfall; Step 26 measures achievable spread and criterion 2 is re-set from evidence by week 10 |
| major | "h cannot drift" is false (user embedding and seen set depend on steered traffic) | Applied — h updates only at s = 0 and is frozen while steering; post-steering drift acknowledged, bounded to 0.05 per session, and measured |
| major | β bonus brings back the scaling problem (p ~1e-3 vs score ~[0,1]) | Applied — lexicographic stage-2 solve with a relevance tolerance δ = 2%; scale-free |
| major | Infeasibility handling only covers lower bounds; relaxing τ mislabels items; fallback ignores U_d | Applied — slack-variable ILP (always feasible, slack = shortfall); τ never relaxed (φ_d removed); supply widening first; fallback respects U_d and the creator rule; short pages flagged |
| major | Sequential sweep drains the seen set and biases shortfall by sweep order | Applied — each sweep point starts from a state snapshot |
| minor | Greedy fallback breaks U_d / creator rules | Applied |
| minor | Page-ordering claim was self-contradictory | Applied — quota items at evenly spaced slots |
| minor | s = 0 forced to the EMA mix instead of unsteered | Applied — no dimension constraints at s = 0 |
| minor | N-dimension joint feasibility not validated | Applied — check in `PUT /control` with UI feedback |
| minor | Criterion 1 is tautological | Applied — relabeled as a system test; criterion 2 is primary |
| minor | CIs need a cluster bootstrap; qualifying-user count | Applied |
| minor | p_abs undefined | Applied — user's median p over a random 1k catalog sample |
| nit | "Tang" → Tan (ECAI 2023) | Applied |
| nit | MicroLens-100K has 100k users | Applied — 10k subsample stated |
| nit | w_d step function | Applied — weights proportional to s (stage 2) |
| nit | Near-duplicate embedding unspecified | Applied — mean SigLIP keyframe embedding |
| nit | Exploration yields little data offline | Applied — noted as post-PoC infrastructure |
| nit | "Long-run share = t_d" wording | Applied — time-average; t constant while s is fixed since h is frozen |

---

## Round 4

**Reviewer verdict:** blocker=0, major=4, minor=11, nit=3 → ITERATE

| Severity | Finding | Action |
|---|---|---|
| major | Two-sided bounds around a lagged/frozen `h` can remove wanted items at small s (non-monotone vs. neutral) | Applied (stronger variant) — one-sided bounds relative to *this request's* unsteered page `U0`; stored `h`, EMA, freeze, drift clip and accumulator all removed |
| major | "Always feasible" false: cardinality and creator/duplicate constraints are hard | Applied — cardinality and creator slack; near-duplicates collapsed before the ILP; x = 0 is feasible; `creator_diversity` reason |
| major | Thresholded count ≠ human-measured share | Applied — constraints now on expected share Σq/P, with q calibrated per annotator; τ used only for display/masks; units-check criterion added |
| major | No reliable measure of relevance under steering | Applied — relevance-vs-s curve criterion, human "fits interests" judgement on served pages, steered-relevance simulation removed from the cut list |
| minor | OPT₁ ambiguous under slack; "never trades" wording | Applied — R₁ = relevance term; "at most 2%" |
| minor | Joint-feasibility units | Applied — shares vs. 1 + overlap; upper bounds on exclusive mass can't conflict |
| minor | Supply widening only fixes lower bounds; reason attribution | Applied — low-d source for upper-bound slack; attribution by filter-stage drop counts |
| minor | "Quota-driven" undefined | Applied — steered = not in U0 |
| minor | Fallback greedy can get stuck | Applied — swap-greedy from U0, remainder reported as shortfall |
| minor | Served vs. viewed | Applied — seen set on impression (≥1 s); prefetched pages invalidated |
| minor | T_min at s = +1 bans edutainment | Applied — pushed-down bound on exclusive mass; explicit product decision |
| minor | κ comparison apples-to-oranges; calibrator target | Applied — model-vs-single-annotator; per-annotator samples in calibration |
| minor | "Session" bound undefined | Obsolete — `h` removed |
| minor | Latency without QPS; GIL | Applied — 20 QPS target, multiple workers, p_abs cached |
| minor | Served-item labels single-annotator | Applied — 20% double-labeled |
| nit | Stale step references and status line | Applied |
| nit | need_d at s = 0 | Applied — K_d = 50 |
| nit | M vs. priority scale | Applied — M = 10·P·max p, priority_d ≥ 1 |

---

## Round 5 (loop cap)

**Reviewer verdict:** blocker=0, major=3, minor=7, nit=5 → ITERATE. The 5-round cap was reached. All findings below were applied **after** the last review and have not been independently re-reviewed.

| Severity | Finding | Action |
|---|---|---|
| major | Big-M too weak for continuous slack, causing false shortfalls | Applied — lexicographic stage 0 minimizes slack first; slack < 1e-6 counts as zero |
| major | Pushed-down promise in exclusive units, but criteria measure total share | Applied — "total up / exclusive down" promise defined once and used in Steps 14–15 and criteria 1–2; human exclusive share from joint labels; spread target re-set to a provisional 0.3 |
| major | Low-d source filters on q, not e; T_min below the q noise floor; "can't conflict" claim false | Applied — low-d source ordered by e_d; T_min/T_max measured from the gold set; claim removed, `conflicting_targets` covers it |
| minor | Pool depends on s, breaking the nested-feasibility argument | Applied — K_d uses the \|s\| = 1 target for all s ≠ 0; claim scoped |
| minor | Stage-2 objective rewards overshoot and penalizes edutainment; mapping s → s_d unstated | Applied — clarity objective q(q − 0.5) on D⁺ only; s_edu = s, s_light = −s |
| minor | Exploration slot could break the bounds | Applied — fixed at x = 1 inside the ILP; exploration pages flagged |
| minor | "Last 20 positives" vs. ~7 interactions per user | Applied — min(20, available), users with ≥ 5 positives, bias stated |
| minor | T_max capped by annotator disagreement | Applied — T_max from unanimous-≥3 gold items |
| minor | Static joint-feasibility check inaccurate | Applied — dropped in favor of slack + reason (noted in "Deliberately Not Applied") |
| minor | U0 from general source only is not the relevance optimum | Applied — U0 = unconstrained top-P over the whole pool |
| nit | Review history inside the deliverable | Partially applied — inline mentions removed; "Deliberately Not Applied" kept because the template requires it |
| nit | p_abs under relaxed floor | Applied — still applies |
| nit | Solver time limit / MIP gap | Applied — incumbent values plus tolerance |
| nit | MicroLens videos ~161 s | Applied — cost estimates adjusted |
| nit | Offline impression rule | Applied — every served item counts as seen |

---

## Final Verdict

Round 5: blocker=0, major=3 → **not SHIP-eligible at the cap**. All round-5 findings were applied, but not re-reviewed. The findings have converged: blockers went 1 → 0 → 1 → 0 → 0 and majors 7 → 9 → 4 → 4 → 3, with rounds 4–5 concentrated in the control math (Steps 14–18). A sixth round focused on Steps 14–18 is the recommended next step before implementation.
