#!/usr/bin/env python
"""Provision a mock DS + 26 tags (13 types x read/write) on TPT platform.

Reads ua_mocker/ua2_full_types.yaml (port 18980, ns=2) and registers:
- One DS pointing at opc.tcp://<localIp>:18980/ua_mocker/
- 26 tags: 13 data types x {read-only, writable}

Idempotent: if DS / tag already exists, reuses it (Duplicate treated as success).
"""
from __future__ import annotations

import json
import os
import sys
import time

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, os.path.join(REPO_ROOT, "tpt_api", "python"))

from tpt_api.client import AlgAPI
from tpt_api import datahub
from tpt_api.types import DataTypes

with open(os.path.join(REPO_ROOT, "env.json"), encoding="utf-8") as f:
    env = json.load(f)

DS_NAME = "tpt_rw_gui_mock_ds"
DS_URL = f"opc.tcp://{env['localIp']}:18980/ua_mocker/"
NS = 2  # namespace_index from ua2_full_types.yaml

TYPE_MAP: dict[str, int] = {
    "boolean": DataTypes["BOOLEAN"],
    "sbyte": DataTypes["S_BYTE"],
    "byte": DataTypes["BYTE"],
    "int16": DataTypes["SHORT"],
    "uint16": DataTypes["U_SHORT"],
    "int32": DataTypes["INT"],
    "uint32": DataTypes["U_INT"],
    "int64": DataTypes["LONG"],
    "uint64": DataTypes["U_LONG"],
    "float": DataTypes["FLOAT"],
    "double": DataTypes["DOUBLE"],
    "string": DataTypes["STRING"],
    "datetime": DataTypes["DATE_TIME"],
}

VARIANTS = [("_r_1", True), ("_w_1", False)]


def main() -> int:
    api = AlgAPI(env["baseUrl"])
    api.login(env["username"], env["password"], env.get("tenantId", ""))
    print("[Login] OK")

    ds_list = datahub.list_ds_info(api)
    existing = [d for d in ds_list.get("records", []) if d.get("dsTarUrl") == DS_URL]
    if existing:
        ds = existing[0]
        ds_id = ds["id"]
        print(f"[DS] already exists id={ds_id} dsName={ds.get('dsName')} alive={ds.get('alive')}")
    else:
        result = datahub.add_ds_info(api, ds_name=DS_NAME, ds_tar_url=DS_URL)
        ds_id = result["id"]
        print(f"[DS] created id={ds_id} dsName={DS_NAME}")

    datahub.change_ds_state(api, ds_id, True)
    print(f"[DS] state=enabled")

    alive = False
    for i in range(30):
        ds_list = datahub.list_ds_info(api)
        ds_now = next((d for d in ds_list.get("records", []) if d.get("id") == ds_id), None)
        if ds_now and ds_now.get("alive"):
            alive = True
            print(f"[DS] alive=true (after {(i + 1) * 2}s)")
            break
        time.sleep(2)
    if not alive:
        print("[DS] WARNING: not alive after 60s, continue anyway")

    ok, fail = 0, 0
    duplicates = 0
    for type_name, type_code in TYPE_MAP.items():
        for suffix, only_read in VARIANTS:
            tag_name = f"{NS}_ua2ft_{type_name}{suffix}"
            try:
                datahub.add_tag(
                    api,
                    tag_name=tag_name,
                    data_type=type_code,
                    tag_type=1,
                    ds_id=ds_id,
                    group_id="0",
                    unit="",
                    only_read=only_read,
                    frequency=10,
                    need_push=True,
                    tag_desc=f"{'read-only' if only_read else 'writable'} {type_name}",
                    is_vector=True,
                    tag_base_name=tag_name,
                )
                ok += 1
                print(f"  + {tag_name} ({type_name}, onlyRead={only_read})")
            except Exception as e:
                msg = str(e)
                if "Duplicate" in msg or "\u5df2\u5b58\u5728" in msg or "A0001" in msg:
                    duplicates += 1
                    print(f"  = {tag_name} already exists")
                else:
                    fail += 1
                    print(f"  ! {tag_name} FAILED: {e}")

    total = ok + duplicates + fail
    print(f"\n[Tags] total={total} created={ok} already={duplicates} failed={fail}")
    print(f"\nDone. DS id={ds_id} url={DS_URL}")
    print(f"Use data source '{DS_NAME}' (id={ds_id}) in the GUI.")
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())