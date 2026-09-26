# Concepts: how steering is defined

Every module uses the vocabulary on this page. Read it first.

## Inputs per item

| Symbol | Code | Meaning |
|---|---|---|
| `p_i` | `Item.p` | Calibrated probability that this user engages with item *i* (relevance). In the full system it comes from the ranker. |
| `q_d,i` | `Item.q[d]`, `Item.q_of(d)` | Calibrated probability that a randomly chosen human annotator rates item *i* ≥ 3 (on a 0–4 rubric) for dimension *d*. A missing score counts as 0. |

`q` is calibrated, so a **sum of `q`s is an expected count**. Ten items with
`q_edu = 0.5` are, in expectation, five educational items. This is why shares
can be averaged, bounded and checked against human labels.

Dimensions are independent. An item can be both educational and light
("edutainment") or neither (a vlog, a sports clip). Targets per dimension do not
sum to 1.

## Page quantities

For a page of size `P`:

| Symbol | Code | Definition | Meaning |
|---|---|---|---|
| `m_d` | `targets.total_share` | `(1/P)·Σ q_d,i` | Expected share of the page that humans would call *d*. |
| `e_d,i` | `targets.exclusive_mass` | `q_d,i · Π_{k∈D⁺, k≠d} (1 − q_k,i)` | How much item *i* is *d* and **not** any pushed-up kind. |
| `x_d` | `targets.exclusive_share` | `(1/P)·Σ e_d,i` | Expected share of "pure" *d*. |

`D⁺` is the set of pushed-up dimensions (slider > 0). The exclusive mass
assumes the dimensions are conditionally independent.

Shares are divided by `P`, the page size, not by the number of items actually
on the page. A short page therefore has a lower share, and that counts against
it.

## The neutral page, U0

`U0` (`targets.unsteered_page`) is the top-`P` items by `p`, with at most one
item per creator. It is what the user would see with every slider at 0, and it
is **recomputed on every request** from the current pool. There is no stored
baseline, so nothing can drift or lag, and a brand-new user is handled like
everyone else.

- The greedy scan (descending `p`, skip a creator already on the page) is exact:
  it is the same as taking each creator's best item and then the top `P` of
  those.
- Ties are broken by `video_id`, so the result does not depend on pool order.
- U0 is the relevance optimum. No steered page can be more relevant.

`u_d = m_d(U0)` and `ū_d = x_d(U0)` are the reference points for this request.

## The control

A control is a map `{dim_id: s_d}` with each `s_d ∈ [−1, 1]`.
`Registry.validate_control` clamps values, and it rejects unknown dimensions,
NaN, strings and bools. A dimension at 0 is unconstrained.

The proof of concept exposes one slider `s` (`registry.single_slider`):
`s_edu = s`, `s_light = −s`. So +1 means "more learning" and −1 means "more fun".

## One-sided bounds

The slider **never sets an absolute mix**. It creates one bound per non-zero
dimension, relative to U0 (`targets.compute_bounds`):

**Pushed up (s_d > 0): lower bound on the total share.**

```
t_d = u_d + |s_d| · (max(T_max_d, u_d) − u_d)
constraint: Σ x_i q_d,i ≥ t_d · P
```

**Pushed down (s_d < 0): upper bound on the exclusive share.**

```
t_d = ū_d − |s_d| · (ū_d − min(T_min_d, ū_d))
constraint: Σ x_i e_d,i ≤ t_d · P
```

Consequences:

- `t_d` moves linearly in |s| from the U0 value toward the registry end point
  (`T_max` = 0.6, `T_min` = 0.1 by default).
- The `max`/`min` terms mean a target never moves *backwards*. If U0 is already
  past the end point, the target stays at U0's value.
- The pushed-down bound counts only *pure* content, so "more learning" does not
  suppress a funny science video.
- With N dimensions, the formulas are the same. The exclusive mass is taken with
  respect to all pushed-up dimensions.

A `Bound` object (`targets.Bound`) carries `target`, `reference` (u or ū),
`coefficient(item)` (`q_d,i` or `e_d,i`) and `mass` (= `target · P`, the
right-hand side in item units).

## What is guaranteed

- Every page meets each bound, or the gap is reported as a `Shortfall`.
- Every page, including shortfall and fallback pages, is **never on the wrong
  side of neutral**: pushed-up mass ≥ U0's, pushed-down exclusive mass ≤ U0's.
  This takes explicit hard constraints (see [assembler](code/assembler.md)).
- The **mean** realized share over users is monotone in the slider within 0.03.

What is **not** guaranteed: that one user's share is monotone in |s|. With two
bounds moving at once (edu up, light down), the most relevant feasible page can
switch, and the share can dip about 0.04 against the slider while staying
inside its bound.

## Glossary

| Term | Meaning |
|---|---|
| Page size, `P` | Items per page (default 10). |
| Pool | The candidate items for one request. Today it is synthetic; later it will be the union of retrieval sources. |
| Steered item | An item on the page that is not in U0 (`Page.steered_ids`). |
| Slack | How much a bound (or the page size) is missed, in items. |
| Shortfall | Slack reported to the caller: `BOUND` (a dimension) or `CARDINALITY` (fewer than `P` distinct-creator items exist). |
| Clarity | `q·(q − 0.5)` summed over pushed-up dimensions: prefers items that are clearly *d* over borderline ones. |
| Creator rule | At most one item per creator per page. |
