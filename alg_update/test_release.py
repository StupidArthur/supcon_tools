from api import AlgAPI

api = AlgAPI("http://10.16.11.46:31501")
api.login("api_client", "Supcon@1304")

url = "http://10.16.11.46:31501/alg-manager-web-v2.2-tpt/api/algorithm/release"

# 测试发布一个未发布的算法 (1002117 isRelease=0)
print("=== 测试发布 1002117 (当前未发布) ===")
try:
    r = api.client.post(url, json={"id": 1002117, "isRelease": 1, "cores": 1, "resourceType": 1, "numReplicas": 1})
    print(f"Status: {r.status_code}")
    print(f"Response: {r.text}")
except Exception as e:
    print(f"Error: {e}")

# 测试取消发布一个已发布的算法 (1003056 isRelease=1)
print("\n=== 测试取消发布 1003056 (当前已发布) ===")
try:
    r = api.client.post(url, json={"id": 1003056, "isRelease": 0, "cores": 1, "resourceType": 1, "numReplicas": 1})
    print(f"Status: {r.status_code}")
    print(f"Response: {r.text}")
except Exception as e:
    print(f"Error: {e}")
