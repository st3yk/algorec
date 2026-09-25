"""Neutral reference page and one-sided steering targets (plan Steps 13-14).

The key idea: the slider never sets an absolute mix. It says "more of d than
you'd get unsteered" (a lower bound on d's total share) or "less *pure* d than
you'd get unsteered" (an upper bound on d's exclusive share), measured against
this request's own unsteered page U0. So a steered page can never move against
the slider relative to neutral.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Mapping, Sequence

from steerrec.items import Item
from steerrec.registry import Registry


def unsteered_page(pool: Sequence[Item], page_size: int) -> list[Item]:
    """U0: the top-`page_size` items by relevance, at most one per creator (Step 13).

    Greedy is exact here: taking the best item of each creator and then the
    top-P of those is the same as scanning by descending p and skipping repeats.
    Ties are broken by video_id so the result is deterministic.
    """
    if page_size < 0:
        raise ValueError("page_size must be >= 0")
    page: list[Item] = []
    creators: set[str] = set()
    for item in sorted(pool, key=lambda it: (-it.p, it.video_id)):
        if len(page) == page_size:
            break
        if item.creator_id in creators:
            continue
        page.append(item)
        creators.add(item.creator_id)
    return page


def exclusive_mass(item: Item, dim_id: str, pushed_up: Sequence[str]) -> float:
    """e_d = q_d * prod over pushed-up k of (1 - q_k): "d and not a pushed-up kind".

    This is what a pushed-down bound counts, so an item that is both fun and
    educational is not suppressed when the user asks for more learning
    (plan Step 14's product decision). Assumes conditional independence of the
    dimensions; see plan "Known Risks".
    """
    mass = item.q_of(dim_id)
    for k in pushed_up:
        if k != dim_id:
            mass *= 1.0 - item.q_of(k)
    return mass


def total_share(items: Sequence[Item], dim_id: str, page_size: int) -> float:
    """m_d = (1/P) * sum of q_d: the expected human-judged share of d on a page."""
    return sum(it.q_of(dim_id) for it in items) / page_size


def exclusive_share(items: Sequence[Item], dim_id: str, pushed_up: Sequence[str], page_size: int) -> float:
    """x_d = (1/P) * sum of e_d: the expected share of "pure" d on a page."""
    return sum(exclusive_mass(it, dim_id, pushed_up) for it in items) / page_size


class BoundKind(Enum):
    LOWER_TOTAL = "lower_total"          # pushed up:   sum_i x_i q_d,i  >= t * P
    UPPER_EXCLUSIVE = "upper_exclusive"  # pushed down: sum_i x_i e_d,i  <= t * P


@dataclass(frozen=True)
class Bound:
    """One per-page constraint derived from the control.

    `coefficient(item)` is the item's contribution to the constrained sum, and
    `mass` (= target * page_size) is the right-hand side.
    """

    dim_id: str
    kind: BoundKind
    target: float       # t_d, as a share of the page
    reference: float    # u_d (total) or u-bar_d (exclusive) of U0
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
        """The page's share in this bound's units (m_d or x_d)."""
        return sum(self.coefficient(it) for it in items) / self.page_size


def compute_bounds(
    control: Mapping[str, float],
    u0: Sequence[Item],
    registry: Registry,
    page_size: int,
) -> list[Bound]:
    """Turn slider values into one-sided bounds relative to U0 (plan Step 14).

    For a pushed-up dimension d (s_d > 0):
        t_d = u_d + |s_d| * (max(T_max, u_d) - u_d)            lower bound on total share
    For a pushed-down dimension d (s_d < 0):
        t_d = ubar_d - |s_d| * (ubar_d - min(T_min, ubar_d))   upper bound on exclusive share
    Dimensions at 0 are unconstrained, so s = 0 everywhere returns no bounds.
    """
    if page_size <= 0:
        raise ValueError("page_size must be > 0")
    control = registry.validate_control(control)
    pushed_up = tuple(d for d, s in control.items() if s > 0)
    bounds: list[Bound] = []
    for dim_id, s in control.items():
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
