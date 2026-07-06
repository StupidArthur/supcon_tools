import httpx
import os
import json


class AlgAPI:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")
        self.token = None
        self._https_mode = self.base_url.startswith("https://")
        self.client = httpx.Client(base_url=self.base_url, timeout=30)
        self.algorithms = []      # 缓存 get_all_algorithms 的结果
        self.source_map = {}      # sourcePath -> 算法完整信息

    def _request(self, method: str, path: str, body=None, params=None, wrap=True):
        url = f"{self.base_url}/{path.lstrip('/')}"
        json_body = {"data": body} if wrap and body is not None else body
        r = self.client.request(method, url, json=json_body, params=params)
        r.raise_for_status()
        data = r.json()
        if data.get("code") != "00000" and not (self._https_mode and not data.get("isSuccess")):
            exc = Exception(f"[{data.get('code')}] {data.get('msg')}")
            exc.is_auth_error = self._is_auth_error(data)
            raise exc
        return data.get("content", data)

    def _is_auth_error(self, data: dict) -> bool:
        """判断是否为鉴权错误。"""
        code = str(data.get("code", ""))
        auth_codes = {"A0230", "A0201", "A0202", "A0203"}
        if code in auth_codes:
            return True
        msg = data.get("msg", "")
        auth_keywords = ("未登录", "登录已超时", "登录过期", "token过期", "无访问权限", "Unauthorized")
        return any(k in msg for k in auth_keywords)

    def login(self, username: str, password: str, tenant_id: str = ""):
        body = {
            "username": username,
            "password": password,
            "remember": False,
            "accountType": "0",
            "generateCode": False,
        }
        if self._https_mode and tenant_id:
            body["tenantId"] = tenant_id
            self.client.cookies.set("TptSaasUserTenantryId", tenant_id)
            self.client.cookies.set("tenant-id", tenant_id)

        result = self._request(
            "POST",
            "/tpt-admin/system-manager/umsAdmin/login",
            body=body,
        )

        if self._https_mode:
            # HTTPS 模式：从 body 取 token，同时设 cookie 和 Bearer header
            if isinstance(result, dict) and result.get("token"):
                self.token = result["token"]
                self.client.cookies.set("tpt-token", self.token)
                self.client.headers["Authorization"] = f"Bearer {self.token}"
        else:
            # HTTP 模式：从响应 body 取 Bearer token
            self.token = result["token"]
            self.client.headers["Authorization"] = f"Bearer {self.token}"

        return result

    def list_algorithms(self, page=1, extend=0, create_time_begin="", create_time_end="", page_size=10, sort="-createTime"):
        return self._request(
            "POST",
            "/alg-manager-web-v2.2-tpt/api/algorithm/page/1",
            body={
                "data": {"createTime_begin": create_time_begin, "createTime_end": create_time_end},
                "requestBase": {"page": f"{page}-{page_size}", "sort": sort},
            },
            params={"extend": extend},
            wrap=False,
        )

    def get_all_algorithms(self, extend=0, page_size=100):
        """自动翻页，获取所有算法信息并缓存到 self.algorithms。"""
        all_records = []
        page = 1
        while True:
            result = self.list_algorithms(page=page, extend=extend, page_size=page_size)
            records = result.get("records", [])
            if not records:
                break
            all_records.extend(records)
            if len(records) < page_size:
                break
            page += 1
        self.algorithms = all_records
        self.source_map = {a.get("sourcePath"): a for a in all_records if a.get("sourcePath")}
        return self.algorithms

    def get_by_source_path(self, source_path: str):
        """通过 sourcePath 获取缓存的算法信息。"""
        return self.source_map.get(source_path)

    def get_by_id(self, algo_id: int):
        """通过 id 获取缓存的算法信息。"""
        for a in self.algorithms:
            if a.get("id") == algo_id:
                return a
        return None

    def release_algorithm(self, algo_id: int, is_release: int, cores: int = 1, resource_type: int = 1, num_replicas: int = 1):
        """
        发布或取消发布算法。
        is_release: 0=取消发布, 1=发布
        resource_type: 1=CPU, 2=GPU
        """
        return self._request(
            "POST",
            "/alg-manager-web-v2.2-tpt/api/algorithm/release",
            body={
                "id": algo_id,
                "isRelease": is_release,
                "cores": cores,
                "resourceType": resource_type,
                "numReplicas": num_replicas,
            },
            wrap=False,
        )

    def upload_file(self, file_path: str, built_in: int = 1) -> dict:
        """
        上传 zip 文件到 MinIO。
        built_in: 1
        返回上传结果 dict。
        """
        url = f"{self.base_url}/alg-manager-web-v2.2-tpt/encryption/upload_file_to_minio"
        with open(file_path, "rb") as f:
            files = {
                "file": (os.path.basename(file_path), f, "application/x-zip-compressed")
            }
            r = self.client.post(url, params={"built_in": built_in}, files=files)
        r.raise_for_status()
        return r.json()

    def edit_algorithm(self, source_path: str = None, algo_id: int = None):
        """
        提交算法信息（需先上传文件）。
        只需传入 source_path 或 algo_id，从缓存中读取算法信息并自动拼接 type 字段。
        """
        if source_path:
            info = self.source_map.get(source_path)
        elif algo_id:
            info = self.get_by_id(algo_id)
        else:
            raise ValueError("必须传入 source_path 或 algo_id")

        if not info:
            raise ValueError(f"未找到算法: source_path={source_path}, algo_id={algo_id}")

        algo_info = dict(info)
        algo_info["type"] = f"{info.get('categoryOne', 1)}-{info.get('categoryTwo', 0)}"
        url = f"{self.base_url}/alg-manager-web-v2.2-tpt/api/algorithm/edit/1"
        algorithm_json = json.dumps(algo_info)
        files = {"algorithm": ("blob", algorithm_json, "application/json")}
        r = self.client.post(url, files=files)
        r.raise_for_status()
        data = r.json()
        if data.get("code") != "00000":
            raise Exception(f"[{data.get('code')}] {data.get('msg')}")
        return data.get("content", data)

    def match_local_files(self, resource_dir: str = "resource") -> list[dict]:
        """
        拿本地文件名匹配 self.source_map，返回完整算法信息 dict 列表。
        匹配到的条目包含算法全部字段，未匹配的条目包含 name 和 isExist=False。
        """
        local_files = list_local_resources(resource_dir)
        result = []
        for f in local_files:
            info = self.source_map.get(f)
            if info:
                item = dict(info)
                item["name"] = f
                item["isExist"] = True
                item["cores"] = int(item.get("cores", 1.0))
                result.append(item)
            else:
                result.append({
                    "name": f,
                    "isExist": False,
                })
        return result


import os


def list_local_resources(dir_path: str = "resource") -> list:
    """读取指定目录下所有 .zip 和 .py 文件名（带后缀）。"""
    if not os.path.isdir(dir_path):
        return []
    return [f for f in os.listdir(dir_path) if f.endswith(".zip") or f.endswith(".py")]


if __name__ == "__main__":
    api = AlgAPI("http://10.16.11.1:31501")
    api.login("api_client", "Supcon@1304")
    api.get_all_algorithms()
    print(api.algorithms)
