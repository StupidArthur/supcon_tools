import httpx
import os

BASE_URL = "http://10.16.11.46:31501"
UPLOAD_URL = f"{BASE_URL}/alg-manager-web-v2.2-tpt/encryption/upload_file_to_minio"
ZIP_PATH = "resource/valve_anomaly_detection_train.zip"

# 登录获取 token
login_payload = {
    "data": {
        "username": "api_client",
        "password": "Supcon@1304",
        "remember": False,
        "accountType": "0",
        "generateCode": False,
    }
}

print("=== 登录 ===")
r = httpx.post(
    f"{BASE_URL}/tpt-admin/system-manager/umsAdmin/login",
    json=login_payload,
    headers={"Content-Type": "application/json", "Accept": "application/json"},
    timeout=30,
)
r.raise_for_status()
token = r.json()["content"]["token"]
print(f"Login OK, token: {token[:40]}...")

# 尝试上传
upload_headers = {
    "Authorization": f"Bearer {token}",
    "Accept": "application/json, text/plain, */*",
}

print(f"\n=== 上传文件 {ZIP_PATH} ===")
print(f"URL: {UPLOAD_URL}")

if not os.path.isfile(ZIP_PATH):
    print(f"File not found: {ZIP_PATH}")
    exit(1)

file_size = os.path.getsize(ZIP_PATH)
print(f"File size: {file_size} bytes")

try:
    with open(ZIP_PATH, "rb") as f:
        files = {
            "file": (os.path.basename(ZIP_PATH), f, "application/x-zip-compressed")
        }
        r = httpx.post(
            UPLOAD_URL,
            params={"built_in": 1},
            files=files,
            headers=upload_headers,
            timeout=120,
        )
    print(f"Status: {r.status_code}")
    print(f"Response: {r.text[:500]}")
except httpx.TimeoutException as e:
    print(f"Timeout: {e}")
except httpx.ConnectError as e:
    print(f"Connection error: {e}")
except httpx.HTTPStatusError as e:
    print(f"HTTP error: {e}")
except Exception as e:
    print(f"Unexpected error: {type(e).__name__}: {e}")
