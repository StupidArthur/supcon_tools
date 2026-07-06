"""USER_MANAGER TPT 后台接口封装。

将父级目录 common/api.py 的 AlgAPI（含 TPT 后台鉴权）引用进来，
再在子类 UserManagerAPI 上加 USER_MANAGER 专属方法（不改 common/api.py，
避免影响 alg_publish / alg_republish / data-hub-tool 等其他工具）。

USER_MANAGER 业务代码:
    from api import UserManagerAPI
    api = UserManagerAPI("https://supcontpt.supcon.com")
    api.login("admin", "xxx", tenant_id="A54Z32M2")
    api.i_get_all_users()
"""

import os
import sys

# 把父级目录（alg_update）加进 sys.path，从而可以引用 common.api
_PARENT = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_PARENT)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from common.api import AlgAPI, list_local_resources  # noqa: E402,F401


class UserManagerAPI(AlgAPI):
    """USER_MANAGER 专用 API。

    继承通用 AlgAPI 拿到 TPT 鉴权 (`login`)、HTTP 客户端、鉴权错误识别等基础设施，
    在此之上加用户管理相关接口。命名约定: 用户域方法统一以 `i_` 前缀。
    """

    def __init__(self, base_url: str):
        super().__init__(base_url)
        # 用户缓存: i_get_all_users 写入
        self.users = []          # list[dict]
        self.user_map = {}       # userId -> user 完整信息

    # === 用户管理 ===

    def i_list_users(
        self,
        page: int = 1,
        page_size: int = 10,
        org_id: str = "",
        keyword: str = "",
        sort: str = "",
        search_fields: tuple = ("nickName", "username", "phone", "email"),
    ) -> dict:
        """分页列后台用户 (POST /xpt-system/api/system-manager/umsAdmin/listByOrgId)。

        参数:
          page:           页码 (从 1 开始)
          page_size:      每页条数 (requestBase.page = "page-page_size")
          org_id:         组织 id, 空串=全部组织
          keyword:        模糊搜索词, 跨 search_fields 任一字段命中即返回; 空串=不过滤
          sort:           排序字符串, 如 "-createTime"; 空串=默认
          search_fields:  模糊搜索作用字段; 默认 4 个常见字段
                          平台语法: *field* 表示对该字段做 LIKE, 多个用 "|" 拼接

        返回:
          content dict (MyBatis Page 结构):
            records:  list[dict], 每条一个用户
            total:    int, 总数
            size:     int, 页大小
            current:  int, 当前页
            pages:    int, 总页数
            orders:   list, 排序信息
        """
        field_keys = "|".join(f"*{f}*" for f in search_fields)
        admin_where = {field_keys: keyword} if keyword else {}
        return self._request(
            "POST",
            "/xpt-system/api/system-manager/umsAdmin/listByOrgId",
            body={
                "data": {"adminWhere": admin_where, "orgId": org_id},
                "requestBase": {"page": f"{page}-{page_size}", "sort": sort},
            },
            wrap=False,
        )

    def i_get_all_users(
        self,
        org_id: str = "",
        keyword: str = "",
        sort: str = "",
        search_fields: tuple = ("nickName", "username", "phone", "email"),
        page_size: int = 200,
    ) -> list:
        """自动翻页拉全部后台用户, 缓存到 self.users 和 self.user_map (按 id)。

        返回:
          list[dict], 全部用户。每条至少含 id / username / nickName / status / type 等。
        """
        all_records: list = []
        page = 1
        while True:
            result = self.i_list_users(
                page=page, page_size=page_size, org_id=org_id,
                keyword=keyword, sort=sort, search_fields=search_fields,
            )
            records = result.get("records", [])
            if not records:
                break
            all_records.extend(records)
            if len(records) < page_size:
                break
            page += 1
        self.users = all_records
        self.user_map = {u.get("id"): u for u in all_records if u.get("id") is not None}
        return all_records

    # 别名: get_users == i_get_all_users (同一函数对象)
    get_users = i_get_all_users

    def i_create_user(
        self,
        username: str,
        password: str,
        nick_name: str,
        org_ids: list = None,
        org_name: str = "默认组织",
        code: str = None,
        gender: str = "1",
        email: str = "",
        phone: str = "",
        status: int = 0,
        user_type: str = "2",
        role_ids: str = "",
        icon: str = "",
    ) -> dict:
        """创建后台用户 (POST /xpt-system/api/system-manager/umsAdmin)。

        参数:
          username:   登录账号 (必填)
          password:   明文密码 (必填, 平台 UMS 不在前端做 hash)
          nick_name:  昵称 / 显示名 (必填)
          org_ids:    组织 id 列表, 默认 [1] (默认组织)
          org_name:   组织显示名, 默认 "默认组织"
          code:       用户 code; None=沿用 username
          gender:     "0"/"1", 字符串, 默认 "1"
          email:      邮箱, 默认 ""
          phone:      手机号, 默认 ""
          status:     0=启用 (默认), 1=禁用
          user_type:  用户类型, 默认 "2" (普通用户); 参数名避开 Python builtin `type`,
                      在请求体里仍以 `type` 提交
          role_ids:   角色 id, 字符串形态 (单值或逗号分隔), 默认 ""
          icon:       头像 URL, 默认 ""

        返回:
          状态 dict {isSuccess, success, code, requestId, msg}.
          注意: 响应不含 userId, 创建后需调 i_get_all_users() 通过 username 反查 id。

        抛出:
          httpx.HTTPStatusError / Exception(code!=00000) — 由 _request 统一处理。
        """
        if org_ids is None:
            org_ids = [1]
        if code is None:
            code = username
        return self._request(
            "POST",
            "/xpt-system/api/system-manager/umsAdmin",
            body={
                "status": status,
                "orgIds": org_ids,
                "username": username,
                "code": code,
                "nickName": nick_name,
                "password": password,
                "gender": gender,
                "email": email,
                "phone": phone,
                "orgName": org_name,
                "type": user_type,
                "roleIds": role_ids,
                "icon": icon,
            },
            wrap=True,  # _request 自动包成 {"data": ...}
        )

    def i_reset_password(
        self,
        user_id: int,
        new_password: str,
        confirm_password: str = None,
    ) -> dict:
        """重置用户密码 (POST /xpt-system/api/system-manager/umsAdmin/resetPwd)。

        参数:
          user_id:           目标用户 id (不是 username; 不知 id 时先调 i_get_all_users())
          new_password:      新密码 (明文, 平台 UMS 不做 hash)
          confirm_password:  确认密码; None=沿用 new_password

        返回:
          状态 dict {isSuccess, success, code, requestId, msg}.
          注意: 响应不含修改结果详情, 需用新密码登录来确认重置生效。

        抛出:
          httpx.HTTPStatusError / Exception(code!=00000) — 由 _request 统一处理。
        """
        if confirm_password is None:
            confirm_password = new_password
        return self._request(
            "POST",
            "/xpt-system/api/system-manager/umsAdmin/resetPwd",
            body={
                "id": user_id,
                "newPwd": new_password,
                "confirmPwd": confirm_password,
            },
            wrap=True,
        )


__all__ = ["AlgAPI", "UserManagerAPI", "list_local_resources"]


if __name__ == "__main__":
    # 冒烟测试: 登录 + 列全部用户
    api = UserManagerAPI("https://supcontpt.supcon.com")
    api.login("admin", "tpt@2026", tenant_id="A54Z32M2")
    print(f"[login] OK, token 长度 {len(api.token)}")

    users = api.i_get_all_users(page_size=200)
    print(f"[i_get_all_users] total={len(users)}")
    for u in users[:5]:
        print(f"  id={u.get('id'):>6}  username={u.get('username'):<20}  nick={u.get('nickName')}")
