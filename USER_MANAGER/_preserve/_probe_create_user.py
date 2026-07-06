"""一次性探针: 登录 + 调创建用户接口, 响应落盘。

会创建一条用户: __probe_i_create_user__ (一眼能识别, 后续 USER_MANAGER 清理时一起删)。
"""
import json
import os
import sys

import api

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_probe_create_user_resp.json")

a = api.UserManagerAPI("https://supcontpt.supcon.com")
try:
    a.login("admin", "tpt@2026", tenant_id="A54Z32M2")
except Exception as e:
    print("LOGIN_FAILED:", type(e).__name__, str(e)[:120])
    sys.exit(1)
print("LOGIN_OK")

# 故意 username/code/nickName 都加 __probe__ 前缀, 方便后续清理
body = {
    "data": {
        "status": 0,
        "orgIds": [1],
        "username": "__probe_i_create_user__",
        "code": "__probe_i_create_user_code__",
        "nickName": "__probe_i_create_user__",
        "password": "Probe@2026",
        "gender": "1",
        "email": "probe_i_create_user@supcon.com",
        "phone": "19999999999",
        "orgName": "默认组织",
        "type": "2",
        "roleIds": "5",
        "icon": "",
    }
}

try:
    resp = a._request("POST", "/xpt-system/api/system-manager/umsAdmin",
                      body=body, params=None, wrap=False)
except Exception as e:
    print("CALL_FAILED:", type(e).__name__, str(e)[:200])
    sys.exit(2)

with open(OUT, "w", encoding="utf-8") as f:
    json.dump(resp, f, ensure_ascii=False, indent=2)

print("CALL_OK")
print("OUT_PATH:", OUT)
print("OUT_BYTES:", os.path.getsize(OUT))
