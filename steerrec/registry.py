"""Dimension registry: steering parameters per content dimension, control
validation, and the single Fun <-> Learn slider mapping.

See docs/code/items-and-registry.md.
"""

import math
import numbers
from collections.abc import Iterable, Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class Dimension:
    dim_id: str
    t_max: float = 0.6
    t_min: float = 0.1
    priority: float = 1.0
    tau: float = 0.6

    def __post_init__(self) -> None:
        if not 0.0 <= self.t_min <= self.t_max <= 1.0:
            raise ValueError(f"{self.dim_id}: need 0 <= t_min <= t_max <= 1")
        if not (math.isfinite(self.priority) and self.priority >= 1.0):
            raise ValueError(f"{self.dim_id}: priority must be finite and >= 1 (it weights stage-0 slack)")
        if not 0.0 <= self.tau <= 1.0:
            raise ValueError(f"{self.dim_id}: tau must be in [0, 1]")


class Registry:
    def __init__(self, dimensions: Iterable[Dimension]):
        self._dims: dict[str, Dimension] = {}
        for d in dimensions:
            if d.dim_id in self._dims:
                raise ValueError(f"duplicate dimension id: {d.dim_id}")
            self._dims[d.dim_id] = d
        if not self._dims:
            raise ValueError("registry needs at least one dimension")

    def __getitem__(self, dim_id: str) -> Dimension:
        return self._dims[dim_id]

    def __contains__(self, dim_id: str) -> bool:
        return dim_id in self._dims

    def __iter__(self):
        return iter(self._dims.values())

    def validate_control(self, control: Mapping[str, float]) -> dict[str, float]:
        unknown = set(control) - set(self._dims)
        if unknown:
            raise ValueError(f"unknown dimension(s) in control: {sorted(unknown)}")
        out = {}
        for dim_id, s in control.items():
            if isinstance(s, bool) or not isinstance(s, numbers.Real):
                raise ValueError(f"control[{dim_id}] must be a number, got {s!r}")
            s = float(s)
            if math.isnan(s):
                raise ValueError(f"control[{dim_id}] is NaN")
            out[dim_id] = max(-1.0, min(1.0, s))
        return out

    def check_scores(self, q: Mapping[str, float]) -> None:
        unknown = set(q) - set(self._dims)
        if unknown:
            raise ValueError(f"unknown dimension(s) in item scores: {sorted(unknown)}")


EDUCATIONAL = "educational"
LIGHT = "light_entertainment"

DEFAULT_REGISTRY = Registry([Dimension(EDUCATIONAL), Dimension(LIGHT)])


def single_slider(s: float) -> dict[str, float]:
    return {EDUCATIONAL: s, LIGHT: -s}
