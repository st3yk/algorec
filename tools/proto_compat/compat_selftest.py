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
    "syntax x.proto proto3",
    "service p.Svc",
    "rpc p.Svc Get p.Req p.Req client_stream=False server_stream=False",
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
    assert "p.Req was removed" in breaking_changes(BASE, current)


def test_removing_an_rpc_or_a_service_is_breaking():
    assert breaking_changes(BASE, [line for line in BASE if not line.startswith("rpc")]) == [
        "rpc p.Svc Get was removed"
    ]
    assert "p.Svc was removed" in breaking_changes(BASE, [line for line in BASE if "p.Svc" not in line])


def test_changing_an_rpc_signature_is_breaking():
    current = [line.replace("p.Req p.Req client_stream=False", "p.Req p.Kind client_stream=False") for line in BASE]
    assert breaking_changes(BASE, current) == [
        "rpc p.Svc Get changed: `Get p.Req p.Req client_stream=False server_stream=False` -> "
        "`Get p.Req p.Kind client_stream=False server_stream=False`"
    ]


def test_adding_an_rpc_is_compatible():
    assert breaking_changes(BASE, BASE + ["rpc p.Svc Put p.Req p.Req client_stream=False server_stream=False"]) == []


def test_moving_a_field_into_a_oneof_or_changing_its_json_name_is_breaking():
    field = "field p.Req 1 user_id optional TYPE_STRING"
    base = [line if line != field else field + " json=userId" for line in BASE]
    into_oneof = [line if line != field + " json=userId" else field + " json=userId oneof=who" for line in base]
    renamed = [line if line != field + " json=userId" else field + " json=uid" for line in base]
    assert breaking_changes(base, into_oneof + ["oneof p.Req who"]) != []
    assert breaking_changes(base, renamed) != []


def test_changing_the_syntax_is_breaking():
    current = [line.replace("syntax x.proto proto3", "syntax x.proto proto2") for line in BASE]
    assert breaking_changes(BASE, current) == ["syntax x.proto changed: `proto3` -> `proto2`"]


def test_describe_flattens_nested_types_maps_and_reservations():
    fds = descriptor_pb2.FileDescriptorSet()
    f = fds.file.add(name="x.proto", package="p", syntax="proto3")
    msg = f.message_type.add(name="M")
    msg.field.add(name="a", number=1, type=descriptor_pb2.FieldDescriptorProto.TYPE_STRING, label=1, json_name="a")
    msg.oneof_decl.add(name="choice")
    msg.field.add(name="c", number=3, type=9, label=1, json_name="c", oneof_index=0)
    svc = f.service.add(name="S")
    svc.method.add(name="Get", input_type=".p.M", output_type=".p.M.N", server_streaming=True)
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
            "syntax x.proto proto3",
            "service p.S",
            "rpc p.S Get p.M p.M.N client_stream=False server_stream=True",
            "message p.M",
            "oneof p.M choice",
            "field p.M 1 a optional TYPE_STRING json=a",
            "field p.M 3 c optional TYPE_STRING json=c oneof=choice",
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
