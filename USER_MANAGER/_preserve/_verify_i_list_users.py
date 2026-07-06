"""一次性验证: 用 UserManagerAPI.i_list_users / i_get_all_users 走真实接口。
输出写到 _verify_i_list_users_out.json, stdout 只输出状态。
"""
import json
import os
import sys

import api

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_verify_i_list_users_out.json")

a = api.UserManagerAPI("https://supcontpt.supcon.com")
try:
    a.login("admin", "tpt@2026", tenant_id="A54Z32M2")
except Exception as e:
    print("LOGIN_FAILED:", type(e).__name__, str(e)[:120])
    sys.exit(1)
print("LOGIN_OK")

# === 验证 1: i_list_users 单页, 应与探针响应一致 ===
try:
    page1 = a.i_list_users(page=1, page_size=10, org_id="", keyword="", sort="")
except Exception as e:
    print("ILIST_FAILED:", type(e).__name__, str(e)[:200])
    sys.exit(2)
print("ILIST_PAGE1_OK")

# === 验证 2: i_list_users 第 2 页 (探针响应 total=13, 共 2 页) ===
try:
    page2 = a.i_list_users(page=2, page_size=10, org_id="", keyword="", sort="")
except Exception as e:
    print("ILIST_P2_FAILED:", type(e).__name__, str(e)[:200])
    sys.exit(3)
print("ILIST_PAGE2_OK")

# === 验证 3: i_get_all_users 自动翻页 ===
try:
    users = a.i_get_all_users(org_id="", keyword="", sort="", page_size=10)
except Exception as e:
    print("IGETALL_FAILED:", type(e).__name__, str(e)[:200])
    sys.exit(4)
print("IGETALL_OK")

# === 验证 4: 关键字搜索 (测 adminWhere 的 *field*|... 语法) ===
try:
    kw = a.i_list_users(page=1, page_size=10, org_id="", keyword="admin", sort="")
except Exception as e:
    print("KW_FAILED:", type(e).__name__, str(e)[:200])
    sys.exit(5)
print("KW_OK")

result = {
    "page1": {
        "total": page1.get("total"),
        "size": page1.get("size"),
        "current": page1.get("current"),
        "pages": page1.get("pages"),
        "records_count": len(page1.get("records", [])),
        "first_username": (page1.get("records") or [{}])[0].get("username"),
        "fields_in_first_record": sorted((page1.get("records") or [{}])[0].keys()),
    },
    "page2": {
        "total": page2.get("total"),
        "records_count": len(page2.get("records", [])),
        "usernames": [u.get("username") for u in page2.get("records", [])],
    },
    "igetall": {
        "cached_count": len(a.users),
        "user_map_keys_count": len(a.user_map),
        "user_map_key_types": sorted({type(k).__name__ for k in a.user_map.keys()}),
        "first_user_id": (a.users or [{}])[0].get("id"),
        "first_user_username": (a.users or [{}])[0].get("username"),
        "usernames_all": [u.get("username") for u in a.users],
    },
    "kw_search_admin": {
        "total": kw.get("total"),
        "records_count": len(kw.get("records", [])),
        "usernames": [u.get("username") for u in kw.get("records", [])],
    },
}

with open(OUT, "w", encoding="utf-8") as f:
    json.dump(result, f, ensure_ascii=False, indent=2)

print("WRITE_OK")
print("OUT_PATH:", OUT)
print("OUT_BYTES:", os.path.getsize(OUT))
