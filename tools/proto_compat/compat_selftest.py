"""Self-tests for the proto compatibility check. See docs/guardrails.md."""

import pytest
from google.protobuf import descriptor_pb2

from tools.proto_compat.compat import breaking_changes, describe, parse, read_listing

BASE = [
    "message p.Req",
    "field p.Req 1 user_id optional TYPE_STRING",
    "field p.Req 2 size optional TYPE_UINT32",
    "reserved p.Req 5 6",
    "reserved_name p.Req old_name",
    "enum p.Kind",
    "value p.Kind 0 KIND_UNSPECIFIED",
    "value p.Kind 1 A",
]


def without(*drop: str) -> list[str]:
    return [line for line in BASE if line not in drop]


def test_identical_listings_are_compatible():
    assert breaking_changes(BASE, BASE) == []


def test_adding_a_field_or_value_is_compatible():
    assert breaking_changes(BASE, BASE + ["field p.Req 3 extra repeated TYPE_STRING", "value p.Kind 2 B"]) == []


def test_renumbering_a_field_is_breaking():
    current = without("field p.Req 2 size optional TYPE_UINT32") + ["field p.Req 3 size optional TYPE_UINT32"]
    assert breaking_changes(BASE, current) == ["p.Req 2 (size) moved to number 3"]


def test_removing_a_field_without_reserving_is_breaking():
    assert breaking_changes(BASE, without("field p.Req 2 size optional TYPE_UINT32")) == [
        "p.Req 2 (size) was removed without `reserved`"
    ]


def test_removing_a_field_and_reserving_its_number_is_compatible():
    current = without("field p.Req 2 size optional TYPE_UINT32") + ["reserved p.Req 2 2"]
    assert breaking_changes(BASE, current) == []


def test_reusing_a_reserved_number_is_breaking():
    current = without("reserved p.Req 5 6") + ["field p.Req 5 x optional TYPE_STRING", "reserved p.Req 6 6"]
    assert breaking_changes(BASE, current) == [
        "p.Req 5 (x) reuses a reserved number",
        "p.Req reservation 5-6 was dropped",
    ]


def test_reusing_a_reserved_name_is_breaking():
    current = BASE + ["field p.Req 9 old_name optional TYPE_STRING"]
    assert breaking_changes(BASE, current) == ["p.Req 9 reuses the reserved name old_name"]


def test_changing_type_label_or_name_is_breaking():
    current = without("field p.Req 1 user_id optional TYPE_STRING") + ["field p.Req 1 user_id repeated TYPE_STRING"]
    assert breaking_changes(BASE, current) == [
        "p.Req 1 changed: `field user_id optional TYPE_STRING` -> `field user_id repeated TYPE_STRING`"
    ]


def test_renumbering_an_enum_value_is_breaking():
    current = without("value p.Kind 1 A") + ["value p.Kind 2 A"]
    assert breaking_changes(BASE, current) == ["p.Kind 1 (A) moved to number 2"]


def test_removing_a_message_is_breaking():
    current = [line for line in BASE if "p.Req" not in line]
    assert breaking_changes(BASE, current) == ["p.Req was removed"]


def test_describe_flattens_nested_types_maps_and_reservations():
    fds = descriptor_pb2.FileDescriptorSet()
    f = fds.file.add(name="x.proto", package="p", syntax="proto3")
    msg = f.message_type.add(name="M")
    msg.field.add(name="a", number=1, type=descriptor_pb2.FieldDescriptorProto.TYPE_STRING, label=1)
    msg.field.add(
        name="b", number=2, type=descriptor_pb2.FieldDescriptorProto.TYPE_MESSAGE, label=3, type_name=".p.M.N"
    )
    msg.reserved_range.add(start=4, end=6)
    msg.reserved_name.append("gone")
    msg.nested_type.add(name="N")
    enum = msg.enum_type.add(name="E")
    enum.value.add(name="E_UNSPECIFIED", number=0)
    enum.reserved_range.add(start=3, end=3)
    assert describe(fds) == sorted(
        [
            "message p.M",
            "field p.M 1 a optional TYPE_STRING",
            "field p.M 2 b repeated p.M.N",
            "reserved p.M 4 5",
            "reserved_name p.M gone",
            "message p.M.N",
            "enum p.M.E",
            "value p.M.E 0 E_UNSPECIFIED",
            "reserved p.M.E 3 3",
        ]
    )


def test_read_listing_skips_comments_and_blank_lines():
    assert read_listing("// header\n\nmessage p.M\n") == ["message p.M"]


def test_unknown_lines_are_rejected():
    with pytest.raises(ValueError):
        parse(["weird p.M"])


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
