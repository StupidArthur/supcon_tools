"""一次性探针：登录 + 调 listByOrgId，把响应落盘。stdout 只输出状态和文件路径。"""
import json
import os
import sys

import api

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_probe_list_users_resp.json")

a = api.AlgAPI("https://supcontpt.supcon.com")
try:
    a.login("admin", "tpt@2026", tenant_id="A54Z32M2")
except Exception as e:
    print("LOGIN_FAILED:", type(e).__name__, str(e)[:120])
    sys.exit(1)

print("LOGIN_OK")

req_body = {
    "data": {
        "adminWhere": {"*nickName*|*username*|*phone*|*email*": ""},
        "orgId": "",
    },
    "requestBase": {"page": "1-10", "sort": ""},
}

# 直接走 self._request 复刻 curl 的形态（wrap=False 因为 body 已含 data/requestBase）
try:
    resp = a._request("POST", "/xpt-system/api/system-manager/umsAdmin/listByOrgId",
                      body=req_body, params=None, wrap=False)
except Exception as e:
    print("CALL_FAILED:", type(e).__name__, str(e)[:200])
    sys.exit(2)

with open(OUT, "w", encoding="utf-8") as f:
    json.dump(resp, f, ensure_ascii=False, indent=2)

print("CALL_OK")
print("OUT_PATH:", OUT)
print("OUT_BYTES:", os.path.getsize(OUT))
