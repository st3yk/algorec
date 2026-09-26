"""Candidate items as the page assembler sees them: relevance p and per-dimension
calibrated scores q.

See docs/code/items-and-registry.md.
"""

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType


@dataclass(frozen=True)
class Item:
    video_id: str
    creator_id: str
    p: float
    q: Mapping[str, float] = field(default_factory=dict, hash=False)

    def __post_init__(self) -> None:
        object.__setattr__(self, "q", MappingProxyType(dict(self.q)))
        if not 0.0 <= self.p <= 1.0:
            raise ValueError(f"{self.video_id}: p={self.p} is not a probability")
        for dim_id, value in self.q.items():
            if not 0.0 <= value <= 1.0:
                raise ValueError(f"{self.video_id}: q[{dim_id}]={value} is not a probability")

    def q_of(self, dim_id: str) -> float:
        return self.q.get(dim_id, 0.0)
