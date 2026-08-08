"""tpt_api 公共数据模型。

与 Go 版 tptapi/{users,algorithms,datahub}.go 一一对应。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# === TPT admin 用户管理 ===

@dataclass
class User:
    """listByOrgId 返回的单条记录。"""
    id: int = 0
    username: str = ""
    code: str = ""
    nickName: str = ""
    email: str = ""
    phone: str = ""
    gender: int = 0
    status: int = 0
    type: int = 0
    tenantId: str = ""
    delFlag: int = 0
    createTime: str = ""
    loginTime: str = ""
    updateTime: str = ""

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "User":
        return cls(
            id=int(d.get("id", 0)),
            username=d.get("username", "") or "",
            code=d.get("code", "") or "",
            nickName=d.get("nickName", "") or "",
            email=d.get("email", "") or "",
            phone=d.get("phone", "") or "",
            gender=int(d.get("gender", 0) or 0),
            status=int(d.get("status", 0) or 0),
            type=int(d.get("type", 0) or 0),
            tenantId=d.get("tenantId", "") or "",
            delFlag=int(d.get("delFlag", 0) or 0),
            createTime=d.get("createTime", "") or "",
            loginTime=d.get("loginTime", "") or "",
            updateTime=d.get("updateTime", "") or "",
        )


@dataclass
class UserDraft:
    """create 时的输入载荷。

    类型 / 组织 / 角色均有默认值，可全部不传：

    - type:      用户类型，"2"=普通用户（默认）；"1"=管理员
    - orgIds:    组织 ID 列表，默认 [1]（默认组织）
    - orgName:   组织名，默认"默认组织"，须与 orgIds 配套
    - roleIds:   角色 ID，"5"=普通用户角色（默认）；"4"=管理员角色
    """
    username: str
    password: str
    nickName: str
    email: str = ""
    phone: str = ""
    type: str = "2"
    orgIds: list[int] = field(default_factory=lambda: [1])
    orgName: str = "默认组织"
    roleIds: str = "5"


@dataclass
class Role:
    """umsRole/page 返回的单条角色记录。"""
    id: int = 0
    name: str = ""
    code: str = ""
    description: str = ""
    status: int = 0
    createTime: str = ""
    updateTime: str = ""
    tenantId: str = ""

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Role":
        return cls(
            id=int(d.get("id", 0)),
            name=d.get("name", "") or "",
            code=d.get("code", "") or "",
            description=d.get("description", "") or "",
            status=int(d.get("status", 0) or 0),
            createTime=d.get("createTime", "") or "",
            updateTime=d.get("updateTime", "") or "",
            tenantId=d.get("tenantId", "") or "",
        )


@dataclass
class RolePageResponse:
    """umsRole/page 返回的角色分页结构（字段与 PageResponse 对齐）。"""
    records: list[Role] = field(default_factory=list)
    total: int = 0
    size: int = 0
    current: int = 0
    pages: int = 0

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "RolePageResponse":
        records = [Role.from_dict(r) for r in (d.get("records") or [])]
        return cls(
            records=records,
            total=int(d.get("total", 0) or 0),
            size=int(d.get("size", 0) or 0),
            current=int(d.get("current", 0) or 0),
            pages=int(d.get("pages", 0) or 0),
        )


@dataclass
class PageResponse:
    """list 接口的 MyBatis Page 结构。"""
    records: list[User] = field(default_factory=list)
    total: int = 0
    size: int = 0
    current: int = 0
    pages: int = 0
    orders: list[Any] = field(default_factory=list)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "PageResponse":
        records = [User.from_dict(r) for r in (d.get("records") or [])]
        return cls(
            records=records,
            total=int(d.get("total", 0) or 0),
            size=int(d.get("size", 0) or 0),
            current=int(d.get("current", 0) or 0),
            pages=int(d.get("pages", 0) or 0),
            orders=list(d.get("orders") or []),
        )


@dataclass
class LoginResponse:
    """登录接口 content 字段的形态。"""
    token: str = ""


@dataclass
class AdminInfo:
    """umsAdmin/info 返回的当前登录用户信息。"""
    id: int = 0
    code: str = ""
    username: str = ""
    nickName: str = ""
    type: int = 0
    gender: int = 0
    icon: str = ""
    menus: list[Any] = field(default_factory=list)
    roles: list[dict[str, Any]] = field(default_factory=list)
    umsOrganization: dict[str, Any] = field(default_factory=dict)
    additional: str = ""

    @property
    def additional_dict(self) -> dict[str, Any]:
        import json as _json
        if not self.additional:
            return {}
        try:
            return _json.loads(self.additional)
        except Exception:
            return {}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "AdminInfo":
        return cls(
            id=int(d.get("id", 0) or 0),
            code=d.get("code", "") or "",
            username=d.get("username", "") or "",
            nickName=d.get("nickName", "") or "",
            type=int(d.get("type", 0) or 0),
            gender=int(d.get("gender", 0) or 0),
            icon=d.get("icon", "") or "",
            menus=list(d.get("menus") or []),
            roles=list(d.get("roles") or []),
            umsOrganization=dict(d.get("umsOrganization") or {}),
            additional=d.get("additional", "") or "",
        )


@dataclass
class OperationStatus:
    """create / resetPwd / deleteTags 等写操作的状态返回（无 content）。"""
    code: str = ""
    msg: str = ""


# === alg-manager 算法管理 ===

# Algorithm 是 list 接口返回的单条记录（字段集与平台返回一致，按需取用）。
Algorithm = dict[str, Any]


# === ibd-data-hub tag + 历史值 ===

@dataclass
class ImportResponse:
    """导入端点响应（写操作统一解析）。"""
    status_code: int = 0
    code: str | None = None
    msg: str = ""
    is_success: bool = False
    data: Any = None
    raw: dict[str, Any] | None = None


# 平台 dataType 枚举（实测 2026-06-27 / String+DateTime 2026-07-10）。
DataTypes: dict[str, int] = {
    "BOOLEAN": 1, "S_BYTE": 2, "BYTE": 3, "SHORT": 4, "U_SHORT": 5,
    "INT": 6, "U_INT": 7, "LONG": 8, "U_LONG": 9, "FLOAT": 10, "DOUBLE": 11,
    "STRING": 12, "DATE_TIME": 13,
}

# 平台 tagType 枚举。
TagTypes: dict[str, int] = {
    "一次位号": 1,
    "虚位号": 4,
}

# 全量扫描时遍历的 tagType 集合（避免 get_all_tags 默认空 data 漏掉其它类）。
DefaultTagTypesAll: tuple[int, ...] = (1, 4, 0, 2, 3, 5)


# === ibd-data-hub 数据源 (ds-info) ===

@dataclass
class DsInfo:
    """ds-info 单条记录。

    字段含义：
      id:           数据源 ID
      name:         显示名（与 dsName 通常一致）
      dsName:       数据源名
      dsType:       数据源大类 (1=Real time database)
      dsTypeDesc:   数据源大类描述
      dsSubType:    数据源子类 (4=OPC-UA-Server)
      dsSubTypeDesc: 数据源子类描述
      dsTarUrl:     目标 URL（如 opc.tcp://host:port）
      dsStatus:     状态 (1=启用)
      alive:        是否在线
      supportSub:   是否支持订阅
      dsExtInfo:    扩展信息 dict
      createBy / updateBy: 操作人
      createTime / updateTime: 操作时间
    """
    id: int = 0
    name: str = ""
    dsName: str = ""
    dsType: int = 0
    dsTypeDesc: str = ""
    dsSubType: int = 0
    dsSubTypeDesc: str = ""
    dsTarUrl: str = ""
    dsStatus: int = 0
    alive: bool = False
    supportSub: bool = False
    dsExtInfo: dict[str, Any] = field(default_factory=dict)
    createBy: str = ""
    updateBy: str = ""
    createTime: str = ""
    updateTime: str = ""

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "DsInfo":
        return cls(
            id=int(d.get("id", 0) or 0),
            name=d.get("name", "") or "",
            dsName=d.get("dsName", "") or "",
            dsType=int(d.get("dsType", 0) or 0),
            dsTypeDesc=d.get("dsTypeDesc", "") or "",
            dsSubType=int(d.get("dsSubType", 0) or 0),
            dsSubTypeDesc=d.get("dsSubTypeDesc", "") or "",
            dsTarUrl=d.get("dsTarUrl", "") or "",
            dsStatus=int(d.get("dsStatus", 0) or 0),
            alive=bool(d.get("alive", False)),
            supportSub=bool(d.get("supportSub", False)),
            dsExtInfo=dict(d.get("dsExtInfo", {}) or {}),
            createBy=d.get("createBy", "") or "",
            updateBy=d.get("updateBy", "") or "",
            createTime=d.get("createTime", "") or "",
            updateTime=d.get("updateTime", "") or "",
        )


# 平台 dsType 枚举（实测）。
DsTypes: dict[str, int] = {
    "REAL_TIME_DB": 1,  # Real time database
}

# 平台 dsSubType 枚举（实测）。
DsSubTypes: dict[str, int] = {
    "OPC_UA_SERVER": 4,  # OPC-UA-Server
}
