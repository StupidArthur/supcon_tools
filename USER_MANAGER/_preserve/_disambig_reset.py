"""消歧测试: reset 到第三个唯一密码, 然后分别试 3 个密码。
如果 reset 真生效: 只有 ResetPwd@2026 能登, 其它 2 个 fail。
如果平台有密码历史: 3 个都能登。
"""
import json
import os
import sys

import api

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_disambig_reset_out.json")

# === admin 登录 + reset 到第三个唯一密码 ===
admin = api.UserManagerAPI("https://supcontpt.supcon.com")
try:
    admin.login("admin", "tpt@2026", tenant_id="A54Z32M2")
except Exception as e:
    print("ADMIN_LOGIN_FAILED:", type(e).__name__, str(e)[:120])
    sys.exit(1)

try:
    resp = admin.i_reset_password(user_id=474357, new_password="ResetPwd@2026")
except Exception as e:
    print("RESET_FAILED:", type(e).__name__, str(e)[:200])
    sys.exit(2)
print("RESET_TO_ResetPwd_OK")

def try_login(pwd: str) -> tuple:
    c = api.UserManagerAPI("https://supcontpt.supcon.com")
    try:
        c.login("__verify_i_create_user__", pwd, tenant_id="A54Z32M2")
        return True, None
    except Exception as e:
        return False, f"{type(e).__name__}: {str(e)[:120]}"

probes = ["ResetPwd@2026", "Verify@2026", "NewPwd@2026"]
results = {p: {"ok": None, "err": None} for p in probes}
for p in probes:
    ok, err = try_login(p)
    results[p]["ok"] = ok
    results[p]["err"] = err
    print(f"LOGIN_{p}: {'OK' if ok else 'FAIL'}")

# 最后: reset 回一个已知值, 留作清理状态
admin.i_reset_password(user_id=474357, new_password="Verify@2026")
print("RESTORED_TO_Verify@2026")

with open(OUT, "w", encoding="utf-8") as f:
    json.dump({"results": results, "reset_resp_code": resp.get("code")},
              f, ensure_ascii=False, indent=2)

print("WRITE_OK")
print("OUT_PATH:", OUT)
print("OUT_BYTES:", os.path.getsize(OUT))
