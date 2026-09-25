"""Candidate items as the page assembler sees them.

In the full system, `p` comes from the ranker (plan Step 12) and `q` from the
calibrated dimension heads (plan Step 7). In this slice they are given directly.
"""

from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Mapping


@dataclass(frozen=True)
class Item:
    """One candidate video.

    Attributes:
        video_id: Unique id; also the deterministic tie-breaker.
        creator_id: At most one item per creator is placed on a page.
        p: Calibrated probability that the user engages (relevance).
        q: Per-dimension calibrated probability that a random annotator rates
           the item >= 3 on that dimension's rubric (plan Step 7), e.g.
           {"educational": 0.8, "light_entertainment": 0.3}.
    """

    video_id: str
    creator_id: str
    p: float
    q: Mapping[str, float] = field(default_factory=dict, hash=False)

    def __post_init__(self) -> None:
        # Read-only copy, so scores can't change after validation.
        object.__setattr__(self, "q", MappingProxyType(dict(self.q)))
        if not 0.0 <= self.p <= 1.0:
            raise ValueError(f"{self.video_id}: p={self.p} is not a probability")
        for dim_id, value in self.q.items():
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{self.video_id}: q[{dim_id}]={value} is not a probability")

    def q_of(self, dim_id: str) -> float:
        """q for a dimension; an item without a score counts as 0 (not that kind)."""
        return self.q.get(dim_id, 0.0)
