# Service contract

The contract is [`proto/steerrec/v1/recommender.proto`](../proto/steerrec/v1/recommender.proto)
(Bazel target `//proto:recommender_proto`, import path
`steerrec/v1/recommender.proto`). This page gives the meaning of each field.

**Status**: the contract is specified and compiles, but no server exists yet.
The "Backed by today" column says which part of `steerrec/` a field maps to.

The recommender is a standalone gRPC service with two calls. The backend calls
`GetNextBatch` to get video ids, and it calls `ReportImpressions` to report what
was actually watched.

## `GetNextBatch`

**The control is a per-request input, not stored state.** A slider change needs
no separate API: the backend discards any prefetched batch and calls again with
the new `control`.

### `GetNextBatchRequest`

| Field | Meaning | Backed by today |
|---|---|---|
| `user_id` | An unknown user is served as a cold user, not rejected. | — |
| `request_id` | Idempotency key. A retry with the same `(user_id, request_id)` returns the same batch and doesn't consume new videos or log twice. | — |
| `batch_size` | `P`. Default 10, max 50. | `assemble(page_size=...)` |
| `control` | `dim_id → s_d`. Values outside [−1, 1] are clamped; an unknown `dim_id` returns `INVALID_ARGUMENT`; a missing dimension means 0. The PoC single slider is `{"educational": s, "light_entertainment": -s}`. | `Registry.validate_control`, `single_slider` |
| `exclude_video_ids` | Served but not yet reported (e.g. still on the device). Excluded from every source. | — |
| `cold_start.topic_ids` | Topics picked at onboarding. Used only while the user has fewer than 5 positives. | — |

### `GetNextBatchResponse`

| Field | Meaning | Backed by today |
|---|---|---|
| `batch_id` | Echoed back in `ReportImpressions`. | — |
| `videos` | In display order. May be shorter than `batch_size`; see `shortfalls`. | `Page.items` |
| `shortfalls` | Empty when every bound was met. | `Page.shortfalls` |
| `registry_version` | The dimension registry and model version used. | — |

### `RecommendedVideo`

| Field | Meaning | Backed by today |
|---|---|---|
| `video_id`, `position` | The item and its 1-based slot. | `Item.video_id`, index in `Page.items` |
| `slot_type` | `ASSEMBLED` (chosen by the ILP), `EXPLORATION` (a sampled slot, not yet built), `FALLBACK` (the solver could not finish in time, so the greedy page was served). | `Page.used_fallback` |
| `dimension_scores` | Calibrated `q_d`, for "why this?" display. | `Item.q` |
| `strong_dims` | Dimensions with `q_d ≥ tau_d`. | `Dimension.tau` |

### `Shortfall`

| Field | Meaning | Backed by today |
|---|---|---|
| `dim_id` | The dimension whose bound was missed. | `Shortfall.dim_id` |
| `amount` | Missing expected-share mass, in items. | `Shortfall.amount` |
| `reason` | `LOW_SUPPLY` (little such content in the catalog), `POOL_EXHAUSTED` (the seen set removed it), `BELOW_RELEVANCE` (the relevance floor removed it), `CREATOR_DIVERSITY`, `CONFLICTING_TARGETS`. | **Not yet.** Reasons come from the retrieval and filter stages. Today the code reports only `BOUND` or `CARDINALITY`. |

### Behavior the server must keep

- **Deadline**: the server keeps an internal budget below the caller's deadline.
  If the solver can't finish, it returns the fallback page (`FALLBACK`), not an
  error.
- **Concurrency**: several worker processes, because the ranker and the solver
  hold Python's GIL.
- **Offline evaluation** calls the same handler in-process, so evaluation tests
  exactly what the backend will call.

## `ReportImpressions`

### `Impression`

| Field | Meaning |
|---|---|
| `batch_id`, `video_id` | Which served item. Idempotent per `(batch_id, video_id)`. |
| `viewed_at_unix_ms` | When it was viewed. |
| `watch_seconds` | A video enters the seen set only when `watch_seconds ≥ 1`. Served-but-unwatched videos therefore don't drain supply. |
| `commented`, `liked` | Outcomes. They are positives for retraining, joined to the serving log by `batch_id`. |
| `feedback` | Optional per-dimension "not educational / not fun to me" (`DimensionFeedback.disagrees`). Stored as label data for future per-user calibration. |

`ReportImpressionsResponse` is empty.

## Changing the contract

- The proto is the source of truth. Update this page in the same commit.
- Follow proto3 compatibility: never reuse or renumber a field, and add new
  fields with new numbers.
- `bazel build //proto:recommender_proto` checks that it compiles.
