"""Show what the slider does, on a synthetic candidate pool.

    bazel run //steerrec:demo
    bazel run //steerrec:demo -- --slider 0.7 --seed 3
    bazel run //steerrec:demo -- --sweep-only

For each slider value it prints the assembled page (items marked * are on the
page only because of steering, i.e. they are not in the unsteered page U0),
the targets derived from the slider, and any shortfall. It ends with a sweep
table showing how the page's mix and relevance change across the slider.
"""

import argparse
import sys
from typing import Optional, Sequence

from steerrec.assembler import Page, assemble
from steerrec.registry import DEFAULT_REGISTRY, EDUCATIONAL, LIGHT, single_slider
from steerrec.synthetic import Catalog, make_catalog
from steerrec.targets import BoundKind, exclusive_share, total_share


def _shares(page: Page, page_size: int) -> dict[str, float]:
    items = page.items
    return {
        "edu": total_share(items, EDUCATIONAL, page_size),
        "light": total_share(items, LIGHT, page_size),
        "pure_light": exclusive_share(items, LIGHT, (EDUCATIONAL,), page_size),
        "pure_edu": exclusive_share(items, EDUCATIONAL, (LIGHT,), page_size),
        "relevance": sum(it.p for it in items) / max(1, len(items)),
    }


def render_page(s: float, page: Page, catalog: Catalog, page_size: int) -> str:
    lines = [f"=== slider s = {s:+.2f} " + "=" * 50]
    if page.bounds:
        for b in page.bounds:
            unit = "total share" if b.kind is BoundKind.LOWER_TOTAL else "pure share (not the pushed-up kind)"
            op = ">=" if b.kind is BoundKind.LOWER_TOTAL else "<="
            lines.append(f"  target: {b.dim_id} {unit} {op} {b.target:.2f}   (unsteered page: {b.reference:.2f})")
    else:
        lines.append(f"  neutral: no mix constraints, the page is the unsteered top-{page_size} by relevance")
    lines.append(f"  {'#':>2}  {'':1} {'kind':7} {'p':>5} {'q_edu':>6} {'q_lgt':>6}  title")
    for pos, it in enumerate(page.items, start=1):
        mark = "*" if it.video_id in page.steered_ids else " "
        kind = catalog.kinds[it.video_id].value
        lines.append(
            f"  {pos:>2}  {mark} {kind:7} {it.p:5.2f} {it.q_of(EDUCATIONAL):6.2f} {it.q_of(LIGHT):6.2f}  "
            f"{catalog.titles[it.video_id]}"
        )
    sh = _shares(page, page_size)
    lines.append(
        f"  mix: edu {sh['edu']:.2f} | light {sh['light']:.2f} | pure light {sh['pure_light']:.2f}"
        f" | mean p {sh['relevance']:.2f}"
    )
    for sf in page.shortfalls:
        what = sf.dim_id or "page size"
        lines.append(f"  SHORTFALL ({sf.kind.value}): {what} missed by {sf.amount:.2f} items")
    if page.used_fallback:
        lines.append("  (solver gave no usable page: greedy fallback)")
    if page.hit_time_limit:
        lines.append("  (a solver stage hit its time limit: this page may be suboptimal)")
    return "\n".join(lines)


def render_sweep(pages: Sequence[tuple[float, Page]], page_size: int) -> str:
    lines = [
        "=== sweep " + "=" * 60,
        f"  {'s':>5}  {'edu':>5}  {'light':>5}  {'pure_edu':>8}  {'pure_lgt':>8}  {'mean p':>6}  {'steered':>7}  shortfall",
    ]
    for s, page in pages:
        sh = _shares(page, page_size)
        lines.append(
            f"  {s:+5.2f}  {sh['edu']:5.2f}  {sh['light']:5.2f}  {sh['pure_edu']:8.2f}  {sh['pure_light']:8.2f}"
            f"  {sh['relevance']:6.2f}  {len(page.steered_ids):7d}  {'yes' if page.shortfalls else '-'}"
        )
    lines.append("  edu/light = expected total share; pure_* = share that is that kind and not the other.")
    lines.append("  Moving right raises edu (lower bound) and lowers pure light (upper bound); left mirrors it.")
    return "\n".join(lines)


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--slider", type=float, action="append", help="slider value(s) in [-1, 1] to show pages for")
    parser.add_argument("--seed", type=int, default=0, help="synthetic catalog seed")
    parser.add_argument("--pool-size", type=int, default=300, help="number of candidate items")
    parser.add_argument("--page-size", type=int, default=10)
    parser.add_argument("--delta", type=float, default=0.02, help="stage-2 relevance tolerance (plan: 0.02)")
    parser.add_argument("--sweep-only", action="store_true", help="print only the sweep table")
    args = parser.parse_args(argv)

    catalog = make_catalog(n_items=args.pool_size, seed=args.seed)
    shown = args.slider if args.slider else [-1.0, 0.0, 0.5, 1.0]
    if not args.sweep_only:
        for s in shown:
            page = assemble(catalog.items, single_slider(s), DEFAULT_REGISTRY, args.page_size, delta=args.delta)
            print(render_page(s, page, catalog, args.page_size))
            print()
    sweep = [
        (k / 10, assemble(catalog.items, single_slider(k / 10), DEFAULT_REGISTRY, args.page_size, delta=args.delta))
        for k in range(-10, 11, 2)
    ]
    print(render_sweep(sweep, args.page_size))
    return 0


if __name__ == "__main__":
    sys.exit(main())
