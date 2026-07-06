"""recheck v2: 累积上限测试。
1. admin 把 __verify_i_create_user__ (id=474357) 的密码 reset 到第 4 个唯一值 Pwd4@2026
2. 用 4 个密码依次尝试登录, 看平台是否同时接受全部
"""
import json
import os
import sys
import time

import api

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_recheck_4pwd_out.json")
TARGET = "__verify_i_create_user__"
PWDS = ["Verify@2026", "NewPwd@2026", "ResetPwd@2026", "Pwd4@2026"]  # 4 个唯一密码

# admin 登录 + reset 到 Pwd4@2026
admin = api.UserManagerAPI("https://supcontpt.supcon.com")
try:
    admin.login("admin", "tpt@2026", tenant_id="A54Z32M2")
except Exception as e:
    print("ADMIN_LOGIN_FAILED:", type(e).__name__, str(e)[:120])
    sys.exit(1)
print("ADMIN_LOGIN_OK")

try:
    resp_reset = admin.i_reset_password(user_id=474357, new_password="Pwd4@2026")
except Exception as e:
    print("RESET_FAILED:", type(e).__name__, str(e)[:200])
    sys.exit(2)
print("RESET_TO_Pwd4_OK")
print("RESET_CODE:", resp_reset.get("code"))


def try_login(pwd: str) -> tuple:
    c = api.UserManagerAPI("https://supcontpt.supcon.com")
    try:
        c.login(TARGET, pwd, tenant_id="A54Z32M2")
        return True, None
    except Exception as e:
        return False, f"{type(e).__name__}: {str(e)[:160]}"


results = {}
for p in PWDS:
    ok, err = try_login(p)
    results[p] = {"ok": ok, "err": err}
    print(f"LOGIN_{p}: {'OK' if ok else 'FAIL'}")

ok_count = sum(1 for r in results.values() if r["ok"])
out = {
    "target_user": TARGET,
    "pwd_attempted_count": len(PWDS),
    "pwd_login_ok_count": ok_count,
    "all_ok": ok_count == len(PWDS),
    "results": results,
}

with open(OUT, "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, indent=2)

print("WRITE_OK")
print("OUT_PATH:", OUT)
print("OUT_BYTES:", os.path.getsize(OUT))
