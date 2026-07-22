"""
工业级 PID 控制算法（对齐中控 ECS-700）

核心特性：
- 增量式 PID（ΔMV = (100/PB) × (ΔE + Ts/TI·E + ΔU)）
- PB 是比例度（Kp = 100/PB），不是比例增益
- ECS-700 MODE 1~8：OOS / IMAN / TR / MAN / AUTO / CAS / RCAS / ROUT
- AUTO = MODE（兼容别名，非布尔），CAS = 1 if MODE==6 else 0（派生）
- 模式切换开关：SWAM/SWSV（MAN: SWAM=OFF；AUTO: SWAM=ON+SWSV=OFF；CAS: SWAM=ON+SWSV=ON）
- AUTO 用本地 SV，CAS/RCAS 用 CSV（同时镜像到对外 SV）
- 工程量程换算（SVSCH/SVSCL、MVSCH/MVSCL）+ 操作限幅（SVH/SVL、MVH/MVL）
- 正反作用 SWPN：0=正作用，1=反作用
- 不完全微分（TD=0 时关闭）
- 冷启动自动模式保留首次比例响应
- 手动类模式 → 自动类模式无扰切换
- 抗积分饱和（饱和时取消同向积分）
- 在线量程变化时保持工程量 MV 连续
- 运行时非法参数自动恢复上次有效值并记录日志
- NaN/Inf 不得传播到最终 MV
"""

from __future__ import annotations

import math
from typing import Any, Dict, Optional

from components.utils.logger import get_logger
from controller.instance import InstanceRegistry
from .base import BaseProgram

logger = get_logger(name="pid")


# 合法的 ECS-700 MODE 数值
_VALID_MODES = {1, 2, 3, 4, 5, 6, 7, 8}
# 手动类模式（不执行 PID，跟踪 MV）
_MANUAL_MODES = {2, 3, 4, 8}
# 自动类模式（执行 PID）
_AUTOMATIC_MODES = {5, 6, 7}


def _is_finite_number(value: Any) -> bool:
    """判断 value 是否为有限数值。"""
    if isinstance(value, bool):
        # bool 是 int 子类，但 PID 参数不允许布尔充当数值
        return False
    try:
        f = float(value)
    except (TypeError, ValueError):
        return False
    return math.isfinite(f)


def _clamp(value: float, low: float, high: float) -> float:
    """限制到 [low, high]。"""
    if value < low:
        return low
    if value > high:
        return high
    return value


def _parse_mode(value: Any) -> Optional[int]:
    """
    严格解析 MODE。

    必须同时满足：
    1. 可转换为 float
    2. 有限数值
    3. 本身为整数（is_integer()）
    4. 位于 1~8

    Returns:
        合法时返回 int，非法时返回 None。
    """
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None

    if not math.isfinite(number):
        return None

    if not number.is_integer():
        return None

    mode = int(number)

    if mode not in _VALID_MODES:
        return None

    return mode


class PID(BaseProgram):
    """
    工业级 PID 控制器（对齐中控 ECS-700）。

    - PB：比例度（%），Kp = 100/PB，PB 越小比例作用越强
    - TI：积分时间（秒），TI=0 关闭积分
    - TD：微分时间（秒），KD：微分滤波系数
    - MODE：ECS-700 工作模式 1~8
    - SWPN：正反作用，0=正作用，1=反作用
    - AUTO：MODE 的兼容别名（数值同 MODE）
    - CAS：派生状态，MODE=6 时为 1，否则为 0
    - AUTO 用 SV；CAS/RCAS 用 CSV（同时镜像到对外 SV）
    """

    # 文档属性
    name = "pid"
    chinese_name = "PID控制器（ECS-700对齐）"
    doc = """
# 工业级 PID 控制器

对齐中控 ECS-700 常规 PID 功能块的核心行为，采用增量式算法。

## 关键参数语义

- **PB**：比例度（%），`Kp = 100/PB`。PB 越小比例作用越强。要求 PB > 0。
- **TI**：积分时间（秒），TI=0 时关闭积分。
- **TD**：微分时间（秒），KD：微分滤波系数（默认 10）。TD=0 时关闭微分。
- **MODE**：ECS-700 工作模式（1~8），必须为整数。
- **SWPN**：正反作用。0=正作用（PV↑→MV↑），1=反作用（PV↑→MV↓）。
- **AUTO**：MODE 的兼容别名（数值同 MODE，非布尔）。
- **CAS**：派生状态，MODE=6 时为 1，否则为 0。
- **SVSCH/SVSCL**：PV/SV 工程量程上下限。
- **MVSCH/MVSCL**：MV 工程量程上下限。
- **SVH/SVL**：SV 操作限幅上下限。
- **MVH/MVL**：MV 实际输出限幅上下限。

## MODE 数值含义

| MODE | 名称 | 行为 |
| ----: | ---- | ---- |
| 1 | OOS  | 保持最后有效 MV，不执行 PID |
| 2 | IMAN | 手动类模式，外部写 MV |
| 3 | TR   | 跟踪当前外部 MV |
| 4 | MAN  | 手动模式，外部写 MV |
| 5 | AUTO | 自动模式，使用本地 SV |
| 6 | CAS  | 串级模式，使用 CSV |
| 7 | RCAS | 远程外给定，使用 CSV |
| 8 | ROUT | 远程手动模式 |

## 模式切换开关（SWAM / SWSV）

MODE 为状态显示；主动切换 MAN/AUTO/CAS 时写入开关（ON=1，OFF=0）：

| 命令 | 写入 | 期望 MODE |
| ---- | ---- | --------: |
| MAN  | SWAM=OFF | 4 |
| AUTO | SWAM=ON，SWSV=OFF | 5 |
| CAS  | SWAM=ON，SWSV=ON | 6 |

确认以运行时快照中的 MODE 为准，不得提前伪造成功。

## SV/CSV 来源

- AUTO 模式使用本地 `SV`（保存在 `_local_sv`）。
- CAS/RCAS 模式使用 `CSV`，并镜像到对外 `SV`。
- 从 CAS 返回 AUTO 时恢复此前保存的 `_local_sv`。
- CAS 模式下写 `SV` 可以更新"未来返回 AUTO 时使用的本地 SV"，但不能改变当前 CAS 有效设定值。

## 使用示例

```yaml
- name: pid1
  type: PID
  params:
    PB: 416.67
    TI: 30.0
    TD: 0.15
    KD: 10.0
    MODE: 5
    SWPN: 1
    SVSCL: 0.0
    SVSCH: 2.0
    SVL: 0.0
    SVH: 2.0
    MVSCL: 0.0
    MVSCH: 100.0
    MVL: 0.0
    MVH: 100.0
  inputs:
    PV: tank_1.level
```
"""
    params_table = """
| 参数名 | 含义 | 默认值 |
|--------|------|--------|
| PV | 过程变量，每周期可由 `execute(PV=...)` 更新 | 0.0 |
| SV | AUTO模式本地设定值 | 0.0 |
| CSV | CAS/RCAS模式外部设定值 | 0.0 |
| MV | 操作变量（输出） | 0.0 |
| PB | 比例度（%），Kp=100/PB | 100.0 |
| TI | 积分时间（秒），0=关闭 | 0.0 |
| TD | 微分时间（秒），0=关闭 | 0.0 |
| KD | 微分滤波系数，默认10 | 10.0 |
| MODE | ECS-700工作模式 1~8 | 5 |
| SWPN | 正反作用：0=正作用，1=反作用 | 1 |
| AUTO | MODE的兼容别名（派生） | 5 |
| CAS | 串级状态（派生） | 0 |
| SVSCH | PV/SV工程量程上限 | 100.0 |
| SVSCL | PV/SV工程量程下限 | 0.0 |
| MVSCH | MV工程量程上限 | 100.0 |
| MVSCL | MV工程量程下限 | 0.0 |
| SVH | SV操作上限 | 100.0 |
| SVL | SV操作下限 | 0.0 |
| MVH | MV输出上限 | 100.0 |
| MVL | MV输出下限 | 0.0 |
"""

    stored_attributes = [
        "PV",
        "SV",
        "CSV",
        "MV",
        "PB",
        "TI",
        "TD",
        "KD",
        "MODE",
        "AUTO",
        "CAS",
        "SWPN",
        "SWAM",
        "SWSV",
        "SVSCH",
        "SVSCL",
        "MVSCH",
        "MVSCL",
        "SVH",
        "SVL",
        "MVH",
        "MVL",
    ]

    input_schema = [
        {"name": "PV", "type": "float", "connectable": True, "desc": "过程测量值"},
        {"name": "SV", "type": "float", "connectable": True, "desc": "AUTO模式本地设定值"},
        {"name": "CSV", "type": "float", "connectable": True, "desc": "CAS/RCAS模式外部设定值"},
        {"name": "MODE", "type": "float", "connectable": False, "desc": "ECS-700工作模式"},
        {"name": "SWPN", "type": "float", "connectable": False, "desc": "正反作用：0=正作用，1=反作用"},
    ]

    param_descriptions = {
        "PV": "过程变量(当前值)",
        "SV": "设定值(对外反映当前有效SV)",
        "CSV": "CAS/RCAS模式外部设定值",
        "MV": "操作变量(输出值)",
        "PB": "比例度(%)，Kp=100/PB",
        "TI": "积分时间(s)，0=关闭",
        "TD": "微分时间(s)，0=关闭",
        "KD": "微分滤波系数",
        "MODE": "ECS-700工作模式 1~8",
        "AUTO": "MODE的兼容别名(派生)",
        "CAS": "串级状态(派生)，MODE=6时为1",
        "SWPN": "正反作用：0=正，1=反",
        "SWAM": "手动/自动切换开关：0=OFF→MAN，1=ON→自动类",
        "SWSV": "设定来源开关：0=OFF→AUTO，1=ON→CAS（需 SWAM=ON）",
        "SVSCH": "PV/SV工程量程上限",
        "SVSCL": "PV/SV工程量程下限",
        "MVSCH": "MV工程量程上限",
        "MVSCL": "MV工程量程下限",
        "SVH": "SV操作上限",
        "SVL": "SV操作下限",
        "MVH": "MV输出上限",
        "MVL": "MV输出下限",
    }

    default_params: Dict[str, Any] = {
        "PV": 0.0,
        "SV": 0.0,
        "CSV": 0.0,
        "MV": 0.0,
        "PB": 100.0,
        "TI": 0.0,
        "TD": 0.0,
        "KD": 10.0,
        # 工具默认直接运行，避免现有 YAML 未配置 MODE 时停止计算
        "MODE": 5,
        # ECS-700：ON 为反作用，OFF 为正作用
        "SWPN": 1,
        # 模式切换开关：与 MODE=5(AUTO) 对齐
        "SWAM": 1,
        "SWSV": 0,
        "SVSCH": 100.0,
        "SVSCL": 0.0,
        "MVSCH": 100.0,
        "MVSCL": 0.0,
        "SVH": 100.0,
        "SVL": 0.0,
        "MVH": 100.0,
        "MVL": 0.0,
        # 派生属性，实际值每周期由 MODE 覆盖
        "AUTO": 5,
        "CAS": 0,
    }

    def __init__(self, cycle_time: float, **kwargs: Any) -> None:
        """
        初始化 PID。

        Args:
            cycle_time: 控制器周期（秒）
            **kwargs: 其他参数（来自 DSL 的 init_args/params），覆盖 default_params
        """
        super().__init__(cycle_time, **kwargs)

        # 初始化校验
        self._validate_init_params()

        # 规范化 MODE 为整数
        self.MODE = _parse_mode(self.MODE)
        if self.MODE is None:
            self.MODE = 5
        self.AUTO = int(self.MODE)
        self._sync_switches_from_mode(int(self.MODE), force=True)
        self._last_swam = self._as_on_off(self.SWAM)
        self._last_swsv = self._as_on_off(self.SWSV)

        # 内部状态（不暴露到 stored_attributes / OPC UA / YAML）
        self._prev_error_pct: float = 0.0
        self._prev_derivative_state: float = 0.0
        self._mv_pct: float = self._engineering_mv_to_pct(self.MV)
        self._previous_mode: Optional[int] = None
        self._initialized: bool = False
        # 本地 SV（AUTO 模式使用），从初始 SV 取值
        self._local_sv: float = float(self.SV)
        # 上一周期主动发布到 self.SV 的值，用于识别周期之间是否发生外部写入
        self._last_published_sv: float = float(self.SV)
        # SV 量程变化标志（由 _validate_or_restore_runtime_params 设置）
        self._sv_scale_changed: bool = False
        # 上次有效的过程量 / 外部设定 / 操作变量（用于 NaN/Inf 恢复）
        self._last_valid_pv: float = float(self.PV)
        self._last_valid_csv: float = float(self.CSV)
        self._last_valid_mv: float = float(self.MV)
        # 上次有效运行参数（运行时非法写值时回退）
        self._last_valid_params: Dict[str, float] = self._snapshot_runtime_params()

    # ------------------------------------------------------------------
    # 校验
    # ------------------------------------------------------------------
    def _validate_init_params(self) -> None:
        """构造时参数校验，失败抛 ValueError。"""
        if not _is_finite_number(self.cycle_time) or float(self.cycle_time) <= 0:
            raise ValueError(
                f"PID参数无效: cycle_time 必须大于0，实际值={self.cycle_time!r}"
            )

        checks = [
            ("PB", self.PB),
            ("TI", self.TI),
            ("TD", self.TD),
            ("KD", self.KD),
            ("PV", self.PV),
            ("SV", self.SV),
            ("CSV", self.CSV),
            ("MV", self.MV),
            ("SWPN", self.SWPN),
            ("SVSCH", self.SVSCH),
            ("SVSCL", self.SVSCL),
            ("MVSCH", self.MVSCH),
            ("MVSCL", self.MVSCL),
            ("SVH", self.SVH),
            ("SVL", self.SVL),
            ("MVH", self.MVH),
            ("MVL", self.MVL),
        ]
        for name, value in checks:
            if not _is_finite_number(value):
                raise ValueError(
                    f"PID参数无效: {name} 必须为有限数值，实际值={value!r}"
                )

        pb = float(self.PB)
        ti = float(self.TI)
        td = float(self.TD)
        kd = float(self.KD)
        sv_scl = float(self.SVSCL)
        sv_sch = float(self.SVSCH)
        mv_scl = float(self.MVSCL)
        mv_sch = float(self.MVSCH)
        sv_l = float(self.SVL)
        sv_h = float(self.SVH)
        mv_l = float(self.MVL)
        mv_h = float(self.MVH)

        if pb <= 0:
            raise ValueError(f"PID参数无效: PB 必须大于0，实际值={self.PB!r}")
        if ti < 0:
            raise ValueError(f"PID参数无效: TI 必须>=0，实际值={self.TI!r}")
        if td < 0:
            raise ValueError(f"PID参数无效: TD 必须>=0，实际值={self.TD!r}")
        if kd < 0:
            raise ValueError(f"PID参数无效: KD 必须>=0，实际值={self.KD!r}")

        if sv_sch <= sv_scl:
            raise ValueError(
                f"PID参数无效: SVSCH 必须大于 SVSCL，实际值 SVSCH={sv_sch}, SVSCL={sv_scl}"
            )
        if mv_sch <= mv_scl:
            raise ValueError(
                f"PID参数无效: MVSCH 必须大于 MVSCL，实际值 MVSCH={mv_sch}, MVSCL={mv_scl}"
            )
        if sv_l < sv_scl:
            raise ValueError(
                f"PID参数无效: SVL 不得小于 SVSCL，实际值 SVL={sv_l}, SVSCL={sv_scl}"
            )
        if sv_h > sv_sch:
            raise ValueError(
                f"PID参数无效: SVH 不得大于 SVSCH，实际值 SVH={sv_h}, SVSCH={sv_sch}"
            )
        if sv_l > sv_h:
            raise ValueError(
                f"PID参数无效: SVL 不得大于 SVH，实际值 SVL={sv_l}, SVH={sv_h}"
            )
        if mv_l < mv_scl:
            raise ValueError(
                f"PID参数无效: MVL 不得小于 MVSCL，实际值 MVL={mv_l}, MVSCL={mv_scl}"
            )
        if mv_h > mv_sch:
            raise ValueError(
                f"PID参数无效: MVH 不得大于 MVSCH，实际值 MVH={mv_h}, MVSCH={mv_sch}"
            )
        if mv_l > mv_h:
            raise ValueError(
                f"PID参数无效: MVL 不得大于 MVH，实际值 MVL={mv_l}, MVH={mv_h}"
            )

        mode = _parse_mode(self.MODE)
        if mode is None:
            raise ValueError(
                f"PID参数无效: MODE 必须为 1..8 整数，实际值={self.MODE!r}"
            )

    def _snapshot_runtime_params(self) -> Dict[str, float]:
        """记录当前有效的运行时参数。"""
        return {
            "PB": float(self.PB),
            "TI": float(self.TI),
            "TD": float(self.TD),
            "KD": float(self.KD),
            "MODE": float(self.MODE),
            "SWPN": float(self.SWPN),
            "SVSCH": float(self.SVSCH),
            "SVSCL": float(self.SVSCL),
            "MVSCH": float(self.MVSCH),
            "MVSCL": float(self.MVSCL),
            "SVH": float(self.SVH),
            "SVL": float(self.SVL),
            "MVH": float(self.MVH),
            "MVL": float(self.MVL),
        }

    def _validate_or_restore_runtime_params(self) -> None:
        """
        每周期执行前校验运行参数。

        合法则更新 _last_valid_params，并处理在线量程变化；
        非法则恢复上次有效值并记录日志。
        """
        # 逐项解析（失败时记录具体参数名和值）
        converted = {}
        for name, raw_value in [
            ("PB", self.PB), ("TI", self.TI), ("TD", self.TD), ("KD", self.KD),
            ("SVSCH", self.SVSCH), ("SVSCL", self.SVSCL),
            ("MVSCH", self.MVSCH), ("MVSCL", self.MVSCL),
            ("SVH", self.SVH), ("SVL", self.SVL),
            ("MVH", self.MVH), ("MVL", self.MVL),
        ]:
            try:
                converted[name] = float(raw_value)
            except (TypeError, ValueError):
                self._restore_last_valid_params(
                    f"{name}类型无法转换为数值，实际值={raw_value!r}"
                )
                return
        pb = converted["PB"]
        ti = converted["TI"]
        td = converted["TD"]
        kd = converted["KD"]
        sv_sch = converted["SVSCH"]
        sv_scl = converted["SVSCL"]
        mv_sch = converted["MVSCH"]
        mv_scl = converted["MVSCL"]
        sv_h = converted["SVH"]
        sv_l = converted["SVL"]
        mv_h = converted["MVH"]
        mv_l = converted["MVL"]

        # 有限性
        finite_checks = [
            ("PB", pb), ("TI", ti), ("TD", td), ("KD", kd),
            ("SVSCH", sv_sch), ("SVSCL", sv_scl),
            ("MVSCH", mv_sch), ("MVSCL", mv_scl),
            ("SVH", sv_h), ("SVL", sv_l),
            ("MVH", mv_h), ("MVL", mv_l),
        ]
        for name, value in finite_checks:
            if not math.isfinite(value):
                self._restore_last_valid_params(f"{name}非有限数值，实际值={value}")
                return

        # MODE 严格校验
        mode = _parse_mode(self.MODE)
        if mode is None:
            self._restore_last_valid_params(
                f"MODE必须为1~8整数，实际值={self.MODE!r}"
            )
            return

        # 数值范围
        if pb <= 0:
            self._restore_last_valid_params(f"PB必须大于0，实际值={pb}")
            return
        if ti < 0:
            self._restore_last_valid_params(f"TI必须>=0，实际值={ti}")
            return
        if td < 0:
            self._restore_last_valid_params(f"TD必须>=0，实际值={td}")
            return
        if kd < 0:
            self._restore_last_valid_params(f"KD必须>=0，实际值={kd}")
            return
        if sv_sch <= sv_scl:
            self._restore_last_valid_params(
                f"SVSCH必须大于SVSCL，SVSCH={sv_sch}，SVSCL={sv_scl}"
            )
            return
        if mv_sch <= mv_scl:
            self._restore_last_valid_params(
                f"MVSCH必须大于MVSCL，MVSCH={mv_sch}，MVSCL={mv_scl}"
            )
            return
        if sv_l < sv_scl:
            self._restore_last_valid_params(
                f"SVL不得小于SVSCL，SVL={sv_l}，SVSCL={sv_scl}"
            )
            return
        if sv_h > sv_sch:
            self._restore_last_valid_params(
                f"SVH不得大于SVSCH，SVH={sv_h}，SVSCH={sv_sch}"
            )
            return
        if sv_l > sv_h:
            self._restore_last_valid_params(
                f"SVL不得大于SVH，SVL={sv_l}，SVH={sv_h}"
            )
            return
        if mv_l < mv_scl:
            self._restore_last_valid_params(
                f"MVL不得小于MVSCL，MVL={mv_l}，MVSCL={mv_scl}"
            )
            return
        if mv_h > mv_sch:
            self._restore_last_valid_params(
                f"MVH不得大于MVSCH，MVH={mv_h}，MVSCH={mv_sch}"
            )
            return
        if mv_l > mv_h:
            self._restore_last_valid_params(
                f"MVL不得大于MVH，MVL={mv_l}，MVH={mv_h}"
            )
            return

        # SWPN：允许 0/1 数值或布尔；非法则回退
        try:
            swpn_val = float(self.SWPN)
        except (TypeError, ValueError):
            self._restore_last_valid_params(
                f"SWPN必须为数值，实际值={self.SWPN!r}"
            )
            return
        # 非有限值（NaN/±Inf）必须恢复上次有效 SWPN，避免 NaN != 0.0 被误判为 1.0
        if not math.isfinite(swpn_val):
            self._restore_last_valid_params(
                f"SWPN非有限数值，实际值={swpn_val}"
            )
            return
        if swpn_val not in (0.0, 1.0):
            # 容忍：非0即1（与ECS-700 ON/OFF语义一致）
            swpn_val = 1.0 if swpn_val != 0.0 else 0.0

        # ----------------------------------------------------------
        # 全部合法。处理在线量程变化。
        # ----------------------------------------------------------
        old_mvscl = self._last_valid_params.get("MVSCL", mv_scl)
        old_mvsch = self._last_valid_params.get("MVSCH", mv_sch)
        old_svscl = self._last_valid_params.get("SVSCL", sv_scl)
        old_svsch = self._last_valid_params.get("SVSCH", sv_sch)

        # MV 量程变化：保持工程量 MV 连续
        if old_mvscl != mv_scl or old_mvsch != mv_sch:
            current_mv = _clamp(float(self.MV), mv_l, mv_h)
            span = mv_sch - mv_scl
            if span != 0:
                self._mv_pct = 100.0 * (current_mv - mv_scl) / span

        # SV 量程变化：下一自动周期重新对齐误差历史
        if old_svscl != sv_scl or old_svsch != sv_sch:
            self._sv_scale_changed = True

        # 规范化 MODE 为整数
        self.MODE = mode
        self.SWPN = swpn_val

        # 更新上次有效参数
        self._last_valid_params = {
            "PB": pb, "TI": ti, "TD": td, "KD": kd,
            "MODE": float(mode),
            "SWPN": swpn_val,
            "SVSCH": sv_sch, "SVSCL": sv_scl,
            "MVSCH": mv_sch, "MVSCL": mv_scl,
            "SVH": sv_h, "SVL": sv_l,
            "MVH": mv_h, "MVL": mv_l,
        }

    def _restore_last_valid_params(self, reason: str) -> None:
        """恢复上次有效的运行参数，并记录日志。"""
        logger.warning("PID运行参数无效，已恢复上次有效参数: %s", reason)
        for key, value in self._last_valid_params.items():
            setattr(self, key, value)

    # ------------------------------------------------------------------
    # 工程量换算
    # ------------------------------------------------------------------
    def _sv_to_pct(self, value: float) -> float:
        """工程量 → 百分比。PV 允许超量程，不强制限幅。"""
        span = float(self.SVSCH) - float(self.SVSCL)
        if span == 0:
            return 0.0
        return 100.0 * (float(value) - float(self.SVSCL)) / span

    def _engineering_mv_to_pct(self, mv: float) -> float:
        """工程量 MV → MV 百分比。"""
        span = float(self.MVSCH) - float(self.MVSCL)
        if span == 0:
            return 0.0
        return 100.0 * (float(mv) - float(self.MVSCL)) / span

    def _pct_to_engineering_mv(self, mv_pct: float) -> float:
        """MV 百分比 → 工程量 MV。"""
        span = float(self.MVSCH) - float(self.MVSCL)
        return float(self.MVSCL) + mv_pct / 100.0 * span

    # ------------------------------------------------------------------
    # 输入处理
    # ------------------------------------------------------------------
    def _apply_inputs(
        self,
        PV: Optional[float],
        CSV: Optional[float],
        MODE: Optional[float],
        SWPN: Optional[float],
    ) -> None:
        """
        接收本周期输入（不含 SV），None 表示不覆盖。

        SV 的处理由 _capture_local_sv() 独立完成，以区分
        "execute(SV=...) 显式输入" 和 "UA 直接写 self.SV"。
        """
        if PV is not None and _is_finite_number(PV):
            self.PV = float(PV)

        if CSV is not None and _is_finite_number(CSV):
            self.CSV = float(CSV)

        if MODE is not None:
            mode = _parse_mode(MODE)
            if mode is not None:
                self.MODE = mode

        if SWPN is not None:
            try:
                swpn_val = float(SWPN)
            except (TypeError, ValueError):
                return
            # 非有限值忽略，由 _validate_or_restore_runtime_params 统一恢复
            if not math.isfinite(swpn_val):
                return
            if swpn_val in (0.0, 1.0):
                self.SWPN = swpn_val
            else:
                # 容忍：非0即1（与ECS-700 ON/OFF语义一致）
                self.SWPN = 1.0 if swpn_val != 0.0 else 0.0

    def _capture_local_sv(self, sv_input: Optional[float]) -> None:
        """
        捕获本地 SV 来源。

        优先级：
        1. execute(SV=...) 显式输入（有限数值）
        2. UA/Engine 外部写 self.SV（self.SV != _last_published_sv 且有限）
        3. 保持原 _local_sv

        CAS 模式下写 SV 也会保存到 _local_sv，但当前有效 SV 仍为 CSV。
        """
        if sv_input is not None and _is_finite_number(sv_input):
            self._local_sv = float(sv_input)
            return

        if _is_finite_number(self.SV) and float(self.SV) != self._last_published_sv:
            self._local_sv = float(self.SV)

    def _sanitize_finite_inputs(self) -> None:
        """
        检查 PV/CSV/MV 是否为有限数值。

        NaN/Inf 不得进入量程换算、限幅和最终 MV。
        非有限值恢复为上次有效值并记录日志。

        注意：_last_valid_mv 不在此处更新。MV 在算法计算后才会确定最终值，
        因此 _last_valid_mv 必须在每个周期最终 MV 限幅完成后更新（见 execute 各 return 分支）。
        """
        if _is_finite_number(self.PV):
            self._last_valid_pv = float(self.PV)
        else:
            logger.warning("PV非有限数值，恢复上次有效值: %r", self.PV)
            self.PV = self._last_valid_pv

        if _is_finite_number(self.CSV):
            self._last_valid_csv = float(self.CSV)
        else:
            logger.warning("CSV非有限数值，恢复上次有效值: %r", self.CSV)
            self.CSV = self._last_valid_csv

        if not _is_finite_number(self.MV):
            logger.warning("MV非有限数值，恢复上次有效值: %r", self.MV)
            self.MV = self._last_valid_mv

    # ------------------------------------------------------------------
    # 设定值处理
    # ------------------------------------------------------------------
    def _resolve_effective_sv(self, mode: int) -> float:
        """
        根据 MODE 解析当前有效 SV，并完成 SV 镜像。

        Returns:
            限幅后的有效 SV（工程量）
        """
        sv_l = float(self.SVL)
        sv_h = float(self.SVH)

        if mode in (6, 7):
            effective = _clamp(float(self.CSV), sv_l, sv_h)
            # 对外 SV 镜像当前有效 CSV
            self.SV = effective
            return effective

        # AUTO(5) 和非自动模式(1,2,3,4,8)都使用本地 SV
        effective = _clamp(self._local_sv, sv_l, sv_h)
        self._local_sv = effective
        self.SV = effective
        return effective

    def _publish_mode_state(self, mode: int) -> None:
        """
        派生上游兼容状态并记录已发布 SV。

        必须在所有 return 分支前调用。
        """
        self.AUTO = mode
        self.CAS = 1 if mode == 6 else 0
        self._sync_switches_from_mode(mode, force=False)
        self._last_swam = self._as_on_off(self.SWAM)
        self._last_swsv = self._as_on_off(self.SWSV)
        self._last_published_sv = float(self.SV)

    @staticmethod
    def _as_on_off(value: Any) -> Optional[int]:
        """Parse ECS ON/OFF switch: 0=OFF, 1=ON. Invalid → None."""
        if not _is_finite_number(value):
            return None
        number = float(value)
        if number == 0.0:
            return 0
        if number == 1.0:
            return 1
        return 1 if number >= 0.5 else 0

    def _sync_switches_from_mode(self, mode: int, force: bool = False) -> None:
        """
        Keep SWAM/SWSV consistent with MAN/AUTO/CAS.
        Other MODEs leave switches unchanged unless force=True (init).
        """
        if mode == 4:
            self.SWAM = 0.0
            self.SWSV = 0.0
        elif mode == 5:
            self.SWAM = 1.0
            self.SWSV = 0.0
        elif mode == 6:
            self.SWAM = 1.0
            self.SWSV = 1.0
        elif force:
            # Unknown / other modes: default to AUTO switches
            self.SWAM = 1.0
            self.SWSV = 0.0

    def _apply_swam_swsv_if_changed(self) -> None:
        """
        Mode switch commands write SWAM/SWSV; when they change, update MODE.
        Never write MODE from the faceplate path.
        """
        swam = self._as_on_off(getattr(self, "SWAM", None))
        swsv = self._as_on_off(getattr(self, "SWSV", None))
        if swam is None:
            return
        if swam == self._last_swam and swsv == self._last_swsv:
            return
        if swam == 0:
            self.MODE = 4  # MAN
        elif swsv == 0 or swsv is None:
            self.MODE = 5  # AUTO
        else:
            self.MODE = 6  # CAS
        self._last_swam = swam
        self._last_swsv = 0 if swsv is None else swsv

    # ------------------------------------------------------------------
    # 微分
    # ------------------------------------------------------------------
    def _calculate_filtered_derivative(self, error_pct: float) -> float:
        """
        不完全微分，返回 ΔU_n。

        U_n = TD / (KD·Ts + TD) × [U_{n-1} + KD·(E_n - E_{n-1})]
        ΔU_n = U_n - U_{n-1}
        """
        td = float(self.TD)
        if td <= 0:
            self._prev_derivative_state = 0.0
            return 0.0

        kd = float(self.KD)
        ts = float(self.cycle_time)
        denom = kd * ts + td
        if denom <= 0:
            self._prev_derivative_state = 0.0
            return 0.0

        u_now = td / denom * (self._prev_derivative_state + kd * (error_pct - self._prev_error_pct))
        d_delta = u_now - self._prev_derivative_state
        self._prev_derivative_state = u_now
        return d_delta

    # ------------------------------------------------------------------
    # 手动跟踪 / 无扰切换
    # ------------------------------------------------------------------
    def _track_manual_state(self, effective_sv: float) -> None:
        """手动类模式：将内部 _mv_pct 跟踪到当前 MV，并更新误差历史。"""
        self._mv_pct = self._engineering_mv_to_pct(float(self.MV))
        # 同步误差历史，便于切回自动时无扰
        pv_pct = self._sv_to_pct(float(self.PV))
        sv_pct = self._sv_to_pct(effective_sv)
        if bool(self.SWPN):
            error_pct = sv_pct - pv_pct
        else:
            error_pct = pv_pct - sv_pct
        self._prev_error_pct = error_pct
        # 微分状态清零，避免切换时冲击
        self._prev_derivative_state = 0.0

    def _prepare_bumpless_transfer(self, error_pct: float) -> None:
        """从手动类模式切入自动类模式时的无扰初始化。"""
        self._mv_pct = self._engineering_mv_to_pct(float(self.MV))
        self._prev_error_pct = error_pct
        self._prev_derivative_state = 0.0

    # ------------------------------------------------------------------
    # 抗积分饱和 + 限幅
    # ------------------------------------------------------------------
    def _calculate_limited_mv_pct(
        self,
        p_delta: float,
        i_delta: float,
        d_delta: float,
        kp: float,
    ) -> float:
        """
        抗积分饱和 + 输出限幅（百分比域）。

        饱和时取消同向积分；允许反向积分以退出饱和。
        """
        mvl_pct = self._engineering_mv_to_pct(float(self.MVL))
        mvh_pct = self._engineering_mv_to_pct(float(self.MVH))

        non_integral_delta = kp * (p_delta + d_delta)
        integral_delta = kp * i_delta

        candidate = self._mv_pct + non_integral_delta + integral_delta

        # 上限饱和且积分正向 → 取消正向积分
        if candidate > mvh_pct and integral_delta > 0:
            candidate = self._mv_pct + non_integral_delta
        # 下限饱和且积分负向 → 取消负向积分
        if candidate < mvl_pct and integral_delta < 0:
            candidate = self._mv_pct + non_integral_delta

        return _clamp(candidate, mvl_pct, mvh_pct)

    # ------------------------------------------------------------------
    # 主入口
    # ------------------------------------------------------------------
    def execute(
        self,
        PV: Optional[float] = None,
        SV: Optional[float] = None,
        CSV: Optional[float] = None,
        MODE: Optional[float] = None,
        SWPN: Optional[float] = None,
    ) -> None:
        """
        执行一个周期。

        Args:
            PV: 过程变量（None 表示沿用上周期值）
            SV: AUTO 模式本地设定值
            CSV: CAS/RCAS 模式外部设定值
            MODE: 工作模式（1~8 整数）
            SWPN: 正反作用（0/1）
        """
        # 1. 接收本周期输入（不含 SV）
        self._apply_inputs(PV=PV, CSV=CSV, MODE=MODE, SWPN=SWPN)

        # 1b. 若外部写了 SWAM/SWSV，则按规格更新 MODE（不改 PID 公式）
        self._apply_swam_swsv_if_changed()

        # 2. 捕获本地 SV（区分 execute 输入 / UA 外部写值 / 沿用原值）
        self._capture_local_sv(SV)

        # 3. 有限性保护（NaN/Inf 恢复）
        self._sanitize_finite_inputs()

        # 4. 校验运行参数；非法时恢复上次有效
        self._validate_or_restore_runtime_params()

        mode = int(self.MODE)

        # 5. 处理设定值来源
        effective_sv = self._resolve_effective_sv(mode)

        # 6. 派生上游兼容状态 + 记录已发布 SV
        self._publish_mode_state(mode)

        # 7. 非自动模式
        if mode in _MANUAL_MODES or mode == 1:
            self.MV = _clamp(float(self.MV), float(self.MVL), float(self.MVH))
            if mode in _MANUAL_MODES:
                self._track_manual_state(effective_sv)
            self._last_valid_mv = float(self.MV)
            self._previous_mode = mode
            self._initialized = True
            return

        # 8. 自动模式只允许 5/6/7
        if mode not in _AUTOMATIC_MODES:
            # 理论上不会到达（_validate 已过滤）
            self._last_valid_mv = float(self.MV)
            self._previous_mode = mode
            return

        # 9. 工程量归一化
        pv_pct = self._sv_to_pct(float(self.PV))
        sv_pct = self._sv_to_pct(effective_sv)

        # 10. 正反作用
        if bool(self.SWPN):
            # 反作用
            error_pct = sv_pct - pv_pct
        else:
            # 正作用
            error_pct = pv_pct - sv_pct

        # 11. 确定 p_delta / d_delta
        if not self._initialized:
            # 情况 A：冷启动自动模式 —— 保留首次比例响应
            self._mv_pct = self._engineering_mv_to_pct(float(self.MV))
            self._prev_error_pct = 0.0
            self._prev_derivative_state = 0.0
            self._sv_scale_changed = False
            p_delta = error_pct
            d_delta = 0.0
        elif self._previous_mode not in _AUTOMATIC_MODES:
            # 情况 B：从手动类/停止类切入自动 —— 无扰切换
            self._prepare_bumpless_transfer(error_pct)
            self._sv_scale_changed = False
            p_delta = 0.0
            d_delta = 0.0
        elif self._sv_scale_changed:
            # 情况 C：SV 量程变化 —— 本周期跳过比例和微分
            self._prev_error_pct = error_pct
            self._prev_derivative_state = 0.0
            self._sv_scale_changed = False
            p_delta = 0.0
            d_delta = 0.0
        else:
            # 情况 D：连续自动运行
            p_delta = error_pct - self._prev_error_pct
            d_delta = self._calculate_filtered_derivative(error_pct)

        # 12. 积分增量
        ti = float(self.TI)
        if ti > 0:
            i_delta = float(self.cycle_time) / ti * error_pct
        else:
            i_delta = 0.0

        kp = 100.0 / float(self.PB)

        # 13. 抗积分饱和和输出限幅
        self._mv_pct = self._calculate_limited_mv_pct(
            p_delta=p_delta,
            i_delta=i_delta,
            d_delta=d_delta,
            kp=kp,
        )

        # 14. 转回工程量
        self.MV = _clamp(
            self._pct_to_engineering_mv(self._mv_pct),
            float(self.MVL),
            float(self.MVH),
        )

        # 15. 更新内部状态
        self._prev_error_pct = error_pct
        self._previous_mode = mode
        self._initialized = True
        self._last_valid_mv = float(self.MV)


# 注册算法
if __name__ != "__main__":
    InstanceRegistry.register_algorithm("PID", PID)
