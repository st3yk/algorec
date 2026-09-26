# `items.py` and `registry.py`: inputs and configuration

## `steerrec/items.py`

### `Item(video_id, creator_id, p, q)`

A frozen dataclass: one candidate video as the assembler sees it.

| Field | Meaning |
|---|---|
| `video_id` | Unique id. It is also the deterministic tie-breaker everywhere. |
| `creator_id` | The creator rule allows at most one item per creator on a page. |
| `p` | Calibrated relevance in [0, 1]. |
| `q` | `{dim_id: probability}`, each in [0, 1]. |

- `__post_init__` copies `q` into a read-only `MappingProxyType`, so scores
  cannot change after validation, and a later change to the caller's dict does
  not leak in. `q` is excluded from the hash, so items stay hashable.
- It raises `ValueError` if `p` or any `q` value is outside [0, 1].
- `q_of(dim_id)` returns 0 for a dimension the item has no score for ("not that
  kind"). In the full system, every item will be scored for every registered
  dimension before it can be retrieved, so this default only matters for
  hand-built fixtures. Misspelled keys are caught by `Registry.check_scores`.

## `steerrec/registry.py`

### `Dimension`

The steering parameters for one content dimension.

| Field | Default | Meaning |
|---|---|---|
| `dim_id` | — | Stable key, used in controls and in `Item.q`. |
| `t_max` | 0.6 | How high a pushed-up total share may be pushed. |
| `t_min` | 0.1 | How low a pushed-down exclusive share may be pushed. |
| `priority` | 1.0 | Weight of this dimension's slack in stage 0. Must be finite and ≥ 1. |
| `tau` | 0.6 | "Strongly *d*" threshold. Used only for display labels and, later, retrieval masks. Never used in the mix constraints. |

Validation requires `0 ≤ t_min ≤ t_max ≤ 1` and `0 ≤ tau ≤ 1`.

`t_max` and `t_min` are product end points in expected-share units. The defaults
are starting guesses. In the full system they will be measured: `t_max` is capped
by what clearly-*d* items actually score (annotator disagreement keeps `q` below 1),
and `t_min` is floored by the `q` noise level.

### `Registry`

An ordered, immutable set of dimensions keyed by id. Everything downstream
iterates over it in registry order, so adding a dimension means adding an entry.

- It raises on duplicate ids or an empty registry.
- `validate_control(control)` returns a new dict with each value clamped to
  [−1, 1]. It rejects:
  - unknown dimension ids;
  - non-numbers, including bool and strings (numpy scalars are fine);
  - NaN, because `max`/`min` would otherwise turn NaN into +1, "maximum
    learning".
- `check_scores(q)` rejects score keys the registry doesn't know. A typo such as
  `"educationl"` would otherwise read silently as q = 0. The assembler calls it
  on every pool item, not just those in U0.

### Constants and helpers

- `EDUCATIONAL = "educational"` and `LIGHT = "light_entertainment"` are the two
  proof-of-concept dimensions.
- `DEFAULT_REGISTRY` holds both, with default parameters.
- `single_slider(s)` returns `{EDUCATIONAL: s, LIGHT: -s}`.
