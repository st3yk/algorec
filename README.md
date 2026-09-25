# steerrec: a steerable short-video recommender (minimal slice)

This is the first slice of the proof-of-concept designed in
[`short-content-recsys-design/plan.md`](short-content-recsys-design/plan.md).
It contains **only the steering idea**: no videos, no ML models, no service.
Items are synthetic, so you can read the code, run the demo, and see how a
user-controlled "Fun ↔ Learn" slider changes a feed.

```sh
bazel run //steerrec:demo      # see BUILDING.md for setup
bazel test //...
```

## The idea in five steps

Each candidate video carries two numbers that, in the full system, come from
models (plan Steps 5–7 and 12). Here they are given directly:

- `p`: how likely this user is to engage (relevance).
- `q[d]`: the probability that a human would call the video "educational" or
  "light entertainment" (one number per dimension, calibrated so a sum of
  `q`s is an expected count).

For every feed request:

1. **Neutral page, `U0`** ([`targets.py`](steerrec/targets.py) `unsteered_page`, plan Step 13):
   the top-10 by relevance, one video per creator. This is what the user
   would see with the slider at 0. It is recomputed on every request, so
   there is no stored baseline that can drift.
2. **Slider → one-sided targets** (`compute_bounds`, plan Step 14). The slider
   never sets an absolute mix. It says:
   - "**at least this much more** educational than `U0`": a *lower* bound on
     the educational share, moving from `U0`'s share toward `T_max` = 0.6 as
     the slider goes to 1;
   - "**at most this much** *pure* light content": an *upper* bound on light
     content that is **not** also educational. That's why a fun science video
     ("edutainment") isn't suppressed when you ask for more learning.

   The slider to the left mirrors this. A steered page never moves *against*
   the slider relative to neutral, even when a target can't be met: the
   assembler enforces "no less of the pushed-up kind, no more pure pushed-down
   content than `U0`" as hard constraints.
3. **Pick the page with a small integer program**
   ([`assembler.py`](steerrec/assembler.py), plan Step 17), solved in stages:
   - stage 0: miss the bounds as little as possible;
   - stage 1: then maximize relevance;
   - stage 2: then prefer *clear* examples, giving up at most 2% relevance.

   Because the stages run in order, the mix is never traded against relevance
   through a weight you'd have to tune.
4. **Shortfall, never silence.** If the pool can't meet a bound (e.g. there is
   no educational content), the page is still served, and the gap is returned
   as a `Shortfall` so a client can say "not much educational content right
   now". If a solver stage fails or runs out of time, the previous stage's page
   is used; after a stage-1 failure it's compared with a greedy page and the
   better one wins. Only if stage 0 itself fails does the greedy page alone
   get served.
5. **Order the page.** Items that are there only because of steering are
   spread evenly, not bunched at the end.

## What the demo shows

On the seed-0 synthetic pool, the ranker stand-in prefers light content, so
the neutral page is mostly "brain-rot":

```
=== slider s = +0.00
   1    light    0.98   0.23   0.81  POV: music but it's chaotic
   2    light    0.95   0.09   0.91  travel fails compilation #14
   ...
   9    neither  0.88   0.06   0.18  travel highlights, clip 55
  mix: edu 0.19 | light 0.69 | pure light 0.55 | mean p 0.92
```

Sweeping the slider (`bazel run //steerrec:demo -- --sweep-only`):

```
      s    edu  light  pure_edu  pure_lgt  mean p  steered  shortfall
  -1.00   0.15   0.92      0.01      0.79    0.90        4  -
  -0.80   0.15   0.92      0.01      0.79    0.90        4  -
  -0.60   0.15   0.92      0.01      0.79    0.90        4  -
  -0.40   0.15   0.92      0.01      0.79    0.90        4  -
  -0.20   0.15   0.92      0.01      0.79    0.90        4  -
  +0.00   0.19   0.69      0.06      0.55    0.92        0  -
  +0.20   0.33   0.58      0.14      0.39    0.89        3  -
  +0.40   0.43   0.57      0.24      0.37    0.87        3  -
  +0.60   0.49   0.51      0.26      0.28    0.85        4  -
  +0.80   0.56   0.49      0.26      0.19    0.81        6  -
  +1.00   0.67   0.42      0.35      0.10    0.76        8  -
```

How to read it:
- **Right side**: the educational share climbs steadily and pure light falls,
  while *total* light stays fairly high. That's the edutainment carve-out
  working. Mean relevance falls from 0.92 to 0.76: that drop is the real cost
  of steering, and it's visible instead of hidden.
- **Left side is flat**, which is worth understanding:
  - This user's neutral page is already 0.69 light, above `T_max` = 0.6, and
    only 0.06 purely educational, below `T_min` = 0.1. So neither left-side
    target has anywhere to go: the plan uses `max(T_max, u)` and
    `min(T_min, ū)` so that pushing never moves a target backwards.
  - The 4 swaps you see come only from stage 2's clarity preference, which
    may give up to 2% relevance for clearer items. It isn't scaled by |s|, so
    it switches fully on at any s < 0.
  - Try `--delta 0` to see the left side without it. The synthetic test also
    runs a registry with different end points, where the left side does move.

## Code map (read in this order)

| File | What | Plan step |
|---|---|---|
| [`steerrec/items.py`](steerrec/items.py) | `Item(video_id, creator_id, p, q)` | inputs from Steps 7, 12 |
| [`steerrec/registry.py`](steerrec/registry.py) | Dimensions, slider end points, control validation, `single_slider` | 8, 21 |
| [`steerrec/targets.py`](steerrec/targets.py) | `U0`, exclusive mass, one-sided bounds | 13, 14 |
| [`steerrec/assembler.py`](steerrec/assembler.py) | Staged ILP, shortfalls, ordering, fallback | 15, 17 |
| [`steerrec/synthetic.py`](steerrec/synthetic.py) | Seeded fake catalog with titles and hidden kinds | stand-in for 5–7, 12 |
| [`steerrec/demo.py`](steerrec/demo.py) | The CLI above | — |
| [`tests/`](tests/) | Property tests; the ILP checked against brute force; plan criterion 1 | — |

## What the tests establish

- The ILP's page matches brute-force enumeration of every possible page on
  small pools, for all three stages.
- Every bound is met, or its exact gap is reported, including for empty,
  single-creator and no-supply pools.
- Targets are linear in |s|, never point against the slider, and respect the
  end points.
- No page ever ends up on the wrong side of neutral, including pages with a
  shortfall and fallback pages.
- The page doesn't depend on the order of the pool, even with tied scores.
- **Plan criterion 1**: averaged over synthetic users, the realized share
  moves monotonically with the slider (within 0.03) on both sides.

## Things this slice found about the design

These are recorded in [`build-log.md`](short-content-recsys-design/build-log.md):

- **Per user, the realized share isn't strictly monotone in the slider.** The
  plan's Step 15 claims it is. With two bounds moving at once, the best page
  can switch, and the share can dip ~0.04 while still inside its bound. The
  *mean* over users is monotone, which is what the plan's success criterion
  measures.
- **"Never below neutral" needs explicit constraints.** Stage 0 minimizes a
  weighted sum of misses. Left alone, it traded educational content away to
  shrink the light miss, so a page at full "Learn" could be *less*
  educational than neutral. Hard "not worse than `U0`" constraints fix it.
- **Stage 2 turns on as a step.** At any s ≠ 0 it can already swap items;
  scaling its effect by |s| is a candidate change.
- **Solver time.** On a 300-item pool the ILP stages take ~20–150 ms each,
  not "a few ms". With the plan's 50 ms limit, pages silently got worse. The
  slice now uses one shared 2 s budget (from the moment `assemble` is called)
  and flags any early stop. Meeting a 300 ms budget will need a smaller pool or warm starts.
- The creator rule is a hard constraint here, and shortfalls have no "reason"
  field (that needs the retrieval stages).

## Not in this slice

Retrieval and candidate sources, the ranker, video feature extraction and
labeling, relevance floors and safety filters, supply widening, exploration,
and the `GetNextBatch` RPC (plan Steps 5–7, 9–12, 16, 18–23).
