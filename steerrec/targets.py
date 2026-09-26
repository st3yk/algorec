"""The neutral page U0 and the one-sided steering bounds derived from the control.

See docs/concepts.md and docs/code/targets.md.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Mapping, Sequence

from steerrec.items import Item
from steerrec.registry import Registry


def dedupe_pool(pool: Sequence[Item]) -> list[Item]:
    seen: dict[str, Item] = {}
    for item in pool:
        prev = seen.get(item.video_id)
        if prev is None:
            seen[item.video_id] = item
        elif prev != item:
            raise ValueError(f"video {item.video_id} appears twice with different data: {prev} vs {item}")
    return list(seen.values())


def unsteered_page(pool: Sequence[Item], page_size: int) -> list[Item]:
    if page_size < 0:
        raise ValueError("page_size must be >= 0")
    page: list[Item] = []
    creators: set[str] = set()
    for item in sorted(dedupe_pool(pool), key=lambda it: (-it.p, it.video_id)):
        if len(page) == page_size:
            break
        if item.creator_id in creators:
            continue
        page.append(item)
        creators.add(item.creator_id)
    return page


def exclusive_mass(item: Item, dim_id: str, pushed_up: Sequence[str]) -> float:
    mass = item.q_of(dim_id)
    for k in pushed_up:
        if k != dim_id:
            mass *= 1.0 - item.q_of(k)
    return mass


def total_share(items: Sequence[Item], dim_id: str, page_size: int) -> float:
    return sum(it.q_of(dim_id) for it in items) / page_size


def exclusive_share(items: Sequence[Item], dim_id: str, pushed_up: Sequence[str], page_size: int) -> float:
    return sum(exclusive_mass(it, dim_id, pushed_up) for it in items) / page_size


class BoundKind(Enum):
    LOWER_TOTAL = "lower_total"
    UPPER_EXCLUSIVE = "upper_exclusive"


@dataclass(frozen=True)
class Bound:
    dim_id: str
    kind: BoundKind
    target: float
    reference: float
    pushed_up: tuple[str, ...]
    page_size: int

    @property
    def mass(self) -> float:
        return self.target * self.page_size

    def coefficient(self, item: Item) -> float:
        if self.kind is BoundKind.LOWER_TOTAL:
            return item.q_of(self.dim_id)
        return exclusive_mass(item, self.dim_id, self.pushed_up)

    def realized(self, items: Sequence[Item]) -> float:
        return sum(self.coefficient(it) for it in items) / self.page_size


def compute_bounds(
    control: Mapping[str, float],
    u0: Sequence[Item],
    registry: Registry,
    page_size: int,
) -> list[Bound]:
    if type(page_size) is not int or page_size <= 0:
        raise ValueError(f"page_size must be a positive int, got {page_size!r}")
    if len(u0) > page_size:
        raise ValueError(f"u0 has {len(u0)} items but page_size is {page_size}")
    if len({it.video_id for it in u0}) < len(u0) or len({it.creator_id for it in u0}) < len(u0):
        raise ValueError("u0 repeats a video or a creator; build it with unsteered_page()")
    for item in u0:
        registry.check_scores(item.q)
    control = registry.validate_control(control)
    ordered = [(dim.dim_id, control[dim.dim_id]) for dim in registry if dim.dim_id in control]
    pushed_up = tuple(d for d, s in ordered if s > 0)
    bounds: list[Bound] = []
    for dim_id, s in ordered:
        if s == 0:
            continue
        dim = registry[dim_id]
        if s > 0:
            u = total_share(u0, dim_id, page_size)
            t_hi = max(dim.t_max, u)
            bounds.append(Bound(dim_id, BoundKind.LOWER_TOTAL, u + s * (t_hi - u), u, pushed_up, page_size))
        else:
            ubar = exclusive_share(u0, dim_id, pushed_up, page_size)
            t_lo = min(dim.t_min, ubar)
            bounds.append(Bound(dim_id, BoundKind.UPPER_EXCLUSIVE, ubar - (-s) * (ubar - t_lo), ubar, pushed_up, page_size))
    return bounds
