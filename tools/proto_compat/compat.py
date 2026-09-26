"""Flattens a proto descriptor set into one line per wire-relevant fact, and finds
breaking changes between two such listings. See docs/guardrails.md."""

import re
from collections.abc import Iterable
from dataclasses import dataclass, field

from google.protobuf import descriptor_pb2

LABELS = {1: "optional", 2: "required", 3: "repeated"}


def describe(fds: descriptor_pb2.FileDescriptorSet) -> list[str]:
    lines: list[str] = []
    for f in fds.file:
        prefix = f.package
        for msg in f.message_type:
            _message(lines, prefix, msg)
        for enum in f.enum_type:
            _enum(lines, prefix, enum)
    return sorted(set(lines))


def _message(lines: list[str], prefix: str, msg: descriptor_pb2.DescriptorProto) -> None:
    name = f"{prefix}.{msg.name}"
    lines.append(f"message {name}")
    for fd in msg.field:
        label = "proto3_optional" if fd.proto3_optional else LABELS[fd.label]
        kind = fd.type_name.lstrip(".") or descriptor_pb2.FieldDescriptorProto.Type.Name(fd.type)
        lines.append(f"field {name} {fd.number} {fd.name} {label} {kind}")
    for r in msg.reserved_range:
        lines.append(f"reserved {name} {r.start} {r.end - 1}")
    for rn in msg.reserved_name:
        lines.append(f"reserved_name {name} {rn}")
    for nested in msg.nested_type:
        _message(lines, name, nested)
    for enum in msg.enum_type:
        _enum(lines, name, enum)


def _enum(lines: list[str], prefix: str, enum: descriptor_pb2.EnumDescriptorProto) -> None:
    name = f"{prefix}.{enum.name}"
    lines.append(f"enum {name}")
    for v in enum.value:
        lines.append(f"value {name} {v.number} {v.name}")
    for r in enum.reserved_range:
        lines.append(f"reserved {name} {r.start} {r.end}")
    for rn in enum.reserved_name:
        lines.append(f"reserved_name {name} {rn}")


@dataclass
class Listing:
    types: set[str] = field(default_factory=set)
    members: dict[tuple[str, int], str] = field(default_factory=dict)
    reserved: dict[str, list[tuple[int, int]]] = field(default_factory=dict)
    reserved_names: dict[str, set[str]] = field(default_factory=dict)

    def is_reserved(self, owner: str, number: int) -> bool:
        return any(lo <= number <= hi for lo, hi in self.reserved.get(owner, []))


def parse(lines: Iterable[str]) -> Listing:
    out = Listing()
    for line in lines:
        line = line.strip()
        if not line:
            continue
        kind, owner, *rest = line.split(" ")
        if kind in ("message", "enum"):
            out.types.add(owner)
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
    for owner, ranges in sorted(old.reserved.items()):
        for lo, hi in ranges:
            if owner in new.types and not all(new.is_reserved(owner, n) for n in range(lo, hi + 1)):
                out.append(f"{owner} reservation {lo}-{hi} was dropped")
    return out


def read_listing(text: str) -> list[str]:
    return [line for line in text.splitlines() if line.strip() and not re.match(r"\s*//", line)]
