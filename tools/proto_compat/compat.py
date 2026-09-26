"""Flattens a proto descriptor set into one line per wire-relevant fact. See docs/guardrails.md."""

from google.protobuf import descriptor_pb2

LABELS = {1: "optional", 2: "required", 3: "repeated"}


def describe(fds: descriptor_pb2.FileDescriptorSet) -> list[str]:
    lines: list[str] = []
    for f in fds.file:
        prefix = f.package
        lines.append(f"syntax {f.name} {f.syntax or 'proto2'}{' edition=' + str(f.edition) if f.edition else ''}")
        for svc in f.service:
            name = f"{prefix}.{svc.name}"
            lines.append(f"service {name}")
            for m in svc.method:
                streams = f"client_stream={m.client_streaming} server_stream={m.server_streaming}"
                lines.append(f"rpc {name} {m.name} {m.input_type.lstrip('.')} {m.output_type.lstrip('.')} {streams}")
        for msg in f.message_type:
            _message(lines, prefix, msg)
        for enum in f.enum_type:
            _enum(lines, prefix, enum)
    return sorted(set(lines))


def _message(lines: list[str], prefix: str, msg: descriptor_pb2.DescriptorProto) -> None:
    name = f"{prefix}.{msg.name}"
    lines.append(f"message {name}")
    for oneof in msg.oneof_decl:
        lines.append(f"oneof {name} {oneof.name}")
    for fd in msg.field:
        label = "proto3_optional" if fd.proto3_optional else LABELS[fd.label]
        kind = fd.type_name.lstrip(".") or descriptor_pb2.FieldDescriptorProto.Type.Name(fd.type)
        extra = f" json={fd.json_name}" if fd.json_name else ""
        if fd.HasField("oneof_index") and not fd.proto3_optional:
            extra += f" oneof={msg.oneof_decl[fd.oneof_index].name}"
        lines.append(f"field {name} {fd.number} {fd.name} {label} {kind}{extra}")
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
