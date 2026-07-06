"""一次性探针: 登录 + 重置 __verify_i_create_user__ (id=474357) 的密码, 响应落盘。
"""
import json
import os
import sys

import api

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_probe_reset_pwd_resp.json")

a = api.UserManagerAPI("https://supcontpt.supcon.com")
try:
    a.login("admin", "tpt@2026", tenant_id="A54Z32M2")
except Exception as e:
    print("LOGIN_FAILED:", type(e).__name__, str(e)[:120])
    sys.exit(1)
print("LOGIN_OK")

# 重置 __verify_i_create_user__ 的密码为 NewPwd@2026 (之前是 Verify@2026, 验证后会还原)
body = {"id": 474357, "newPwd": "NewPwd@2026", "confirmPwd": "NewPwd@2026"}

try:
    resp = a._request("POST", "/xpt-system/api/system-manager/umsAdmin/resetPwd",
                      body=body, params=None, wrap=True)
except Exception as e:
    print("CALL_FAILED:", type(e).__name__, str(e)[:200])
    sys.exit(2)

with open(OUT, "w", encoding="utf-8") as f:
    json.dump(resp, f, ensure_ascii=False, indent=2)

print("CALL_OK")
print("OUT_PATH:", OUT)
print("OUT_BYTES:", os.path.getsize(OUT))
