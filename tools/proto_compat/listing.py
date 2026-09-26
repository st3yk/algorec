"""The flattened contract listing and its breaking-change rules, stdlib only so the verify
judge can use it without protobuf. See docs/guardrails.md."""

import re
from collections.abc import Iterable
from dataclasses import dataclass, field


@dataclass
class Listing:
    types: set[str] = field(default_factory=set)
    members: dict[tuple[str, int], str] = field(default_factory=dict)
    reserved: dict[str, list[tuple[int, int]]] = field(default_factory=dict)
    reserved_names: dict[str, set[str]] = field(default_factory=dict)
    named: dict[tuple[str, str], str] = field(default_factory=dict)

    def is_reserved(self, owner: str, number: int) -> bool:
        return any(lo <= number <= hi for lo, hi in self.reserved.get(owner, []))


def parse(lines: Iterable[str]) -> Listing:
    out = Listing()
    for line in lines:
        line = line.strip()
        if not line:
            continue
        kind, owner, *rest = line.split(" ")
        if kind in ("message", "enum", "service"):
            out.types.add(owner)
        elif kind in ("rpc", "syntax", "oneof"):
            out.named[(kind, f"{owner} {rest[0]}" if rest and kind != "syntax" else owner)] = " ".join(rest)
        elif kind in ("field", "value"):
            out.members[(owner, int(rest[0]))] = " ".join([kind, *rest[1:]])
        elif kind == "reserved":
            out.reserved.setdefault(owner, []).append((int(rest[0]), int(rest[1])))
        elif kind == "reserved_name":
            out.reserved_names.setdefault(owner, set()).add(rest[0])
        else:
            raise ValueError(f"unknown listing line: {line!r}")
    return out


def breaking_changes(golden_lines: Iterable[str], current_lines: Iterable[str]) -> list[str]:
    old, new = parse(golden_lines), parse(current_lines)
    out = []
    for t in sorted(old.types - new.types):
        out.append(f"{t} was removed")
    for (owner, number), desc in sorted(old.members.items()):
        now = new.members.get((owner, number))
        if now is None:
            if owner in new.types and not new.is_reserved(owner, number):
                name = desc.split(" ")[1]
                moved = [n for (o, n), d in new.members.items() if o == owner and d.split(" ")[1] == name]
                why = f"moved to number {moved[0]}" if moved else "was removed without `reserved`"
                out.append(f"{owner} {number} ({name}) {why}")
        elif now != desc:
            out.append(f"{owner} {number} changed: `{desc}` -> `{now}`")
    for (owner, number), desc in sorted(new.members.items()):
        if (owner, number) not in old.members and old.is_reserved(owner, number):
            out.append(f"{owner} {number} ({desc.split(' ')[1]}) reuses a reserved number")
        if (owner, number) not in old.members and desc.split(" ")[1] in old.reserved_names.get(owner, set()):
            out.append(f"{owner} {number} reuses the reserved name {desc.split(' ')[1]}")
    for (kind, key), desc in sorted(old.named.items()):
        now = new.named.get((kind, key))
        if now is None and kind == "oneof":
            continue
        if now is None:
            out.append(f"{kind} {key} was removed")
        elif now != desc:
            out.append(f"{kind} {key} changed: `{desc}` -> `{now}`")
    for owner, ranges in sorted(old.reserved.items()):
        for lo, hi in ranges:
            if owner in new.types and not all(new.is_reserved(owner, n) for n in range(lo, hi + 1)):
                out.append(f"{owner} reservation {lo}-{hi} was dropped")
    return out


def read_listing(text: str) -> list[str]:
    return [line for line in text.splitlines() if line.strip() and not re.match(r"\s*//", line)]
