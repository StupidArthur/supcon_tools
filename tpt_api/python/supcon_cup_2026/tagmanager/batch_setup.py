"""批量给选手租户添加数据源 + 位号，并验证实时值。"""

from __future__ import annotations

import json
import sys
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from tpt_api import AlgAPI
from tpt_api import datahub as dh
from tpt_api.types import DataTypes, TagTypes

TAG_DEFS = [
    ("PRAC_LOAD.VALUE",  DataTypes["U_SHORT"], False),
    ("EXAM_LOAD.VALUE",  DataTypes["U_SHORT"], False),
    ("LOAD_RSP.VALUE",   DataTypes["U_SHORT"], False),
    ("FICQ_60101.PV",    DataTypes["FLOAT"],   True),
    ("FICQ_60101.SV",    DataTypes["FLOAT"],   False),
    ("FICQ_60101.MV",    DataTypes["FLOAT"],   True),
    ("FICQ_60401.PV",    DataTypes["FLOAT"],   True),
    ("FICQ_60401.SV",    DataTypes["FLOAT"],   False),
    ("FICQ_60401.MV",    DataTypes["FLOAT"],   True),
    ("FICQ_60402.PV",    DataTypes["FLOAT"],   True),
    ("FICQ_60402.SV",    DataTypes["FLOAT"],   False),
    ("FICQ_60402.MV",    DataTypes["FLOAT"],   True),
    ("LIC_60501.PV",     DataTypes["FLOAT"],   True),
    ("LIC_60501.SV",     DataTypes["FLOAT"],   True),
    ("LIC_60501.MV",     DataTypes["FLOAT"],   False),
    ("PICA_60402.PV",    DataTypes["FLOAT"],   True),
    ("PICA_60402.SV",    DataTypes["FLOAT"],   True),
    ("PICA_60402.MV",    DataTypes["FLOAT"],   True),
    ("FT60201.PV",       DataTypes["FLOAT"],   True),
    ("FT60501.PV",       DataTypes["FLOAT"],   True),
    ("LT60401.PV",       DataTypes["FLOAT"],   True),
    ("TE60401.PV",       DataTypes["FLOAT"],   True),
    ("TE60402.PV",       DataTypes["FLOAT"],   True),
    ("TE60403.PV",       DataTypes["FLOAT"],   True),
    ("TE60404.PV",       DataTypes["FLOAT"],   True),
    ("TE60405.PV",       DataTypes["FLOAT"],   True),
    ("TE60406.PV",       DataTypes["FLOAT"],   True),
    ("TE60407.PV",       DataTypes["FLOAT"],   True),
    ("TE60408.PV",       DataTypes["FLOAT"],   True),
    ("TE60410.PV",       DataTypes["FLOAT"],   True),
    ("T602D.VALUE",      DataTypes["FLOAT"],   True),
    ("T602RR.VALUE",     DataTypes["FLOAT"],   True),
    ("T604D.PV",         DataTypes["FLOAT"],   True),
]

BASE_URL = "https://tpt.supcon.com"
ADMIN_USER = "admin"
ADMIN_PWD = "tpt@2026"
DS_NAME = "中控杯test"


def process_one(env: dict) -> dict:
    name = env["name"]
    tenant_id = env["tenant_id"]
    ipv4 = env["ipv4"]
    ds_tar_url = f"opc.tcp://{ipv4}:18950"
    result = {"name": name, "tenant_id": tenant_id, "ipv4": ipv4, "ok": True, "errors": []}

    try:
        api = AlgAPI(BASE_URL, timeout=60.0)
        api.login(ADMIN_USER, ADMIN_PWD, tenant_id)

        existing_ds = dh.get_all_ds_info(api)
        ds_id = None
        for ds in existing_ds:
            if ds.get("dsTarUrl") == ds_tar_url:
                ds_id = ds["id"]
                result["ds_action"] = "exists"
                break
        if ds_id is None:
            resp = dh.add_ds_info(api, ds_name=DS_NAME, ds_tar_url=ds_tar_url)
            ds_id = resp.get("id")
            result["ds_action"] = "created"
            if not ds_id:
                result["ok"] = False
                result["errors"].append("add_ds_info 返回无 id")
                return result

        result["ds_id"] = ds_id

        existing_tags = dh.get_all_tags_all_types(api)
        existing_names = {t.get("tagName") for t in existing_tags}
        to_add = [(tn, dt, ro) for tn, dt, ro in TAG_DEFS if tn not in existing_names]

        if to_add:
            for tag_name, data_type, only_read in to_add:
                try:
                    dh.add_tag(
                        api,
                        tag_name=tag_name,
                        tag_base_name="1_" + tag_name,
                        data_type=data_type,
                        tag_type=TagTypes["一次位号"],
                        ds_id=ds_id,
                        only_read=only_read,
                        frequency=5,
                    )
                except Exception as e:
                    result["errors"].append(f"add_tag {tag_name}: {e}")
            result["tags_added"] = len(to_add)
        else:
            result["tags_added"] = 0

        all_tags = dh.get_all_tags_all_types(api)
        result["tag_count"] = len(all_tags)
        if len(all_tags) != 33:
            result["errors"].append(f"位号数 {len(all_tags)} != 33")

        time.sleep(3)
        tag_names = [t["tagName"] for t in all_tags]
        rt = dh.get_rt_value(api, tag_names=tag_names)
        bad_q = [item.get("tagName", "?") for item in rt if item.get("quality") != 192]
        result["rt_count"] = len(rt)
        result["bad_quality"] = bad_q
        if bad_q:
            result["errors"].append(f"quality!=192: {bad_q}")

        if result["errors"]:
            result["ok"] = False

    except Exception as e:
        result["ok"] = False
        result["errors"].append(str(e))

    return result


def main():
    config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "cub_manager", "config.json")
    with open(config_path, "r", encoding="utf-8") as f:
        config = json.load(f)

    player_envs = [e for e in config["environments"] if e["type"] == "选手"]
    print("选手租户: %d 个" % len(player_envs))
    print()

    done = 0
    total = len(player_envs)

    with ThreadPoolExecutor(max_workers=5) as pool:
        futures = {pool.submit(process_one, env): env for env in player_envs}
        for fut in as_completed(futures):
            done += 1
            r = fut.result()
            status = "OK" if r["ok"] else "FAIL"
            ds_info = "ds_id=%s (%s)" % (r.get("ds_id", "?"), r.get("ds_action", "?"))
            tag_info = "tags=%d added=%d" % (r.get("tag_count", 0), r.get("tags_added", 0))
            rt_info = "rt=%d bad_q=%d" % (r.get("rt_count", 0), len(r.get("bad_quality", [])))
            print("[%2d/%2d] %-8s %-20s %s  %s  %s  %s" % (
                done, total, status, r["name"][:20], ds_info, tag_info, rt_info,
                "" if r["ok"] else " | ".join(r["errors"])
            ))

    print()
    print("完成。")


if __name__ == "__main__":
    main()
