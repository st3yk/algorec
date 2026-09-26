# `synthetic.py` and `demo.py`: fake data and the CLI

## `steerrec/synthetic.py`

Until the scoring and ranking stages exist, items come from a seeded synthetic
catalog.

`make_catalog(n_items=300, n_creators=120, seed=0) -> Catalog`

- Each item gets a hidden `Kind`. The catalog mix is 45% `LIGHT`, 25%
  `EDUCATIONAL`, 20% `NEITHER` and 10% `EDUTAINMENT`.
- `q_edu`, `q_light` and `p` are drawn from Beta distributions that depend on
  the kind (`_PARAMS`). Creators are drawn uniformly from `n_creators`.
- **Relevance is deliberately biased toward light content**, as an
  engagement-trained ranker tends to be. That makes the neutral feed skew toward
  "brain-rot" and gives the slider something to do.
- Titles are generated from per-kind templates, so the demo is readable.
- The output is deterministic for a given `(n_items, n_creators, seed)`.

`Catalog` holds `items`, `titles` (video_id → title) and `kinds` (video_id →
hidden kind). The kinds are for display and tests only. The assembler never
sees them.

## `steerrec/demo.py`

```sh
bazel run //steerrec:demo
bazel run //steerrec:demo -- --slider 0.7 --seed 3
bazel run //steerrec:demo -- --sweep-only --delta 0
```

| Flag | Default | Meaning |
|---|---|---|
| `--slider` (repeatable) | −1, 0, 0.5, 1 | Slider values to show full pages for. |
| `--seed` | 0 | Catalog seed. |
| `--pool-size` | 300 | Number of candidate items. |
| `--page-size` | 10 | `P`. |
| `--delta` | 0.02 | How much stage-1 relevance stage 2 may give up. 0 turns the clarity preference off. |
| `--sweep-only` | off | Print only the sweep table. |

- `render_page` prints the bounds, then one line per item. The line shows the
  position, `*` if the item is steered, the hidden kind, `p`, `q_edu`, `q_light`
  and the title. Then it prints the mix, any shortfalls, and the
  fallback/time-limit flags.
- `render_sweep` prints one row per slider point from −1 to 1 in steps of 0.2.
  Each row has the total and pure shares, mean `p`, the number of steered
  items, and whether there is a shortfall.

### Reading the seed-0 sweep

- **Right side**: the educational share climbs steadily and pure light falls,
  while *total* light stays fairly high. That is the edutainment carve-out
  working. Mean relevance falls from 0.92 to 0.76. That drop is the real cost of
  steering, and it is shown, not hidden.
- **The left side is flat.** This user's neutral page is already 0.69 light,
  above `T_max` = 0.6, and only 0.06 purely educational, below `T_min` = 0.1.
  Neither left-side target has anywhere to go. The 4 swaps come only from stage
  2's clarity preference, which is fully on at any s ≠ 0. Run with `--delta 0`
  to see the left side without it.
