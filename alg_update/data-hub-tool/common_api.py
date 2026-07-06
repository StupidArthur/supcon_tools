"""data-hub tag 管理 + 历史值导入 API 客户端。

基于 ibd-data-hub-web-v2.2 平台, 复用 AlgAPI 登录。

2026-06-27: 算法相关 API 已剥离, 此文件专注 data-hub 位号管理 + 历史值导入。
注: 此前是 ../common/api.py 的本地快照, 现已分叉, 同步源会冲突。

封装 endpoint:
  POST /ibd-data-hub-web-v2.2/api/tag-info/add                         注册位号
  POST /ibd-data-hub-web-v2.2/api/tag-info/page                        分页列位号 (MyBatis Page)
  POST /ibd-data-hub-web-v2.2/api/tag-value/importTagValue             JSON 批量导入历史值 (≤10000)
  POST /ibd-data-hub-web-v2.2/api/tag-value/importTagValueHistory      Excel/ZIP 导入历史值 (异步)
  POST /ibd-data-hub-web-v2.2/api/tag-value/importCSVTagValueHistory   CSV 导入历史值 (已废弃)
  POST /ibd-data-hub-web-v2.2/api/tag-value/getHistoryValueFromDB      查历史值 (验证用)
"""

import os
import logging
import httpx

log = logging.getLogger(__name__)


class AlgAPI:
    def __init__(self, base_url: str, timeout: float = 60.0):
        # 默认 60s: 实测 29 tags 在 1970-2099 宽范围上 getHistoryValueFromDB 会超时
        # 用户报告 timeout (2026-07 用户反馈). 仍可按需外部覆盖.
        self.base_url = base_url.rstrip("/")
        self.token = None
        self._https_mode = self.base_url.startswith("https://")
        self.client = httpx.Client(base_url=self.base_url, timeout=timeout)
        # get_all_tags 缓存
        self.tags = []           # list[dict]
        self.name_map = {}       # tagName -> tag 完整信息

    # === 内部辅助 ===

    def _request(self, method: str, path: str, body=None, params=None, wrap=True):
        url = f"{self.base_url}/{path.lstrip('/')}"
        json_body = {"data": body} if wrap and body is not None else body
        log.debug("%s %s", method, url)
        r = self.client.request(method, url, json=json_body, params=params)
        r.raise_for_status()
        data = r.json()
        if data.get("code") != "00000" and not (self._https_mode and not data.get("isSuccess")):
            code = data.get("code")
            msg = data.get("msg")
            log.error("业务 code 非 00000: %s %s -> code=%s msg=%s", method, url, code, msg)
            exc = Exception(f"[{data.get('code')}] {data.get('msg')}")
            exc.is_auth_error = self._is_auth_error(data)
            raise exc
        log.debug("%s %s -> OK", method, url)
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

    # === 登录 ===

    def login(self, username: str, password: str, tenant_id: str = ""):
        log.info("登录开始: user=%s, https=%s", username, self._https_mode)
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

        log.info("登录成功: token 长度=%d", len(self.token or ""))
        return result

    # === 位号管理 (data-hub) ===

    # 平台 dataType 枚举 (实测 2026-06-27)
    DATA_TYPES = {
        "BOOLEAN": 1, "S_BYTE": 2, "BYTE": 3, "SHORT": 4, "U_SHORT": 5,
        "INT": 6, "U_INT": 7, "LONG": 8, "U_LONG": 9, "FLOAT": 10, "DOUBLE": 11,
    }
    # 平台 tagType 枚举
    TAG_TYPES = {"一次位号": 1, "虚位号": 4}

    def add_tag(self, tag_name: str, data_type: int = 11, tag_type: int = 1,
                ds_id: int = 2, group_id: str = "0", unit: str = "",
                only_read: bool = False, frequency: int = 10,
                need_push: bool = True, tag_desc: str = None,
                is_vector: bool = True) -> dict:
        """注册一个位号。

        参数:
          tag_name:    系统位号名 (也是底层位号名, 默认同名)
          data_type:   数据类型代码 (1=BOOLEAN .. 11=DOUBLE), 默认 11=DOUBLE
          tag_type:    位号类型 (1=一次位号, 4=虚位号), 默认 1
          ds_id:       数据源 ID (默认 2 = "我的数据源")
          group_id:    位号分组 ID, 默认 "0" = Root
          unit:        单位
          only_read:   是否只读
          frequency:   采集频率(秒)
          need_push:   是否需要推送
          tag_desc:    描述, 默认 "{tag_name} 描述"
          is_vector:   是否向量

        返回: API 响应 content 字段 (一般为空 dict)
        """
        if tag_desc is None:
            tag_desc = f"{tag_name} 描述"
        return self._request(
            "POST",
            "/ibd-data-hub-web-v2.2/api/tag-info/add",
            body={
                "tagType": tag_type,
                "dsId": ds_id,
                "tagBaseName": tag_name,
                "tagName": tag_name,
                "dataType": data_type,
                "unit": unit,
                "onlyRead": only_read,
                "frequency": frequency,
                "needPush": need_push,
                "tagDesc": tag_desc,
                "isVector": is_vector,
                "groupId": group_id,
            },
            wrap=True,
        )

    def list_tags(self, page: int = 1, page_size: int = 10,
                  sort: str = "-createTime", data: dict = None) -> dict:
        """分页列位号 (MyBatis Page 结构)。

        参数:
          page:      页码 (从 1 开始)
          page_size: 每页条数
          sort:      排序字段 (如 "-createTime" = createTime 降序)
          data:      过滤条件 dict, 例如 {"tagName": "t_double"} 或 {"dataType": 11}

        返回: content 字典, 包含 records / total / size / current / orders 等
        """
        return self._request(
            "POST",
            "/ibd-data-hub-web-v2.2/api/tag-info/page",
            body={
                "data": data or {},
                "requestBase": {"page": f"{page}-{page_size}", "sort": sort},
            },
            wrap=False,
        )

    def get_all_tags(self, page_size: int = 200, sort: str = "-createTime",
                     data: dict = None) -> list:
        """自动翻页, 拉取所有位号, 缓存到 self.tags 和 self.name_map。

        返回: 全部位号 list[dict]
        """
        all_records = []
        page = 1
        while True:
            result = self.list_tags(page=page, page_size=page_size, sort=sort, data=data)
            records = result.get("records", [])
            if not records:
                break
            all_records.extend(records)
            if len(records) < page_size:
                break
            page += 1
        self.tags = all_records
        self.name_map = {t.get("tagName"): t for t in all_records if t.get("tagName")}
        log.info("get_all_tags 完成: 共 %d tags (filter=%s)", len(all_records), data)
        return all_records

    def get_tag_by_name(self, tag_name: str) -> dict:
        """通过 tagName 获取缓存的位号信息 (依赖 get_all_tags 先跑过)。"""
        return self.name_map.get(tag_name)

    def get_all_tags_all_types(self, page_size: int = 2000,
                               tag_types=(1, 4, 0, 2, 3, 5)) -> list:
        """拉取全部位号, 遍历所有 tagType 合并去重 (按 id).

        get_all_tags() 默认 data 为空, 平台只返回默认类, 会漏掉其它 tagType
        的位号 (实测曾因此漏掉 ~87 个删不掉). 本方法逐个 tagType 拉取后合并,
        确保不漏. 返回去重后的 list[dict].
        """
        seen, all_records = set(), []
        for tt in tag_types:
            try:
                records = self.get_all_tags(page_size=page_size, data={"tagType": tt})
            except Exception:
                records = []
            for t in records:
                tid = t.get("id")
                if tid is not None and tid not in seen:
                    seen.add(tid)
                    all_records.append(t)
        # 重建缓存为合并后的全集
        self.tags = all_records
        self.name_map = {t.get("tagName"): t for t in all_records if t.get("tagName")}
        return all_records

    def delete_tags(self, ids) -> dict:
        """批量逻辑删除位号 (POST /api/tag-info/batchDeleteLogic).

        参数:
          ids: int / int 的可迭代对象 (位号 id 列表)

        返回: _parse_resp dict (HTTP 200 / code=00000 = 请求已接受).
              注意: 逻辑删除, 数据保留但位号在列表中不再可见.

        位号 id 来源 (联动关系):
          - list_tags() / get_all_tags() 返回的每条 record 含 'id' 字段
          - get_tag_by_name(name)['id'] 从缓存取单个 id
          - 上层用 tag 名 → 查 id → 删除, 见 delete_tags_by_name()
        """
        if isinstance(ids, int):
            ids = [ids]
        ids = [int(i) for i in ids]
        r = self.client.request(
            "DELETE",
            "/ibd-data-hub-web-v2.2/api/tag-info/batchDeleteLogic",
            json={"data": {"ids": ids}},
        )
        return self._parse_resp(r)

    def delete_tags_by_name(self, tag_names, refresh: bool = False) -> dict:
        """按位号名批量删除. 内部用 name_map 查 id 再调 delete_tags.

        参数:
          tag_names: str / str 的可迭代对象
          refresh:   若 name_map 为空 (还没 get_all_tags 过), 自动拉一次

        返回: {
            "deleted":  [tagName, ...],   # 成功删除的
            "missing":  [tagName, ...],   # 目标环境不存在的
            "result":   delete_tags() 返回,
        }
        """
        if isinstance(tag_names, str):
            tag_names = [tag_names]
        if refresh or not self.name_map:
            self.get_all_tags()
        deleted, missing, ids = [], [], []
        for name in tag_names:
            t = self.name_map.get(name)
            if t and t.get("id") is not None:
                ids.append(int(t["id"]))
                deleted.append(name)
            else:
                missing.append(name)
        result = None
        if ids:
            result = self.delete_tags(ids)
        return {"deleted": deleted, "missing": missing, "result": result}

    # === 回收站 (逻辑删除后的位号) ===
    #
    # 业务: batchDeleteLogic 是软删 (进回收站), batchDelete 才是物理删 (清回收站).
    # 回收站里的位号不再出现在 list_tags, 必须用 tag-group/get 查 (按 groupId 分组).

    def list_recycle_tags(self, page: int = 1, page_size: int = 100,
                          group_id: str = "1", tag_type: int = 1,
                          sort: str = "-createTime") -> dict:
        """查回收站位号 (POST /api/tag-group/get), 单页.

        平台回收站用 groupId=1 表示 (实测). 返回 MyBatis Page 结构
        (records / total / ...), 每条 record 含 id / tagName 等.

        参数:
          page:      页码 (从 1 开始)
          page_size: 每页条数 (requestBase.page = "page-page_size")
          group_id:  回收站分组 id, 默认 "1"
          tag_type:  位号类型 (1=一次位号)
          sort:      排序字段
        """
        return self._request(
            "POST",
            "/ibd-data-hub-web-v2.2/api/tag-group/get",
            body={
                "data": {"groupId": str(group_id), "tagType": tag_type,
                         "sortField": sort, "sortType": 1},
                "requestBase": {"page": f"{page}-{page_size}", "sort": sort},
            },
            wrap=False,
        )

    def get_all_recycle_tags(self, page_size: int = 100, group_id: str = "1",
                             tag_type: int = 1, on_page=None) -> list:
        """翻页拉取回收站全部位号. 返回 list[dict] (每条含 id/tagName).

        注意: tag-group/get 的响应结构是 content.tagInfoList.records
              (位号藏在分组对象的 tagInfoList 里, 不是顶层 records).

        on_page: 可选回调 on_page(page, accumulated), 每拉一页调用, 用于进度展示.
        """
        all_records = []
        page = 1
        while True:
            result = self.list_recycle_tags(page=page, page_size=page_size,
                                            group_id=group_id, tag_type=tag_type)
            # content 是分组对象, 位号在 tagInfoList.records
            info = result.get("tagInfoList", {}) if isinstance(result, dict) else {}
            records = info.get("records", [])
            if not records:
                break
            all_records.extend(records)
            if on_page:
                on_page(page, len(all_records))
            if len(records) < page_size:
                break
            page += 1
        return all_records

    def delete_tags_physical(self, ids) -> dict:
        """物理删除位号 (DELETE /api/tag-info/batchDelete) — 清回收站.

        与 delete_tags (batchDeleteLogic 软删) 的区别: 这个是物理删, 不可恢复.
        参数/返回同 delete_tags.
        """
        if isinstance(ids, int):
            ids = [ids]
        ids = [int(i) for i in ids]
        r = self.client.request(
            "DELETE",
            "/ibd-data-hub-web-v2.2/api/tag-info/batchDelete",
            json={"data": {"ids": ids}},
        )
        return self._parse_resp(r)

    # === 历史值导入 (data-hub) ===
    #
    # 注意: 3 个导入端点都返回 HTTP 200 / code=00000 ≠ 数据落地,
    # 实际写入是异步的, 必须用 list_tags / queryWithQuality 回头查。
    # (PROGRESS.md 5.4)

    @staticmethod
    def _parse_resp(r: httpx.Response) -> dict:
        """统一解析导入端点响应。

        返回: {
            "status_code": int,
            "code": str,           # 业务 code
            "msg": str,            # 业务 msg
            "is_success": bool,    # HTTP 200 且 (isSuccess/success=true) 且 code="00000"
            "data": any,           # 响应 data 字段 (importTagValue 这里是失败位号 dict)
            "raw": dict,           # 完整响应 dict
        }
        """
        try:
            body = r.json()
        except Exception:
            return {
                "status_code": r.status_code,
                "code": None,
                "msg": r.text[:500],
                "is_success": r.status_code == 200,
                "data": None,
                "raw": None,
            }
        is_ok = r.status_code == 200 and (body.get("isSuccess") or body.get("success")) and body.get("code") == "00000"
        return {
            "status_code": r.status_code,
            "code": body.get("code"),
            "msg": body.get("msg"),
            "is_success": is_ok,
            "data": body.get("data"),
            "raw": body,
        }

    def import_tag_value(self, data: list, ds_id: int = None) -> dict:
        """JSON 批量导入历史值 (同步, 一次最多 10000 条)。

        参数:
          data: list[dict], 每个 dict 至少含 tagName/tagValue, 可选 quality/tagTime/appTime
                时间格式 yyyy-MM-dd HH:mm:ss (空格分隔, 不是 ISO T)
          ds_id: 数据源 ID, None=默认时序库

        返回: _parse_resp dict, 其中 data 字段是失败位号 dict {tagName: [errors]}
        """
        url = "/ibd-data-hub-web-v2.2/api/tag-value/importTagValue"
        body = {"data": data}
        if ds_id is not None:
            body["dsId"] = ds_id
        r = self.client.post(url, json=body)
        return self._parse_resp(r)

    def import_tag_value_history(self, file_path: str,
                                 ds_id: int = None,
                                 start_time: str = None,
                                 end_time: str = None,
                                 frequency: int = None,
                                 cron: str = None) -> dict:
        """Excel / ZIP 导入历史值 (异步)。

        参数:
          file_path:  .xlsx / .xls / .zip
          ds_id:      数据源 ID, None 或 0 = 默认时序库
          start_time: 起始时间过滤, 优先于 A1 里的
          end_time:   结束时间过滤
          frequency:  采样频率
          cron:       Cron 表达式 (注意: API 拼写是 corn 不是 cron)

        Excel 格式 (A1 四段逗号):
          A1: startTime,endTime,frequency,corn
          A2: (空)
          A3 起: 时间, 位号1值, 位号2值, ...

        返回: _parse_resp dict (HTTP 200 仅代表请求已接受, 数据异步处理)
        """
        # 按扩展名决定 MIME
        ext = os.path.splitext(file_path)[1].lower()
        mime_map = {
            ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            ".xls":  "application/vnd.ms-excel",
            ".zip":  "application/zip",
        }
        mime = mime_map.get(ext, "application/octet-stream")

        url = "/ibd-data-hub-web-v2.2/api/tag-value/importTagValueHistory"
        size = os.path.getsize(file_path) if os.path.exists(file_path) else 0
        log.info("上传文件: %s (size=%d bytes, mime=%s)", file_path, size, mime)
        with open(file_path, "rb") as f:
            files = {"file": (os.path.basename(file_path), f, mime)}
            form = {}
            if ds_id is not None and ds_id != 0:
                form["dsId"] = ds_id
            if start_time:
                form["startTime"] = start_time
            if end_time:
                form["endTime"] = end_time
            if frequency is not None:
                form["frequency"] = str(frequency)
            if cron:
                form["corn"] = cron  # API 拼写是 corn
            r = self.client.post(url, files=files, data=form)
        result = self._parse_resp(r)
        log.info(
            "上传响应: status=%s code=%s msg=%s requestId=%s",
            result["status_code"], result["code"], result["msg"],
            (result["raw"] or {}).get("requestId") if result.get("raw") else None,
        )
        return result

    def import_csv_tag_value_history(self, file_path: str) -> dict:
        """CSV 导入历史值 (已废弃, 但接口仍可用)。"""
        url = "/ibd-data-hub-web-v2.2/api/tag-value/importCSVTagValueHistory"
        with open(file_path, "rb") as f:
            files = {"file": (os.path.basename(file_path), f, "text/csv")}
            r = self.client.post(url, files=files)
        return self._parse_resp(r)

    # === 历史值查询 (data-hub) ===
    #
    # 用于 import 后的"验证闭环": 导入是异步的, 用这个端点读回数据判断是否真落地。

    def get_history_value(self, tag_names, beg_time: str, end_time: str,
                          is_source: bool = True, number_to_string: bool = False,
                          page: int = 1, page_size: int = 100,
                          sort: str = "-appTime") -> dict:
        """查位号历史值 (单页)。

        参数:
          tag_names:         list[str], 要查的位号名, 一次可多个
          beg_time:          起始时间 'yyyy-MM-dd HH:mm:ss'
          end_time:          结束时间 'yyyy-MM-dd HH:mm:ss'
          is_source:         是否原始数据, True=源数据, False=插值后
          number_to_string:  数值是否转字符串 (True=返回值是字符串)
          page:              页码 (从 1 开始)
          page_size:         每页条数 (数据点行数, 不是 tag 数)
          sort:              排序字段, 实际 API 忽略此参数, 固定返回最新在前

        返回: {tagName: {"pageNum", "pageSize", "totalPage", "total", "list": [data points]}}
        """
        return self._request(
            "POST",
            "/ibd-data-hub-web-v2.2/api/tag-value/getHistoryValueFromDB",
            body={
                "data": {
                    "tagNames": list(tag_names),
                    "begTime": beg_time,
                    "endTime": end_time,
                    "isSource": is_source,
                    "numberToString": number_to_string,
                },
                "requestBase": {"page": f"{page}-{page_size}", "sort": sort},
            },
            wrap=False,
        )

    def get_all_history(self, tag_names, beg_time: str, end_time: str,
                        is_source: bool = True, number_to_string: bool = False,
                        page_size: int = 2000) -> dict:
        """翻页拉取所有历史值, 返回 {tagName: [data points]}。

        每个 tag 的所有数据点 (按 API 返回顺序, 固定最新在前), 自动按 total 翻页。
        """
        result = {name: [] for name in tag_names}
        page = 1
        while True:
            page_data = self.get_history_value(
                tag_names=tag_names, beg_time=beg_time, end_time=end_time,
                is_source=is_source, number_to_string=number_to_string,
                page=page, page_size=page_size, sort="-appTime",
            )
            any_remaining = False
            for tag_name, info in page_data.items():
                lst = info.get("list", [])
                result[tag_name].extend(lst)
                if len(result[tag_name]) < info.get("total", 0):
                    any_remaining = True
            if not any_remaining:
                break
            page += 1
        return result


if __name__ == "__main__":
    # 烟雾测试: 登录 + 列前 5 个位号
    api = AlgAPI("http://10.10.58.179:31501")
    api.login("admin", "123456", "")
    print(f"[login] OK, token 长度 {len(api.token)}")

    result = api.list_tags(page=1, page_size=5)
    records = result.get("records", [])
    total = result.get("total")
    print(f"[list_tags] total={total}, first {len(records)}:")
    for t in records:
        print(f"  id={t.get('id'):>6} {t.get('tagName'):<25s} dataType={t.get('dataType')} tagType={t.get('tagType')}")
