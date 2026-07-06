"""一次性验证: 用 UserManagerAPI.i_create_user 走真实接口。
会再创建一条用户 __verify_i_create_user__, 之后用 i_get_all_users 找到它确认字段。
"""
import json
import os
import sys

import api

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_verify_i_create_user_out.json")

a = api.UserManagerAPI("https://supcontpt.supcon.com")
try:
    a.login("admin", "tpt@2026", tenant_id="A54Z32M2")
except Exception as e:
    print("LOGIN_FAILED:", type(e).__name__, str(e)[:120])
    sys.exit(1)
print("LOGIN_OK")

# === 验证 1: i_create_user (会创建一条 __verify_i_create_user__) ===
try:
    resp = a.i_create_user(
        username="__verify_i_create_user__",
        password="Verify@2026",
        nick_name="__verify_i_create_user__",
        org_ids=[1],
        org_name="默认组织",
        gender="1",
        email="verify_i_create_user@supcon.com",
        phone="18888888881",
        status=0,
        user_type="2",
        role_ids="5",
        icon="",
    )
except Exception as e:
    print("CREATE_FAILED:", type(e).__name__, str(e)[:200])
    sys.exit(2)
print("CREATE_OK")

# === 验证 2: i_get_all_users 反查新用户 ===
try:
    users = a.i_get_all_users()
except Exception as e:
    print("LIST_FAILED:", type(e).__name__, str(e)[:200])
    sys.exit(3)
print("LIST_OK")

verify_user = None
for u in users:
    if u.get("username") == "__verify_i_create_user__":
        verify_user = u
        break

result = {
    "create_resp": {
        "isSuccess": resp.get("isSuccess"),
        "success": resp.get("success"),
        "code": resp.get("code"),
        "msg": resp.get("msg"),
        "has_content_key": "content" in resp,
    },
    "total_users_after": len(users),
    "verify_user_found": verify_user is not None,
    "verify_user_fields": sorted(verify_user.keys()) if verify_user else None,
    "verify_user_values": {k: verify_user.get(k) for k in (
        "id", "username", "code", "nickName", "email", "phone", "gender",
        "status", "type", "tenantId", "delFlag"
    )} if verify_user else None,
    "probe_user_found": any(u.get("username") == "__probe_i_create_user__" for u in users),
}

with open(OUT, "w", encoding="utf-8") as f:
    json.dump(result, f, ensure_ascii=False, indent=2)

print("WRITE_OK")
print("OUT_PATH:", OUT)
print("OUT_BYTES:", os.path.getsize(OUT))
