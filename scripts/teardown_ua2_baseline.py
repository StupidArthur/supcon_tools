"""Explicit teardown of UA-2 shared baseline datasources.

The normal automation runner NEVER calls this script. It exists so an operator
can tear down the two shared datasources (`ua_shared_ua2_types_ds`,
`ua_shared_ua2_empty_ds`) explicitly when needed. Requires
`--confirm-delete-shared` to acknowledge the destructive nature.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--confirm-delete-shared", action="store_true",
                        help="Required acknowledgment to delete shared baseline DS.")
    parser.add_argument("--result", default="-",
                        help="Path to write JSON result, or '-' for stdout.")
    args = parser.parse_args()

    if not args.confirm_delete_shared:
        print("teardown_ua2_baseline requires --confirm-delete-shared", file=sys.stderr)
        return 2

    # Ensure repo root is importable so ua_test_harness.* resolves.
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

    from unittest.mock import MagicMock
    from ua_test_harness.config import RunConfig
    from ua_test_harness.context import RunContext
    from ua_test_harness.provisioning import teardown_ua2_baseline

    cfg = RunConfig()
    cfg.local_ip = os.environ.get("UA_LOCAL_IP", "127.0.0.1")
    cfg.mock.endpoints.functional = os.environ.get(
        "DATAHUB_BASE_MOCK", f"opc.tcp://{cfg.local_ip}:18965/ua_mocker/"
    )
    cfg.subject.base_url = os.environ.get("DATAHUB_BASE_URL", "")
    cfg.subject.username = os.environ.get("DATAHUB_USER", "admin")
    cfg.subject.password = os.environ.get("DATAHUB_PASSWORD", "")
    cfg.subject.tenant_id = os.environ.get("DATAHUB_TENANT_ID", "")

    ctx = RunContext(config=cfg, emitter=MagicMock())
    result = teardown_ua2_baseline(ctx, confirm=True)

    out = json.dumps(result, ensure_ascii=False, indent=2)
    if args.result == "-":
        print(out)
    else:
        out_path = Path(args.result)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(out, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())