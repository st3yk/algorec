"""Dimension registry (plan Step 8), reduced to what steering needs.

Adding a dimension means adding a registry entry (plus, in the full system, a
rubric, gold labels and a scoring head). Everything downstream iterates over it.
"""

import math
from dataclasses import dataclass
from typing import Iterable, Mapping


@dataclass(frozen=True)
class Dimension:
    """Steering parameters for one content dimension.

    Attributes:
        dim_id: Stable key, used in the control map and in Item.q.
        t_max: How high the slider may push the expected share when this
            dimension is pushed up (plan Step 8; starting guess 0.6).
        t_min: How low the slider may push the exclusive share when this
            dimension is pushed down (starting guess 0.1).
        priority: Weight of this dimension's slack in stage 0 (>= 1).
        tau: "Strongly d" threshold, used only for display labels.
    """

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
    """An ordered, immutable set of dimensions keyed by id."""

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
        """Clamp each slider to [-1, 1]; reject unknown dimensions and NaN (plan Step 21)."""
        unknown = set(control) - set(self._dims)
        if unknown:
            raise ValueError(f"unknown dimension(s) in control: {sorted(unknown)}")
        out = {}
        for dim_id, s in control.items():
            # bool is an int subclass, and float("0.5") would accept strings: reject both.
            if isinstance(s, bool) or not isinstance(s, (int, float)):
                raise ValueError(f"control[{dim_id}] must be a number, got {s!r}")
            s = float(s)
            if math.isnan(s):  # max/min would silently turn NaN into +1 ("maximum learning")
                raise ValueError(f"control[{dim_id}] is NaN")
            out[dim_id] = max(-1.0, min(1.0, s))
        return out

    def check_scores(self, q: Mapping[str, float]) -> None:
        """Reject score keys the registry doesn't know: a typo would silently read as q = 0."""
        unknown = set(q) - set(self._dims)
        if unknown:
            raise ValueError(f"unknown dimension(s) in item scores: {sorted(unknown)}")


EDUCATIONAL = "educational"
LIGHT = "light_entertainment"

DEFAULT_REGISTRY = Registry([Dimension(EDUCATIONAL), Dimension(LIGHT)])


def single_slider(s: float) -> dict[str, float]:
    """The PoC's one "Fun <-> Learn" slider: s_edu = s, s_light = -s (plan Step 14)."""
    return {EDUCATIONAL: s, LIGHT: -s}
