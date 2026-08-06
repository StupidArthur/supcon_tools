"""cubapi/cub-data 接口（SupCon Cup 中控杯数据接口）。

端点（GET/POST 混合，统一 base URL /cubapi）：

1. datahub 读写位号接口 (Tag Value Controller)
   - GET  /cub-data/tag/readHisData        批量读位号历史值
   - GET  /cub-data/tag/readValues          读位号实时值
   - POST /cub-data/tag/writeValue          写入位号实时值

2. 评分中心 (Score Center Controller)
   - GET  /cub-data/score/getHistoryRecord  查询当前用户成绩记录
   - POST /cub-data/score/runAlgorithm      运行算法评估（已废弃，用 V2）
   - POST /cub-data/score/runAlgorithmV2    运行算法评估 v2（加载工况，2h 后定时计算）
   - POST /cub-data/score/clearMyRecords    清空当前用户成绩

3. 软测量评分 (File Controller)
   - GET  /cub-data/file/score              查询当前用户软测量评分（最新一条）
   - POST /cub-data/file/softSensorScore    软测量评分
   - GET  /cub-data/file/template           下载模板文件
   - POST /cub-data/file/upload             上传软测量预测数据文件

4. 成绩排行榜 (Ranking Controller)
   - GET  /cub-data/ranking/all             查询所有租户成绩排名

5. 评估配置 (Eval Config Controller)
   - GET  /cub-data/eval-config             查询评估配置
   - POST /cub-data/eval-config             更新评估配置

6. 鉴权调试 (Auth Controller)
   - GET  /cub-data/auth/info               解析 token 返回用户信息

7. 开发维护 (Dev Controller)
   - GET    /cub-data/dev/tenant-detail     查询指定租户得分详情
   - DELETE /cub-data/dev/cleanup-tenant    清空指定租户评分数据

8. 用户同步 (Auth User Sync Controller)
   - POST /cub-data/auth-user-sync/sync     手动触发同步 TPT 系统用户

鉴权与 tpt-admin / alg-manager / ibd-data-hub 共用同一套 Bearer token + tenant cookie，
登录后 AlgAPI 实例可直接调用本模块函数。

响应格式：统一响应体 {code: int, message: str, data: ...}，code=200 表示成功。
"""

from __future__ import annotations

import logging
import os
from typing import Any

from .client import AlgAPI

log = logging.getLogger(__name__)


# === cub-data 端点常量 ===

# 1. 位号读写 (Tag Value Controller)
CubDataReadHisDataPath = "/cubapi/cub-data/tag/readHisData"
CubDataReadValuesPath = "/cubapi/cub-data/tag/readValues"
CubDataWriteValuePath = "/cubapi/cub-data/tag/writeValue"

# 2. 评分中心 (Score Center Controller)
CubDataScoreHistoryPath = "/cubapi/cub-data/score/getHistoryRecord"
CubDataScoreRunAlgoPath = "/cubapi/cub-data/score/runAlgorithm"
CubDataScoreRunAlgoV2Path = "/cubapi/cub-data/score/runAlgorithmV2"
CubDataScoreClearPath = "/cubapi/cub-data/score/clearMyRecords"

# 3. 软测量评分 (File Controller)
CubDataFileScorePath = "/cubapi/cub-data/file/score"
CubDataFileSoftSensorScorePath = "/cubapi/cub-data/file/softSensorScore"
CubDataFileTemplatePath = "/cubapi/cub-data/file/template"
CubDataFileUploadPath = "/cubapi/cub-data/file/upload"

# 4. 成绩排行榜 (Ranking Controller)
CubDataRankingAllPath = "/cubapi/cub-data/ranking/all"

# 5. 评估配置 (Eval Config Controller)
CubDataEvalConfigPath = "/cubapi/cub-data/eval-config"

# 6. 鉴权调试 (Auth Controller)
CubDataAuthInfoPath = "/cubapi/cub-data/auth/info"

# 7. 开发维护 (Dev Controller)
CubDataDevTenantDetailPath = "/cubapi/cub-data/dev/tenant-detail"
CubDataDevCleanupTenantPath = "/cubapi/cub-data/dev/cleanup-tenant"

# 8. 用户同步 (Auth User Sync Controller)
CubDataAuthUserSyncPath = "/cubapi/cub-data/auth-user-sync/sync"


# === 1. 位号读写 (Tag Value Controller) ===


def read_history_data(
    api: AlgAPI,
    tag_names: list[str],
    start_time: str,
    end_time: str,
) -> Any:
    """批量读位号历史值（GET /cub-data/tag/readHisData）。

    一次查多个位号在指定时间范围内的历史值，5s 采集间隔，无分页。

    参数:
      tag_names:  位号名列表（如 ["FICQ_60402.PV", "LIC_60501.MV"]）；
                  传空列表时服务端使用默认位号列表
      start_time: 起始时间 yyyy-MM-dd HH:mm:ss
      end_time:   结束时间 yyyy-MM-dd HH:mm:ss

    返回: 统一响应体 dict，data 为 TagValueRow 列表，每项含 name/count/values[]。
          values 每条含 value/timeStamp/quality/alarm。
    """
    params = {
        "startTime": start_time,
        "endTime": end_time,
        "tagNames": ",".join(tag_names),
    }
    return api._request("GET", CubDataReadHisDataPath, params=params)


def read_realtime_values(
    api: AlgAPI,
    tag_names: list[str],
) -> Any:
    """读位号实时值（GET /cub-data/tag/readValues）。

    根据租户 ID（从 token 解析）和位号名列表读取实时值。

    参数:
      tag_names: 位号名列表

    返回: 统一响应体 dict，data 为位号实时值列表，每项含
          name/value/quality/timeStamp/alarm。
    """
    params = {"tagNames": ",".join(tag_names)}
    return api._request("GET", CubDataReadValuesPath, params=params)


def write_tag_value(
    api: AlgAPI,
    tag_name: str,
    value: str | int | float,
) -> Any:
    """写入位号实时值（POST /cub-data/tag/writeValue）。

    参数:
      tag_name: 位号名
      value:    位号值（会转为字符串传输）

    返回: 统一响应体 dict，data 为 true 表示写入成功。
    """
    params = {"tagName": tag_name, "value": str(value)}
    return api._request("POST", CubDataWriteValuePath, params=params)


# === 2. 评分中心 (Score Center Controller) ===


def get_score_history(api: AlgAPI) -> Any:
    """查询当前登录用户的成绩记录（GET /cub-data/score/getHistoryRecord）。

    用户 ID 由服务端从 JWT 令牌解析，无需传参。

    返回: 统一响应体 dict，data 为用户成绩记录列表，每项含
          id/userId/score/sci/se/ssafe/ssmi/status/algorithmType/
          startWorktime/endWorktime/algorithmStartTime/algorithmEndTime/
          isBest/retryCount/addTime/updateTime/tenantId/count。
          status: 1=评估中, 2=评估完成, 3=评估失败。
    """
    return api._request("GET", CubDataScoreHistoryPath)


def run_algorithm(
    api: AlgAPI,
    start_time: str,
    end_time: str,
) -> Any:
    """运行算法评估（POST /cub-data/score/runAlgorithm）。

    已废弃，请改用 run_algorithm_v2。
    用户 ID 由服务端从 JWT 解析，时间范围不能超过 2 小时。

    参数:
      start_time: 起始时间 yyyy-MM-dd HH:mm:ss
      end_time:   结束时间 yyyy-MM-dd HH:mm:ss

    返回: 统一响应体 dict，data 为算法运行结果，含
          code(0=成功,-1=失败)/message/score/remainingTimes。
    """
    body = {"startTime": start_time, "endTime": end_time}
    return api._request("POST", CubDataScoreRunAlgoPath, body=body, wrap=False)


def run_algorithm_v2(api: AlgAPI) -> Any:
    """运行算法评估 v2（POST /cub-data/score/runAlgorithmV2）。

    加载工况，2 小时后定时任务调用算法计算结果。
    用户 ID 由服务端从 JWT 解析，无需传参。

    返回: 统一响应体 dict，data 为用户成绩记录（status=1 评估中），
          字段同 get_score_history。
    """
    return api._request("POST", CubDataScoreRunAlgoV2Path)


def clear_my_records(api: AlgAPI) -> Any:
    """清空当前登录用户的成绩（POST /cub-data/score/clearMyRecords）。

    删除当前登录用户在 user_score_record、user_file 表的所有数据，
    并清理已上传的磁盘文件。

    返回: 统一响应体 dict，data 为 true 表示清空成功。
    """
    return api._request("POST", CubDataScoreClearPath)


# === 3. 软测量评分 (File Controller) ===


def get_soft_sensor_score(api: AlgAPI) -> Any:
    """查询当前登录用户软测量评分（GET /cub-data/file/score）。

    返回最新一条上传文件记录及其评分。

    返回: 统一响应体 dict，data 为用户上传文件对象，含
          id/userId/fileName/filePath/uploadTime/score/tenantId。
          score: 0-10 保留两位小数，未评分时为 null。
    """
    return api._request("GET", CubDataFileScorePath)


def run_soft_sensor_score(api: AlgAPI) -> Any:
    """软测量评分（POST /cub-data/file/softSensorScore）。

    读取当前登录用户最新上传文件的 Excel B 列数据（从第 3 行开始）作为 REFERENCE.PV，
    从考核对比的产品浓度标准文件.csv 读取 T602D_C4.PV 数据，
    调用 concentration_fit_py 算法计算评分并更新到 user_file 记录。

    返回: 统一响应体 dict，data 为算法运行结果，含
          code(0=成功,-1=失败)/message/score/remainingTimes。
    """
    return api._request("POST", CubDataFileSoftSensorScorePath)


def download_template(
    api: AlgAPI,
    save_path: str | None = None,
) -> bytes:
    """下载模板文件（GET /cub-data/file/template）。

    参数:
      save_path: 保存路径，None=不存文件只返回 bytes

    返回: 模板文件 raw bytes。
    """
    content = api._download("GET", CubDataFileTemplatePath)
    if save_path:
        with open(save_path, "wb") as f:
            f.write(content)
    return content


def upload_score_file(
    api: AlgAPI,
    file_path: str,
) -> Any:
    """上传软测量预测数据文件（POST /cub-data/file/upload）。

    上传 Excel 文件，B 列从第 3 行开始为预测数据（REFERENCE.PV）。

    参数:
      file_path: Excel 文件路径

    返回: 统一响应体 dict，data 为用户上传文件对象，含
          id/userId/fileName/filePath/uploadTime/score(null)/tenantId。
    """
    url = f"{api.base_url}/{CubDataFileUploadPath.lstrip('/')}"
    with open(file_path, "rb") as f:
        files = {"file": (os.path.basename(file_path), f,
                          "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
        r = api.client.post(url, files=files)
    r.raise_for_status()
    return r.json()


# === 4. 评估配置 (Eval Config Controller) ===


def get_eval_config(api: AlgAPI) -> Any:
    """查询评估配置（GET /cub-data/eval-config）。

    读取单行评估配置（id=1），不存在时自动初始化默认配置。

    返回: 统一响应体 dict，data 为评估配置对象，含
          id/pracLoadEnabled/examLoadEnabled/evalDurationMinutes/addTime/updateTime。
          pracLoadEnabled: 1=开启练习工况, 0=关闭。
          examLoadEnabled: 1=开启考试工况, 0=关闭。
          evalDurationMinutes: 评估时间段（分钟）。
    """
    return api._request("GET", CubDataEvalConfigPath)


def update_eval_config(
    api: AlgAPI,
    prac_load_enabled: int | None = None,
    exam_load_enabled: int | None = None,
    eval_duration_minutes: int | None = None,
) -> Any:
    """更新评估配置（POST /cub-data/eval-config）。

    仅允许修改 pracLoadEnabled / examLoadEnabled / evalDurationMinutes 三个字段，
    id 由服务端强制为 1（单行配置表约束）。

    参数:
      prac_load_enabled:      练习工况开关（1=开启, 0=关闭），None=不修改
      exam_load_enabled:      考试工况开关（1=开启, 0=关闭），None=不修改
      eval_duration_minutes:  评估时间段（分钟），None=不修改

    返回: 统一响应体 dict，data 为更新后的评估配置对象。
    """
    body: dict[str, Any] = {}
    if prac_load_enabled is not None:
        body["pracLoadEnabled"] = prac_load_enabled
    if exam_load_enabled is not None:
        body["examLoadEnabled"] = exam_load_enabled
    if eval_duration_minutes is not None:
        body["evalDurationMinutes"] = eval_duration_minutes
    return api._request("POST", CubDataEvalConfigPath, body=body, wrap=False)


# === 5. 鉴权调试 (Auth Controller) ===


def get_auth_info(api: AlgAPI) -> Any:
    """解析 Authorization 头中的 token（GET /cub-data/auth/info）。

    解析 JWT 令牌并返回其中的用户信息。

    返回: 统一响应体 dict，data 为鉴权信息对象，含
          userId/username/nickName/type/exp/expired/valid/message。
    """
    return api._request("GET", CubDataAuthInfoPath)


# === 6. 用户同步 (Auth User Sync Controller) ===


def sync_auth_users(
    api: AlgAPI,
    update_time_begin: str = "",
) -> Any:
    """手动触发同步 TPT 系统用户（POST /cub-data/auth-user-sync/sync）。

    立即从 TPT 系统拉取用户列表并同步到本服务 auth_user 表，
    返回同步成功的用户数量；失败返回 -1。

    参数:
      update_time_begin: 查询起始时间 yyyy-MM-dd HH:mm:ss，
                         不传则取当前时间。
                         调试建议传较早时间以拉全量，如 "2020-01-01 00:00:00"

    返回: 统一响应体 dict，data 为同步成功的用户数量（int）。
    """
    params: dict[str, Any] = {}
    if update_time_begin:
        params["updateTimeBegin"] = update_time_begin
    return api._request("POST", CubDataAuthUserSyncPath, params=params)


# === 4. 成绩排行榜 (Ranking Controller) ===


def get_ranking_all(api: AlgAPI) -> Any:
    """查询所有租户成绩排名（GET /cub-data/ranking/all）。

    返回所有租户的控制最优成绩、软测量成绩、总分和排名。

    返回: 统一响应体 dict，data 为租户成绩排名列表，每项含：
          tenantId / controlScore / softSensorScore / totalScore / rank。
          - controlScore: 控制最优成绩（is_best=true 的最高分），无成绩时 null
          - softSensorScore: 软测量成绩（user_file 最高分），无成绩时 null
          - totalScore: 总分 = 控制最优×0.8 + 软测量×0.2，缺失项按 0，保留 5 位小数
          - rank: 排名（按总分降序，同分同排名）
    """
    return api._request("GET", CubDataRankingAllPath)


# === 7. 开发维护 (Dev Controller) ===


def get_tenant_detail(
    api: AlgAPI,
    tenant_id: str,
) -> Any:
    """查询指定租户的得分详情（GET /cub-data/dev/tenant-detail）。

    需要管理员权限。返回指定租户的控制成绩记录和软测量评分记录。

    参数:
      tenant_id: 租户 ID

    返回: 统一响应体 dict，data 为 Map，包含控制成绩记录和软测量评分记录。
    """
    params = {"tenantId": tenant_id}
    return api._request("GET", CubDataDevTenantDetailPath, params=params)


def cleanup_tenant(
    api: AlgAPI,
    tenant_id: str,
) -> Any:
    """清空指定租户的评分相关数据（DELETE /cub-data/dev/cleanup-tenant）。

    需要管理员权限。删除指定租户的成绩记录、上传文件记录及磁盘文件。

    参数:
      tenant_id: 租户 ID

    返回: 统一响应体 dict，data 为清理数量统计（Map<string,int>）。
    """
    params = {"tenantId": tenant_id}
    return api._request("DELETE", CubDataDevCleanupTenantPath, params=params)
