"""一次性探针: 创建 email+phone 都为空的账号, 看平台是否接受。

直接 import _preserve/api.py 的 UserManagerAPI（之前会话写过的封装）。
"""
import importlib.util
import json
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(_HERE))  # alg_update/

# 显式加载 _preserve/api.py
_spec = importlib.util.spec_from_file_location("user_mgr_api", os.path.join(_HERE, "_preserve", "api.py"))
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)
UserManagerAPI = _mod.UserManagerAPI

OUT = os.path.join(_HERE, "_probe_empty_email_phone_resp.json")

a = UserManagerAPI("https://supcontpt.supcon.com")
try:
    a.login("admin", "tpt@2026", tenant_id="A54Z32M2")
except Exception as e:
    print("LOGIN_FAILED:", type(e).__name__, str(e)[:120])
    sys.exit(1)
print("LOGIN_OK")

try:
    resp = a.i_create_user(
        username="__probe_empty_fields__",
        password="Probe@2026",
        nick_name="__probe_empty_fields__",
        email="",
        phone="",
    )
except Exception as e:
    print("CREATE_FAILED:", type(e).__name__, str(e)[:200])
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump({"error": str(e), "type": type(e).__name__}, f, ensure_ascii=False, indent=2)
    sys.exit(2)

with open(OUT, "w", encoding="utf-8") as f:
    json.dump({
        "code": resp.get("code") if isinstance(resp, dict) else "?",
        "msg": resp.get("msg") if isinstance(resp, dict) else str(resp),
    }, f, ensure_ascii=False, indent=2)

code = resp.get("code") if isinstance(resp, dict) else "?"
msg = resp.get("msg") if isinstance(resp, dict) else ""
print(f"CODE: {code} MSG: {(msg or '')[:120]}")
print("OUT:", OUT)