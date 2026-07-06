"""recheck: 距上次 disambig 已过 14+ min, 再测一遍 3 个密码是否还能登 __verify_i_create_user__。
"""
import json
import os
import sys
import time

import api

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_recheck_passwords_out.json")

# 3 个待测密码
TARGET_USER = "__verify_i_create_user__"
PWDS = ["Verify@2026", "NewPwd@2026", "ResetPwd@2026"]

# 计算距上次 reset 已过多久
last_reset_file = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_disambig_reset_out.json")
elapsed_since_reset = time.time() - os.path.getmtime(last_reset_file)


def try_login(pwd: str) -> tuple:
    c = api.UserManagerAPI("https://supcontpt.supcon.com")
    try:
        c.login(TARGET_USER, pwd, tenant_id="A54Z32M2")
        return True, None
    except Exception as e:
        return False, f"{type(e).__name__}: {str(e)[:160]}"


results = {}
for p in PWDS:
    ok, err = try_login(p)
    results[p] = {"ok": ok, "err": err}
    print(f"LOGIN_{p}: {'OK' if ok else 'FAIL'}")

out = {
    "elapsed_since_last_reset_sec": round(elapsed_since_reset, 1),
    "elapsed_since_last_reset_min": round(elapsed_since_reset / 60, 2),
    "target_user": TARGET_USER,
    "results": results,
}

with open(OUT, "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, indent=2)

print("WRITE_OK")
print("OUT_PATH:", OUT)
print("OUT_BYTES:", os.path.getsize(OUT))
