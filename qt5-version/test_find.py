from api import AlgAPI

api = AlgAPI("http://10.16.11.46:31501")
api.login("api_client", "Supcon@1304")

# 测试 requestBase.page 作为真正分页参数的可能性
for page_range in ["1-100", "2-100"]:
    print(f"\n=== requestBase.page = '{page_range}' ===")
    result = api._request(
        "POST",
        "/alg-manager-web-v2.2-tpt/api/algorithm/page/1",
        body={
            "data": {"createTime_begin": "", "createTime_end": ""},
            "requestBase": {"page": page_range, "sort": "-createTime"},
        },
        params={"extend": 0},
        wrap=False,
    )
    records = result.get("records", [])
    total = result.get("total", 0)
    print(f"total={total}, returned={len(records)}")
    ids = [r.get("id") for r in records]
    print(f"ids={ids}")

    # 检查1003056是否在其中
    for r in records:
        if r.get("id") == 1003056:
            print(f"\n>>> FOUND 1003056:")
            import json
            print(json.dumps(r, indent=2, ensure_ascii=False))
            break
