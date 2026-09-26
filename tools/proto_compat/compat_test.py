"""Fails when the service contract changes incompatibly, or when the golden listing is
stale. See docs/guardrails.md."""

import os
import sys

from google.protobuf import descriptor_pb2

from tools.proto_compat.compat import breaking_changes, describe, read_listing


def main(descriptor_path: str, golden_path: str) -> int:
    root = os.path.join(os.environ["TEST_SRCDIR"], "_main")
    fds = descriptor_pb2.FileDescriptorSet()
    with open(os.path.join(root, descriptor_path), "rb") as f:
        fds.ParseFromString(f.read())
    with open(os.path.join(root, golden_path), encoding="utf-8") as f:
        golden = read_listing(f.read())
    current = describe(fds)
    broken = breaking_changes(golden, current)
    if broken:
        print("Breaking change(s) to the service contract (AGENTS.md: never renumber or reuse):", file=sys.stderr)
        for b in broken:
            print(f"  - {b}", file=sys.stderr)
        return 1
    if sorted(set(golden)) != current:
        added = sorted(set(current) - set(golden))
        print("The contract changed compatibly, but the golden listing is stale:", file=sys.stderr)
        for a in added:
            print(f"  + {a}", file=sys.stderr)
        print("Update it with: bazel run //tools/proto_compat:update_golden", file=sys.stderr)
        return 1
    print(f"proto contract: {len(current)} facts match the golden listing")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1], sys.argv[2]))
