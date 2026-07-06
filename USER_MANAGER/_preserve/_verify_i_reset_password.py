"""一次性验证: 用 UserManagerAPI.i_reset_password 走真实接口 + 用新密码登录证明重置生效。
还原策略: 把 __verify_i_create_user__ (id=474357) 的密码从 NewPwd@2026 (probe 改的) 重置回 Verify@2026,
然后用 Verify@2026 登录证明 reset 真的生效。
"""
import json
import os
import sys

import api

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_verify_i_reset_password_out.json")

# === Step 1: admin 登录 (验 i_reset_password 之前的鉴权) ===
admin = api.UserManagerAPI("https://supcontpt.supcon.com")
try:
    admin.login("admin", "tpt@2026", tenant_id="A54Z32M2")
except Exception as e:
    print("ADMIN_LOGIN_FAILED:", type(e).__name__, str(e)[:120])
    sys.exit(1)
print("ADMIN_LOGIN_OK")

# === Step 2: i_reset_password 重置 __verify_i_create_user__ (id=474357) 密码为 Verify@2026 ===
try:
    resp_reset = admin.i_reset_password(
        user_id=474357,
        new_password="Verify@2026",
    )
except Exception as e:
    print("RESET_FAILED:", type(e).__name__, str(e)[:200])
    sys.exit(2)
print("RESET_OK")

# === Step 3: 用 __verify_i_create_user__ / Verify@2026 登录, 证明重置生效 ===
verify_user_client = api.UserManagerAPI("https://supcontpt.supcon.com")
try:
    resp_login = verify_user_client.login("__verify_i_create_user__", "Verify@2026", tenant_id="A54Z32M2")
except Exception as e:
    print("VERIFY_LOGIN_FAILED:", type(e).__name__, str(e)[:200])
    sys.exit(3)
print("VERIFY_LOGIN_OK")

# === Step 4: 反向证明 — 用旧密码 (NewPwd@2026, probe 改过的那个) 登录应该失败 ===
try:
    api.UserManagerAPI("https://supcontpt.supcon.com").login(
        "__verify_i_create_user__", "NewPwd@2026", tenant_id="A54Z32M2"
    )
    print("OLD_PWD_LOGIN_UNEXPECTED_OK")
    old_pwd_login_failed = False
except Exception as e:
    old_pwd_login_failed = True
    old_pwd_err = f"{type(e).__name__}: {str(e)[:120]}"

result = {
    "reset_resp": {
        "isSuccess": resp_reset.get("isSuccess"),
        "code": resp_reset.get("code"),
        "msg": resp_reset.get("msg"),
        "has_content_key": "content" in resp_reset,
    },
    "new_pwd_login_ok": True,
    "new_pwd_login_token_len": len(verify_user_client.token) if verify_user_client.token else 0,
    "old_pwd_login_failed_as_expected": old_pwd_login_failed,
    "old_pwd_login_error": old_pwd_err if old_pwd_login_failed else None,
}

with open(OUT, "w", encoding="utf-8") as f:
    json.dump(result, f, ensure_ascii=False, indent=2)

print("WRITE_OK")
print("OUT_PATH:", OUT)
print("OUT_BYTES:", os.path.getsize(OUT))
