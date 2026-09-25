"""A seeded, synthetic candidate pool: the stand-in for real videos.

In the full system each video's q comes from the calibrated scoring heads
(plan Steps 5-7) and p from the ranker (Step 12). Here every item gets a hidden
"kind" and its q/p are drawn from distributions that depend on that kind, so the
demo has something human-readable to show without any video processing.

The relevance model is deliberately biased toward light content, the way an
engagement-trained ranker tends to be. That is what makes the unsteered feed
skew toward "brain-rot" and gives the slider something to do.
"""

import random
from dataclasses import dataclass
from enum import Enum

from steerrec.items import Item
from steerrec.registry import EDUCATIONAL, LIGHT


class Kind(Enum):
    EDUCATIONAL = "edu"
    LIGHT = "light"
    EDUTAINMENT = "both"
    NEITHER = "neither"


# Share of each kind in the catalog, and the Beta(a, b) parameters for
# (q_educational, q_light, relevance p) of that kind.
_MIX = {
    Kind.LIGHT: 0.45,
    Kind.EDUCATIONAL: 0.25,
    Kind.NEITHER: 0.20,
    Kind.EDUTAINMENT: 0.10,
}
_PARAMS = {
    Kind.LIGHT: ((1.2, 8.0), (8.0, 1.5), (5.0, 3.0)),
    Kind.EDUCATIONAL: ((8.0, 1.5), (1.2, 8.0), (3.0, 5.0)),
    Kind.EDUTAINMENT: ((6.0, 2.0), (6.0, 2.0), (4.5, 3.5)),
    Kind.NEITHER: ((1.5, 8.0), (1.5, 8.0), (3.5, 4.5)),
}
_TOPICS = ["space", "cooking", "history", "cats", "football", "chemistry", "music", "coding", "travel", "finance"]
_TITLE_FORMATS = {
    Kind.LIGHT: ["{t} fails compilation #{n}", "POV: {t} but it's chaotic", "{t} meme remix {n}"],
    Kind.EDUCATIONAL: ["How {t} actually works, part {n}", "{t} explained in 60 seconds", "3 facts about {t} ({n})"],
    Kind.EDUTAINMENT: ["{t} myths, busted with a laugh ({n})", "Wild {t} science you won't forget #{n}"],
    Kind.NEITHER: ["My {t} day, vlog {n}", "{t} highlights, clip {n}"],
}


@dataclass(frozen=True)
class Catalog:
    items: list[Item]
    titles: dict[str, str]   # video_id -> human-readable title
    kinds: dict[str, Kind]   # video_id -> hidden ground-truth kind (for display only)


def make_catalog(n_items: int = 300, n_creators: int = 120, seed: int = 0) -> Catalog:
    """Deterministic for a given (n_items, n_creators, seed)."""
    if n_items < 0 or n_creators <= 0:
        raise ValueError("need n_items >= 0 and n_creators > 0")
    rng = random.Random(seed)
    kinds_in_order = list(_MIX)
    weights = [_MIX[k] for k in kinds_in_order]
    items, titles, kinds = [], {}, {}
    for i in range(n_items):
        kind = rng.choices(kinds_in_order, weights)[0]
        (ea, eb), (la, lb), (pa, pb) = _PARAMS[kind]
        video_id = f"v{i:04d}"
        items.append(
            Item(
                video_id=video_id,
                creator_id=f"creator{rng.randrange(n_creators):03d}",
                p=rng.betavariate(pa, pb),
                q={EDUCATIONAL: rng.betavariate(ea, eb), LIGHT: rng.betavariate(la, lb)},
            )
        )
        fmt = rng.choice(_TITLE_FORMATS[kind])
        titles[video_id] = fmt.format(t=rng.choice(_TOPICS), n=rng.randrange(1, 100))
        kinds[video_id] = kind
    return Catalog(items=items, titles=titles, kinds=kinds)
