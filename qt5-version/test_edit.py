import httpx
import os
import json

BASE_URL = "http://10.16.11.46:31501"

# 登录
login_payload = {"data": {"username": "api_client", "password": "Supcon@1304", "remember": False, "accountType": "0", "generateCode": False}}
r = httpx.post(
    f"{BASE_URL}/tpt-admin/system-manager/umsAdmin/login",
    json=login_payload,
    headers={"Content-Type": "application/json", "Accept": "application/json"},
    timeout=30,
)
r.raise_for_status()
token = r.json()["content"]["token"]
print(f"Login OK")

# 编辑接口
EDIT_URL = f"{BASE_URL}/alg-manager-web-v2.2-tpt/api/algorithm/edit/1"
headers = {
    "Authorization": f"Bearer {token}",
    "Accept": "application/json, text/plain, */*",
}

algorithm_json = json.dumps({
    "sourcePath": "valve_anomaly_detection_train.zip",
    "zhName": "valve_anomaly_detection_train",
    "name": "valve_anomaly_detection_train",
    "version": "1",
    "author": "zqd",
    "type": "1-100000",
    "disabled": "0",
    "id": 1003056,
    "extend": 0,
    "categoryOne": 1,
    "categoryTwo": 100000,
    "categoryThree": 0,
})

print(f"\n=== 编辑算法 {EDIT_URL} ===")
try:
    files = {
        "algorithm": ("blob", algorithm_json, "application/json"),
    }
    r = httpx.post(EDIT_URL, files=files, headers=headers, timeout=30)
    print(f"Status: {r.status_code}")
    print(f"Response: {r.text}")
except httpx.TimeoutException as e:
    print(f"Timeout: {e}")
except httpx.ConnectError as e:
    print(f"Connection error: {e}")
except httpx.HTTPStatusError as e:
    print(f"HTTP error: {e}")
except Exception as e:
    print(f"Unexpected error: {type(e).__name__}: {e}")
