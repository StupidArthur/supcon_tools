"""
工业级 PID 控制算法（对齐中控 ECS-700）

核心特性：
- 增量式 PID（ΔMV = (100/PB) × (ΔE + Ts/TI·E + ΔU)）
- PB 是比例度（Kp = 100/PB），不是比例增益
- ECS-700 MODE 1~8：OOS / IMAN / TR / MAN / AUTO / CAS / RCAS / ROUT
- AUTO = MODE（兼容别名，非布尔），CAS = 1 if MODE==6 else 0（派生）
- AUTO 用本地 SV，CAS/RCAS 用 CSV（同时镜像到对外 SV）
- 工程量程换算（SVSCH/SVSCL、MVSCH/MVSCL）+ 操作限幅（SVH/SVL、MVH/MVL）
- 正反作用 SWPN：0=正作用，1=反作用
- 不完全微分（TD=0 时关闭）
- 手动类模式 → 自动类模式无扰切换
- 抗积分饱和（饱和时取消同向积分）
- 运行时非法参数自动恢复上次有效值
"""

from __future__ import annotations

import math
from typing import Any, Dict, Optional

from controller.instance import InstanceRegistry
from .base import BaseProgram


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
- **MODE**：ECS-700 工作模式（1~8）。
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

## SV/CSV 来源

- AUTO 模式使用本地 `SV`（保存在 `_local_sv`）。
- CAS/RCAS 模式使用 `CSV`，并镜像到对外 `SV`。
- 从 CAS 返回 AUTO 时恢复此前保存的 `_local_sv`。

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
| TI | 积分时间（秒），0=关闭 | 20.0 |
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
        "TI": 20.0,
        "TD": 0.0,
        "KD": 10.0,
        # 工具默认直接运行，避免现有 YAML 未配置 MODE 时停止计算
        "MODE": 5,
        # ECS-700：ON 为反作用，OFF 为正作用
        "SWPN": 1,
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

        # 内部状态（不暴露到 stored_attributes / OPC UA / YAML）
        self._prev_error_pct: float = 0.0
        self._prev_derivative_state: float = 0.0
        self._mv_pct: float = self._engineering_mv_to_pct(self.MV)
        self._previous_mode: Optional[int] = None
        self._initialized: bool = False
        # 本地 SV（AUTO 模式使用），从初始 SV 取值
        self._local_sv: float = float(self.SV)
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
            ("PB", self.PB, lambda v: v > 0),
            ("TI", self.TI, lambda v: v >= 0),
            ("TD", self.TD, lambda v: v >= 0),
            ("KD", self.KD, lambda v: v >= 0),
            ("SVSCH", self.SVSCH, lambda v: True),
            ("SVSCL", self.SVSCL, lambda v: True),
            ("MVSCH", self.MVSCH, lambda v: True),
            ("MVSCL", self.MVSCL, lambda v: True),
            ("SVH", self.SVH, lambda v: True),
            ("SVL", self.SVL, lambda v: True),
            ("MVH", self.MVH, lambda v: True),
            ("MVL", self.MVL, lambda v: True),
            ("MODE", self.MODE, lambda v: True),
        ]
        for name, value, _ in checks:
            if not _is_finite_number(value):
                raise ValueError(
                    f"PID参数无效: {name} 必须为有限数值，实际值={value!r}"
                )

        pb = float(self.PB)
        if pb <= 0:
            raise ValueError(f"PID参数无效: PB 必须大于0，实际值={self.PB!r}")
        if float(self.TI) < 0:
            raise ValueError(f"PID参数无效: TI 必须>=0，实际值={self.TI!r}")
        if float(self.TD) < 0:
            raise ValueError(f"PID参数无效: TD 必须>=0，实际值={self.TD!r}")
        if float(self.KD) < 0:
            raise ValueError(f"PID参数无效: KD 必须>=0，实际值={self.KD!r}")

        sv_scl = float(self.SVSCL)
        sv_sch = float(self.SVSCH)
        mv_scl = float(self.MVSCL)
        mv_sch = float(self.MVSCH)
        sv_l = float(self.SVL)
        sv_h = float(self.SVH)
        mv_l = float(self.MVL)
        mv_h = float(self.MVH)

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

        try:
            mode_int = int(self.MODE)
        except (TypeError, ValueError):
            raise ValueError(
                f"PID参数无效: MODE 必须为 1..8 整数，实际值={self.MODE!r}"
            )
        if mode_int not in _VALID_MODES:
            raise ValueError(
                f"PID参数无效: MODE 必须在 1..8 范围内，实际值={self.MODE!r}"
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

        合法则更新 _last_valid_params；非法则恢复上次有效值。
        AUTO / CAS 的外部写值直接忽略，在本周期重新派生。
        """
        # AUTO / CAS 是派生属性，不允许外部写值改变模式，每周期重新派生
        # 这里不读 AUTO/CAS，直接以 MODE 为准

        # 逐项校验，任一非法则整体回退到上次有效值
        try:
            pb = float(self.PB)
            ti = float(self.TI)
            td = float(self.TD)
            kd = float(self.KD)
            mode_raw = self.MODE
            swpn = self.SWPN
            sv_sch = float(self.SVSCH)
            sv_scl = float(self.SVSCL)
            mv_sch = float(self.MVSCH)
            mv_scl = float(self.MVSCL)
            sv_h = float(self.SVH)
            sv_l = float(self.SVL)
            mv_h = float(self.MVH)
            mv_l = float(self.MVL)
        except (TypeError, ValueError):
            self._restore_last_valid_params()
            return

        # 有限性
        finite_items = {
            "PB": pb, "TI": ti, "TD": td, "KD": kd,
            "SVSCH": sv_sch, "SVSCL": sv_scl,
            "MVSCH": mv_sch, "MVSCL": mv_scl,
            "SVH": sv_h, "SVL": sv_l,
            "MVH": mv_h, "MVL": mv_l,
        }
        for name, value in finite_items.items():
            if not math.isfinite(value):
                self._restore_last_valid_params()
                return

        # MODE 校验
        try:
            mode_int = int(mode_raw)
        except (TypeError, ValueError):
            self._restore_last_valid_params()
            return
        if mode_int not in _VALID_MODES:
            self._restore_last_valid_params()
            return

        # 数值范围
        if pb <= 0 or ti < 0 or td < 0 or kd < 0:
            self._restore_last_valid_params()
            return
        if sv_sch <= sv_scl or mv_sch <= mv_scl:
            self._restore_last_valid_params()
            return
        if sv_l < sv_scl or sv_h > sv_sch or sv_l > sv_h:
            self._restore_last_valid_params()
            return
        if mv_l < mv_scl or mv_h > mv_sch or mv_l > mv_h:
            self._restore_last_valid_params()
            return

        # SWPN：允许 0/1 数值或布尔；非法则回退
        try:
            swpn_val = float(swpn)
        except (TypeError, ValueError):
            self._restore_last_valid_params()
            return
        if swpn_val not in (0.0, 1.0):
            # 容忍：非0即1（与ECS-700 ON/OFF语义一致）
            swpn_val = 1.0 if swpn_val != 0.0 else 0.0

        # 全部合法，更新上次有效
        self.SWPN = swpn_val
        self._last_valid_params = {
            "PB": pb, "TI": ti, "TD": td, "KD": kd,
            "MODE": float(mode_int),
            "SWPN": swpn_val,
            "SVSCH": sv_sch, "SVSCL": sv_scl,
            "MVSCH": mv_sch, "MVSCL": mv_scl,
            "SVH": sv_h, "SVL": sv_l,
            "MVH": mv_h, "MVL": mv_l,
        }

    def _restore_last_valid_params(self) -> None:
        """恢复上次有效的运行参数。"""
        for k, v in self._last_valid_params.items():
            setattr(self, k, v)

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
        SV: Optional[float],
        CSV: Optional[float],
        MODE: Optional[float],
        SWPN: Optional[float],
    ) -> None:
        """接收本周期输入，None 表示不覆盖。"""
        if PV is not None and _is_finite_number(PV):
            self.PV = float(PV)

        # SV：AUTO 模式下视为本地 SV 来源
        if SV is not None and _is_finite_number(SV):
            self._local_sv = float(SV)

        if CSV is not None and _is_finite_number(CSV):
            self.CSV = float(CSV)

        if MODE is not None:
            try:
                mode_int = int(MODE)
                if mode_int in _VALID_MODES:
                    self.MODE = mode_int
            except (TypeError, ValueError):
                pass

        if SWPN is not None:
            try:
                swpn_val = float(SWPN)
                if swpn_val in (0.0, 1.0):
                    self.SWPN = swpn_val
                else:
                    self.SWPN = 1.0 if swpn_val != 0.0 else 0.0
            except (TypeError, ValueError):
                pass

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

        if mode == 5:
            effective = _clamp(self._local_sv, sv_l, sv_h)
            self._local_sv = effective
            self.SV = effective
            return effective

        if mode in (6, 7):
            effective = _clamp(float(self.CSV), sv_l, sv_h)
            # 对外 SV 镜像当前有效 CSV
            self.SV = effective
            return effective

        # 非自动模式：保留本地 SV 不镜像
        effective = _clamp(self._local_sv, sv_l, sv_h)
        self._local_sv = effective
        self.SV = effective
        return effective

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
            MODE: 工作模式（1~8）
            SWPN: 正反作用（0/1）
        """
        # 1. 接收本周期输入
        self._apply_inputs(PV=PV, SV=SV, CSV=CSV, MODE=MODE, SWPN=SWPN)

        # 2. 校验运行参数；非法时恢复上次有效
        self._validate_or_restore_runtime_params()

        mode = int(self.MODE)

        # 3. 派生上游兼容状态
        self.AUTO = mode
        self.CAS = 1 if mode == 6 else 0

        # 4. 处理设定值来源
        effective_sv = self._resolve_effective_sv(mode)

        # 5. 非自动模式
        if mode in _MANUAL_MODES or mode == 1:
            self.MV = _clamp(float(self.MV), float(self.MVL), float(self.MVH))
            if mode in _MANUAL_MODES:
                self._track_manual_state(effective_sv)
            self._previous_mode = mode
            self._initialized = True
            return

        # 6. 自动模式只允许 5/6/7
        if mode not in _AUTOMATIC_MODES:
            self._previous_mode = mode
            return

        # 7. 工程量归一化
        pv_pct = self._sv_to_pct(float(self.PV))
        sv_pct = self._sv_to_pct(effective_sv)

        # 8. 正反作用
        if bool(self.SWPN):
            # 反作用
            error_pct = sv_pct - pv_pct
        else:
            # 正作用
            error_pct = pv_pct - sv_pct

        # 9. 无扰切换：首次进入自动 或 从手动类切入自动
        if not self._initialized or self._previous_mode not in _AUTOMATIC_MODES:
            self._prepare_bumpless_transfer(error_pct)
            # 本周期只允许积分增量，避免比例/微分突跳
            p_delta = 0.0
            d_delta = 0.0
        else:
            # 10. 计算增量 PID
            p_delta = error_pct - self._prev_error_pct
            d_delta = self._calculate_filtered_derivative(error_pct)

        # 积分增量
        ti = float(self.TI)
        if ti > 0:
            i_delta = float(self.cycle_time) / ti * error_pct
        else:
            i_delta = 0.0

        kp = 100.0 / float(self.PB)

        # 11. 抗积分饱和和输出限幅
        self._mv_pct = self._calculate_limited_mv_pct(
            p_delta=p_delta,
            i_delta=i_delta,
            d_delta=d_delta,
            kp=kp,
        )

        # 12. 转回工程量
        self.MV = _clamp(
            self._pct_to_engineering_mv(self._mv_pct),
            float(self.MVL),
            float(self.MVH),
        )

        # 13. 更新内部状态
        self._prev_error_pct = error_pct
        self._previous_mode = mode
        self._initialized = True


# 注册算法
if __name__ != "__main__":
    InstanceRegistry.register_algorithm("PID", PID)
