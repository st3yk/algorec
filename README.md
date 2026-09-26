# steerrec

A steerable short-video recommender. The user moves one "Fun ↔ Learn" control,
and the feed's content mix follows it, reliably and visibly, while staying
personally relevant.

This repository currently contains the **steering core**: given scored
candidates, it picks and orders a page that honors the control. The items are
synthetic, and there are no models or videos yet.

```sh
bazel run //steerrec:demo      # see BUILDING.md for setup
bazel test //...
```

- **Where it's going**: [`NORTH_STAR.md`](NORTH_STAR.md)
- **How it works**: [`docs/`](docs/README.md), starting with [concepts](docs/concepts.md)
- **Service contract**: [`proto/steerrec/v1/recommender.proto`](proto/steerrec/v1/recommender.proto), explained in [docs/service-contract.md](docs/service-contract.md)
- **Working here as an agent**: [`AGENTS.md`](AGENTS.md)

## The idea in four lines

1. Each request computes the **neutral page U0**: the top 10 by relevance, one
   item per creator.
2. The slider turns into **one-sided bounds relative to U0**: "at least this
   much more educational", and "at most this much *pure* light content", so
   edutainment isn't punished.
3. A **small integer program, solved in stages**, picks the page: first miss the
   bounds as little as possible, then maximize relevance, then prefer clear
   examples.
4. If a bound can't be met, the page is still served and the gap is reported as
   a **shortfall**. It never fails silently.

## What the demo shows

On the seed-0 synthetic pool, the ranker stand-in favors light content, so the
neutral page is mostly "brain-rot". Sweeping the slider
(`bazel run //steerrec:demo -- --sweep-only`):

```
      s    edu  light  pure_edu  pure_lgt  mean p  steered  shortfall
  -1.00   0.15   0.92      0.01      0.79    0.90        4  -
  ...
  +0.00   0.19   0.69      0.06      0.55    0.92        0  -
  +0.20   0.33   0.58      0.14      0.39    0.89        3  -
  +0.60   0.49   0.51      0.26      0.28    0.85        4  -
  +1.00   0.67   0.42      0.35      0.10    0.76        8  -
```

The educational share climbs, pure light falls, and total light stays fairly
high (edutainment survives). Mean relevance falls from 0.92 to 0.76, and that
visible drop is the real cost of steering. The left side is flat for this user;
[the demo docs](docs/code/synthetic-and-demo.md#reading-the-seed-0-sweep)
explain why.
