# `targets.py`: the neutral page and the bounds

The math is in [concepts](../concepts.md). This page describes the functions.

## `dedupe_pool(pool) -> list[Item]`

Keeps one entry per `video_id`, in first-seen order. In the full system the pool
is a union of retrieval sources, so the same video can arrive more than once.

- It drops identical repeats.
- It **raises** if a `video_id` arrives twice with different creator, `p` or
  `q`. That is an upstream bug. Picking one copy would make the result depend on
  pool order.

## `unsteered_page(pool, page_size) -> list[Item]`

U0: the pool is deduplicated, sorted by `(-p, video_id)`, and scanned, skipping
creators already on the page, until `page_size` items are taken. It returns
fewer items if the pool has fewer distinct creators. It raises if
`page_size < 0`.

## `exclusive_mass(item, dim_id, pushed_up) -> float`

`q_d · Π (1 − q_k)` over `k` in `pushed_up`, skipping `k == dim_id`, since a
dimension is never "exclusive of" itself.

## `total_share(items, dim_id, page_size)` and `exclusive_share(items, dim_id, pushed_up, page_size)`

`m_d` and `x_d`. Both divide by `page_size`, not by `len(items)`.

## `BoundKind`

- `LOWER_TOTAL`: a pushed-up dimension, `Σ x q_d ≥ t·P`.
- `UPPER_EXCLUSIVE`: a pushed-down dimension, `Σ x e_d ≤ t·P`.

## `Bound`

A frozen dataclass: `dim_id`, `kind`, `target`, `reference`, `pushed_up`, `page_size`.

- `mass`: `target · page_size`, the constraint's right-hand side in items.
- `coefficient(item)`: `q_d` for `LOWER_TOTAL`, and `e_d` with respect to
  `pushed_up` for `UPPER_EXCLUSIVE`.
- `realized(items)`: the page's share in this bound's units.

## `compute_bounds(control, u0, registry, page_size) -> list[Bound]`

It first validates its inputs and raises on any of these:
- `page_size` is not a positive `int` (a `bool` doesn't count);
- `u0` is longer than the page;
- `u0` repeats a video or a creator, which means it wasn't built with
  `unsteered_page`;
- an unknown score key;
- an invalid control.

Then it works through the dimensions **in registry order**, not the control dict's
order, so the output order and the floating-point products are stable:
- It collects `pushed_up`, the dimensions with `s > 0`.
- For each non-zero dimension, it builds a `LOWER_TOTAL` or `UPPER_EXCLUSIVE`
  bound with the formulas in [concepts](../concepts.md#one-sided-bounds).
- Dimensions at 0 get no bound, so an all-zero control returns `[]`.
