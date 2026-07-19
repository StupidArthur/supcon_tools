# 乙醇—水精馏塔参考稳态生成器修复实施指令

> 交付对象：一个没有前序对话上下文的新 Agent  
> 仓库：`StupidArthur/supcon_tools`  
> 工作目录：`review3/`  
> 基准提交：开始工作时先同步最新 `main`，本文诊断时对应 `31559c7`  
> 本轮目标：修正参考稳态生成路径的物理一致性、稳态判定和失败写盘语义  
> 本轮不要求 Agent 进行长时间仿真验收；完整求解、长稳态窗口和漂移验收由后续审查者统一执行

---

## 1. Agent 开始前先明确任务性质

当前问题不是“再调一组 PI 参数”，也不是阀门响应太慢，而是参考稳态生成器把两套物理含义不同的模型串在了一起：

```text
阶段 1：直接指定 V_boil，并反推一个虚拟 Q_R
阶段 2：由真实蒸汽热量、散热和显热需求计算 V_boil
```

阶段 1 最终得到的状态不是阶段 2 方程的稳态，因此切换时必然产生大扰动。

本轮必须从结构上消除这个问题。不得继续通过增大 PI、延长运行周期、放宽组成阈值或修改 NRTL 参数掩盖问题。

---

## 2. 已经复现并确认的证据

在最新代码上，直接流量模式结束时得到：

| 项目 | 数值 |
|---|---:|
| 塔顶压力 | 101.32297 kPa |
| 塔釜温度 | 33.72425 ℃ |
| 当前压力下塔釜泡点 | 100.83901 ℃ |
| 塔釜过冷度 | 67.11476 K |
| 蒸汽流量 | 60.48639 kg/h |
| 蒸汽可用热量 | 34.04628 kW |
| 散热 | 0.17449 kW |
| 显热需求 | 33.87179 kW |
| 直接旁路强制的 `V_boil` | 0.00083734082 kmol/s |
| 相同蒸汽流量下物理路径的 `V_boil` | 0 kmol/s |

切到阀位模式后的第一周期：

```text
V_boil_internal      = 0
V_condense_internal  = 0.00067736044 kmol/s
P_top                = 101.32297 → 97.77882 kPa
```

冷凝器继续消耗气相库存，而再沸器暂时没有产生气相，所以压力立即下降。

切换前所谓“稳态”的真实导数为：

| 指标 | 实测 | `todo/5.md §9.4` 上限 |
|---|---:|---:|
| `max(abs(dM_tray/dt))` | 4.021e-5 kmol/s | 1e-8 |
| `max(abs(dnE_tray/dt))` | 1.813e-5 kmol/s | 1e-9 |
| `max(abs(dT_tray/dt))` | 4.007e-3 K/s | 1e-4 |
| `dTotalInventory/dt` | 1.849e-4 kmol/s | 接近 0 |
| `dxD/dt` | -1.382e-5 /s | 接近 0 |

并且：

```text
F - D - B                  = 0.00018490745 kmol/s
dTotalInventory/dt         = 0.00018490745 kmol/s
```

两者完全一致。回流罐和塔釜液位虽然被控制在约 50%，物料却持续积存在塔板中。

因此以下结论是本轮设计前提：

1. 阀门 `command_pct/actual_pct` 初始化不是主因；
2. 上一周期组成参与质量流量换算不是主因；
3. 当前阶段 1 没有达到稳态；
4. `direct_vapor_bypass` 隐藏了塔釜显热需求；
5. 当前 `check_convergence()` 没有落实规格中的状态导数门槛；
6. 收敛窗口为 0 时，生成器仍继续切换并写文件，这是错误的失败语义。

---

## 3. 开始编码前必须阅读的文件

按顺序阅读，不要只根据本文盲改：

```text
todo/5.md
todo/精馏塔稳态生成问题诊断.md
components/programs/ethanol_water_distillation.py
components/programs/ethanol_water_actuators.py
components/thermo/ethanol_water.py
tools/generate_ethanol_water_reference_state.py
tests/test_ethanol_water_distillation.py
```

重点位置：

```text
ethanol_water_distillation.py
  _build_warm_guess_initial_state()
  _compute_algebraic()
  _calculate_rhs()
  _integrate_substeps()
  execute()
  _get_full_state_dict()
  _set_full_state_dict()
  _load_steady_reference_state_strict()

generate_ethanol_water_reference_state.py
  compute_convergence_metrics()
  check_convergence()
  compute_steam_flow_from_v()
  _run_settling_phase()
  generate_reference_state()
```

开始前执行：

```bash
git status --short --branch
git log -1 --oneline
```

保留用户已有修改，不得使用 `git reset --hard`、`git checkout --` 等破坏性命令。

---

## 4. 本轮拍板采用的技术路线

采用以下固定路线，不再让 Agent 自选策略：

```text
WARM_GUESS
→ 使用动态模型原有 RHS 建立稳态非线性残差
→ scipy.optimize.least_squares 求一致稳态
→ 安装求解结果
→ 用“直接实际流量入口”做短验证
→ 把相同实际流量反算为阀位
→ 做直接流量/阀位单步等价性验证
→ 用标称阀位做连续动态稳态窗口和漂移验证
→ 全部门禁通过后原子写入正式 JSON
```

这里的代数求解器不能另写一套精馏模型。它只能调用动态模型现有的：

```text
_compute_algebraic()
_calculate_hydraulics()
_calculate_rhs()
```

因此代数求解和动态运行共享同一套 VLE、物料、能量、再沸和冷凝机理。

`least_squares` 只负责寻找 `RHS≈0` 的一致初值，最后仍以动态模型长时间无漂移作为验收依据。

---

## 5. 修改范围总览

预计修改：

```text
requirements.txt
components/programs/ethanol_water_distillation.py
tools/generate_ethanol_water_reference_state.py
tests/test_ethanol_water_distillation.py
```

本轮不要修改：

```text
components/thermo/ethanol_water.py
NRTL 参数
12 块理论板数量
进料板位置
两个正式 DSL
正式 PID 参数
todo/5.md 中 xD/xB 目标
```

本轮不要手工编辑正式参考状态：

```text
components/programs/data/ethanol_water_reference_state.json
```

只有完整求解和动态验收通过后，生成器才有权替换它。Agent 本轮无需亲自运行长验收，因此提交时通常不应包含该 JSON 的变化。

---

## 6. 修改一：为模型增加“直接实际公用工程流量”输入

### 6.1 原因

当前直接模式可以传入 `F/R/D/B/V`，但不能显式传入蒸汽和冷却水实际流量。

这迫使生成器用 `V_boil` 旁路代替蒸汽热量，造成两套物理路径。

修复后，直接入口和阀位入口的区别只能是“实际流量如何得到”：

```text
直接实际流量入口：调用方直接提供实际流量
阀位入口：阀门特性把开度转换为相同的实际流量
植物内部：两者统一调用 Q_R/Q_C/V_boil/V_condense 机理
```

### 6.2 修改 `execute()` 签名

文件：

```text
components/programs/ethanol_water_distillation.py
```

在 `execute()` 增加两个可选输入：

```python
def execute(
    self,
    ...,
    steam_flow_kg_h: Optional[float] = None,
    cooling_flow_kg_h: Optional[float] = None,
    **kwargs: Any,
) -> None:
```

名称虽然与输出属性相同，但方法局部参数和 `self.steam_flow_kg_h` 不冲突。

### 6.3 输入规则

保持现有优先级，避免大范围破坏兼容性：

1. 传入任一 `*_valve_pct`：进入阀位模式；实际流量由阀门计算；
2. 没有阀位输入：进入直接实际流量模式；
3. 直接模式下允许传入 `F/R/D/B/steam/cooling`；
4. 只有显式传入 `vapor_boilup_kgmol_per_s` 时才启用旧测试旁路；
5. 正式生成器绝对不得传入 `vapor_boilup_kgmol_per_s`。

在直接模式分支增加：

```python
if steam_flow_kg_h is not None:
    value = float(steam_flow_kg_h)
    if not math.isfinite(value) or value < 0.0:
        raise ValueError(...)
    self._last_steam_flow_kg_per_h = value

if cooling_flow_kg_h is not None:
    value = float(cooling_flow_kg_h)
    if not math.isfinite(value) or value < 0.0:
        raise ValueError(...)
    self._last_cooling_flow_kg_per_h = value
```

不要在模型内部悄悄截断为阀门额定流量。生成器和 DSL 应保证输入处于设备能力内；非法输入应明确失败。

### 6.4 `direct_vapor_bypass` 的处置

暂时保留以兼容已有阶段 B/C 单元测试，但必须把语义写清楚：

```text
仅供遗留单元测试使用；
不代表真实蒸汽/再沸器；
不得用于参考稳态生成；
不得用于正式 DSL；
不得用于模式等价性验证。
```

不要在本轮大规模删除旧测试或旧参数，避免扩大修复范围。

---

## 7. 修改二：删除生成器中的固定 V 工作流

文件：

```text
tools/generate_ethanol_water_reference_state.py
```

以下逻辑不得再出现在正式生成流程中：

```text
FIXED_VAPOR_BOILUP_KGMOL_PER_S 作为运行时强制输入
compute_steam_flow_from_v() 作为模式切换等价保证
_sync_valves_for_vapor_bypass()
col.execute(..., vapor_boilup_kgmol_per_s=V_flow)
“4 回路 PI + 固定 V”作为主稳态算法
```

常量可以暂时保留为初始猜测并重命名，例如：

```python
INITIAL_VAPOR_BOILUP_GUESS_KGMOL_PER_S = 0.00083734082
```

但它只能进入非线性求解器的初始向量，不能直接钉住动态模型的 `V_boil`。

`compute_steam_flow_from_v()` 如需保留，只能改名为：

```python
compute_initial_steam_guess_at_bubble_point()
```

而且必须明确：它只是 `WARM_GUESS` 位于泡点时的初猜，不保证任意状态下的逆映射。

初猜公式至少包含散热：

```python
Q_guess = V_guess * delta_h_vap + Q_loss_sump
steam_guess = (
    Q_guess * 3600.0
    / (steam_latent_heat_kj_per_kg * steam_heat_transfer_efficiency)
)
```

不要尝试用一个闭式公式处理任意过冷状态，因为 `Q_subcool` 本身和可用热量存在耦合。最终蒸汽流量应由稳态残差求解器求出。

---

## 8. 修改三：建立与动态模型同源的稳态残差问题

### 8.1 增加依赖

在：

```text
requirements.txt
```

增加：

```text
scipy>=1.10
```

生成器使用：

```python
from scipy.optimize import least_squares
```

### 8.2 未知变量固定为 51 个

不要自行减少或增加自由度，先按以下向量实现。

#### 塔板状态：36 个

```text
M_tray[12]
xE_tray[12]
T_tray[12]
```

#### 回流罐：3 个

```text
M_drum
xE_drum
T_drum
```

#### 塔釜：3 个

```text
M_sump
xE_sump
T_sump
```

#### 气相库存：3 个

```text
P_top
yE_vapor
T_vapor
```

#### 稳态操作变量：5 个

```text
R_flow_kgmol_per_s
D_flow_kgmol_per_s
B_flow_kgmol_per_s
steam_flow_kg_h
cooling_flow_kg_h
```

#### CMO 气相流量固定点变量：1 个

```text
V_boil_trial_kgmol_per_s
```

合计：

```text
36 + 3 + 3 + 3 + 5 + 1 = 51
```

进料流量、组成和温度保持 `REFERENCE_PARAMS` 固定值，不进入未知向量。

### 8.3 为什么用 `M/x/T` 而不是直接用 `M/nE/U`

这样可以通过简单上下界保证：

```text
M > 0
0 <= x <= 1
物理温度范围
```

每次评估残差时转换为动态模型状态：

```python
nE = M * x
U = M * liquid_enthalpy_kj_per_kmol(x, T)
```

气相状态转换：

```python
N_vapor = (
    P_top * col._vapor_volume_m3
    / (R_UNIVERSAL_KPA_M3_PER_KMOL_K * T_vapor)
)
nE_vapor = N_vapor * yE_vapor
U_vapor = N_vapor * vapor_internal_energy_kj_per_kmol(
    yE_vapor, T_vapor
)
```

### 8.4 51 个残差

调用 `_calculate_rhs()` 可获得 45 个状态导数：

```text
dM_tray[12]
dnE_tray[12]
dU_tray[12]
dM_drum, dnE_drum, dU_drum
dM_sump, dnE_sump, dU_sump
dN_vapor, dnE_vapor, dU_vapor
```

再增加：

```text
V_boil_trial - V_boil_calculated                  1 个
drum_level_pct - 50                               1 个
sump_level_pct - 50                               1 个
P_top - 101.325                                   1 个
top_ethanol_wt - 0.85                             1 个
bottom_ethanol_wt - 0.015                         1 个
```

合计：

```text
45 + 1 + 5 = 51
```

不要额外添加 `F-D-B=0` 方程，否则会超定。所有状态导数为零时，整体物料平衡自然成立。整体物料衡算只作为求解后的独立验收指标。

### 8.5 残差评估函数的固定调用顺序

建议实现：

```python
def evaluate_steady_residual(
    z: np.ndarray,
    col: ETHANOL_WATER_DISTILLATION,
) -> np.ndarray:
    ...
```

函数内部严格按下列顺序：

1. 解包 `z`；
2. 构造 `M/nE/U` 和气相状态；
3. 保存局部变量 `V_trial`；
4. 调用 `_compute_algebraic(..., V_trial)`；
5. 调用 `_calculate_hydraulics(M_tray)`；
6. 调用 `_calculate_rhs(..., direct_vapor_bypass=None)`；
7. 从 `col._V_boil_internal` 读取 `V_calculated`；
8. 拼接并缩放 51 个残差；
9. 返回一维 `np.float64` 数组。

核心调用形式参考：

```python
algebraic = col._compute_algebraic(
    M_tray, nE_tray, U_tray,
    M_drum, nE_drum, U_drum,
    M_sump, nE_sump, U_sump,
    N_vapor, nE_vapor, U_vapor,
    V_trial,
)

(
    T_tray_calc,
    yE_tray,
    T_drum_calc,
    T_sump_calc,
    yE_sump,
    p_top_calc,
    pressure_kpa,
    p_sump,
    T_vapor_avg,
    yE_vapor_calc,
    T_vapor_calc,
) = algebraic

L = col._calculate_hydraulics(M_tray)

rhs = col._calculate_rhs(
    M_tray, nE_tray, U_tray,
    M_drum, nE_drum, U_drum,
    M_sump, nE_sump, U_sump,
    N_vapor, nE_vapor, U_vapor,
    L, V_trial,
    T_tray_calc, yE_tray,
    T_drum_calc, T_sump_calc, yE_sump,
    T_vapor_calc, yE_vapor_calc,
    p_top_calc, p_sump,
    feed_flow, feed_xE, feed_temperature_k,
    R_flow, D_flow, B_flow,
    steam_flow_kg_h, cooling_flow_kg_h,
    cooling_water_temperature_c,
    direct_vapor_bypass=None,
)

V_calculated = float(col._V_boil_internal)
```

重要约束：

```text
direct_vapor_bypass 必须始终为 None
```

### 8.6 残差缩放

`least_squares` 接收的是无量纲缩放残差。使用以下固定缩放，不要直接把不同量纲裸拼接：

| 残差 | 除数 |
|---|---:|
| `dM_tray` | `1e-8 kmol/s` |
| `dnE_tray` | `1e-9 kmol/s` |
| `dU_tray` | `1e-3 kW` |
| `dM_drum`, `dM_sump` | `1e-8 kmol/s` |
| `dnE_drum`, `dnE_sump` | `1e-9 kmol/s` |
| `dU_drum`, `dU_sump` | `1e-3 kW` |
| `dN_vapor`, `dnE_vapor` | `1e-9 kmol/s` |
| `dU_vapor` | `1e-3 kW` |
| `V_trial - V_calculated` | `1e-9 kmol/s` |
| 回流罐/塔釜液位误差 | `0.1 percentage point` |
| 压力误差 | `0.10 kPa` |
| 塔顶质量分数误差 | `0.003` |
| 塔底质量分数误差 | `0.001` |

缩放后的绝对残差 `<=1` 表示达到对应门槛，但最终仍需用未缩放指标单独验收。

### 8.7 变量上下界

使用 `least_squares(bounds=(lower, upper))`，至少设置：

```text
M_tray:     0.2 * m_tray_nom ～ 3.0 * m_tray_nom
xE:         1e-8 ～ 0.999999
T_liquid:   280 ～ 420 K

M_drum:     0.10 * m_drum_100pct ～ 0.90 * m_drum_100pct
M_sump:     0.10 * m_sump_100pct ～ 0.90 * m_sump_100pct

P_top:      70.1 ～ 130 kPa(a)
yE_vapor:   1e-8 ～ 0.999999
T_vapor:    280 ～ 420 K

R:          1e-7 ～ 0.0015 kmol/s
D:          1e-7 ～ 0.0015 kmol/s
B:          1e-7 ～ 0.0030 kmol/s
steam:      0.1 ～ 100 kg/h
cooling:    1 ～ 7000 kg/h
V_trial:    1e-8 ～ 0.0030 kmol/s
```

液位量程字段应读取现有模型公共参数：

```python
col.m_drum_100pct_kmol
col.m_sump_100pct_kmol
```

不要把 50% 直接写成固定 kmol，避免以后设备参数变化后失效。

### 8.8 初始向量

从刚构造的 `WARM_GUESS` 模型读取状态，不得再手写第二套温度或浓度剖面。

操作变量初猜使用：

```text
F = 0.00130716777 kmol/s（固定）
D = 0.00020933521 kmol/s
B = 0.00109783256 kmol/s
R = 0.00062800562 kmol/s
V = 0.00083734082 kmol/s
steam ≈ 60.47 kg/h
cooling = 3500 kg/h
```

这些只是初猜，不是最终强制值。

整体质量目标本身是合理的。按质量分数计算：

```text
F = 100 kg/h
zF = 0.25
xD = 0.85
xB = 0.015

D = F * (zF - xB) / (xD - xB) = 28.144 kg/h
B = F - D                         = 71.856 kg/h
乙醇回收率                        = 95.69%
```

所以不要因为当前错误状态的 `xB≈1e-5` 而放弃 `xB=0.015`。

### 8.9 求解器参数

固定使用：

```python
result = least_squares(
    fun=evaluate_steady_residual,
    x0=x0,
    bounds=(lower, upper),
    method="trf",
    x_scale="jac",
    loss="linear",
    ftol=1e-10,
    xtol=1e-10,
    gtol=1e-10,
    max_nfev=2000,
    verbose=2 if verbose else 0,
)
```

若个别试探点触发已知物理求根失败，只捕获以下数值异常：

```python
(ValueError, RuntimeError, FloatingPointError)
```

返回固定长度的大残差，例如：

```python
np.full(51, 1e6, dtype=np.float64)
```

不要使用裸 `except Exception`，否则真实编程错误会被伪装成求解不收敛。

---

## 9. 修改四：安装求解结果

增加一个明确函数：

```python
def install_steady_solution(
    col: ETHANOL_WATER_DISTILLATION,
    result_vector: np.ndarray,
) -> OperatingInputs:
    ...
```

它必须：

1. 将 `M/x/T` 转换成 `M/nE/U` 并写入模型；
2. 写入气相 `N/nE/U`；
3. 写入 `_last_feed_flow/_last_reflux_flow/_last_distillate_flow/_last_bottoms_flow`；
4. 写入 `_last_steam_flow_kg_per_h/_last_cooling_flow_kg_per_h`；
5. 写入 `_V_boil_internal` 初值；
6. 重新调用 `_compute_algebraic()` 更新派生状态；
7. 调用 `_publish_scalar_attributes()`；
8. 返回一个不可变的实际操作量对象。

建议定义：

```python
@dataclass(frozen=True)
class OperatingInputs:
    feed_flow_kgmol_per_s: float
    reflux_flow_kgmol_per_s: float
    distillate_flow_kgmol_per_s: float
    bottoms_flow_kgmol_per_s: float
    steam_flow_kg_h: float
    cooling_flow_kg_h: float
```

后续直接模式、阀位反算和元数据必须共享这一个对象，禁止各阶段重新计算一套操作量。

---

## 10. 修改五：真正落实稳态判定

### 10.1 每周期保存前一状态

建议增加：

```python
@dataclass
class StateSnapshot:
    M_tray: np.ndarray
    nE_tray: np.ndarray
    U_tray: np.ndarray
    M_drum: float
    nE_drum: float
    U_drum: float
    M_sump: float
    nE_sump: float
    U_sump: float
    N_vapor: float
    nE_vapor: float
    U_vapor: float
    T_tray: np.ndarray
    T_drum: float
    T_sump: float
    T_vapor: float
    P_top: float
```

实现：

```python
def capture_state_snapshot(col) -> StateSnapshot:
    ...
```

数组必须 `.copy()`，否则下一周期会原地覆盖。

### 10.2 `compute_convergence_metrics()` 必须接收前一状态

改为：

```python
def compute_convergence_metrics(
    col: ETHANOL_WATER_DISTILLATION,
    previous: StateSnapshot,
    dt: float,
) -> Dict[str, float]:
```

必须计算：

```python
max_abs_dM_tray_dt = max(abs(M_now - M_prev)) / dt
max_abs_dnE_tray_dt = max(abs(nE_now - nE_prev)) / dt
abs_dM_drum_dt = abs(M_drum_now - M_drum_prev) / dt
abs_dM_sump_dt = abs(M_sump_now - M_sump_prev) / dt
abs_dN_vapor_dt = abs(N_now - N_prev) / dt
abs_dP_top_dt = abs(P_now - P_prev) / dt
max_abs_dT_dt = max(
    tray temperature derivatives,
    drum temperature derivative,
    sump temperature derivative,
    vapor temperature derivative,
)
```

同时保留：

```text
液位
压力
xD/xB
回收率
质量闭合
乙醇闭合
能量闭合
```

### 10.3 `check_convergence()` 必须覆盖规格全部门槛

严格落实 `todo/5.md §9.4`：

```text
max(abs(dM_tray/dt))       <= 1e-8 kmol/s
max(abs(dnE_tray/dt))      <= 1e-9 kmol/s
abs(dM_drum/dt)            <= 1e-8 kmol/s
abs(dM_sump/dt)            <= 1e-8 kmol/s
abs(dN_vapor/dt)           <= 1e-9 kmol/s
abs(dP_top/dt)              <= 1e-4 kPa/s
abs(dT_any/dt)              <= 1e-4 K/s
47 <= drum level <= 53
47 <= sump level <= 53
abs(P_top - 101.325)        <= 0.10 kPa
0.82 <= xD <= 0.88
0.010 <= xB <= 0.020
ethanol recovery            >= 95%
mass closure relative       <= 0.1%
ethanol closure relative    <= 0.2%
energy closure relative     <= 1.0%
```

### 10.4 连续窗口必须是硬门禁

```python
if convergence_window_count < required_window_cycles:
    raise ReferenceStateGenerationError(
        "未满足连续稳态窗口，禁止进入阀位验证和正式写盘"
    )
```

不得继续执行“先看看切换后会怎样”。

---

## 11. 修改六：直接实际流量动态验证

求解成功并安装状态后，使用同一个 `OperatingInputs` 调用：

```python
col.execute(
    feed_flow_kgmol_per_s=op.feed_flow_kgmol_per_s,
    reflux_flow_kgmol_per_s=op.reflux_flow_kgmol_per_s,
    distillate_flow_kgmol_per_s=op.distillate_flow_kgmol_per_s,
    bottoms_flow_kgmol_per_s=op.bottoms_flow_kgmol_per_s,
    steam_flow_kg_h=op.steam_flow_kg_h,
    cooling_flow_kg_h=op.cooling_flow_kg_h,
)
```

严禁出现：

```python
vapor_boilup_kgmol_per_s=...
```

正式完整验收将要求连续 1800 s 满足门槛。本轮 Agent 只需要把这段验证代码实现正确，不需要亲自跑满 3600 个周期。

---

## 12. 修改七：增加直接流量与阀位模式等价性门禁

### 12.1 反算阀位

继续复用现有：

```python
compute_valve_pct_from_flow(...)
```

反算时必须使用求解结果对应的当前塔顶/塔底组成。

### 12.2 建立两个完全相同的模型状态

```python
state_before_switch = col.save_state()

direct_col = ETHANOL_WATER_DISTILLATION(**REFERENCE_PARAMS)
direct_col.load_state(copy.deepcopy(state_before_switch))

valve_col = ETHANOL_WATER_DISTILLATION(**REFERENCE_PARAMS)
valve_col.load_state(copy.deepcopy(state_before_switch))
```

在 `valve_col` 上将六个阀门的：

```text
command_pct
actual_pct
```

同时设置为反算值，保证没有执行机构阶跃。

### 12.3 单步运行

`direct_col` 使用六个实际流量；`valve_col` 使用六个阀位。各运行一个 `cycle_time`。

先比较六个实际流量：

```text
feed_flow_kg_h
reflux_flow_kg_h
distillate_flow_kg_h
bottoms_flow_kg_h
steam_flow_kg_h
cooling_flow_kg_h
```

再比较：

```text
V_boil_internal
V_condense_internal
Q_R
Q_C
P_top
M/nE/U 全状态
```

建议阈值：

```text
实际流量：rtol <= 1e-8，atol <= 1e-10
V/Q/P：    rtol <= 1e-7，atol <= 1e-10
状态数组： rtol <= 1e-7，atol <= 1e-10
```

如果阀位模式因为质量流量到摩尔流量的组成换算产生超差，不要放宽到百分之几。应统一反算和正算使用的组成来源，直到等价性成立。

该门禁通过后，才允许把阀位称为“标称稳态阀位”。

---

## 13. 修改八：阀位模式动态漂移验证

模式等价性通过后，用 `valve_col` 和固定标称阀位运行。

完整验收由后续审查者执行：

```text
连续稳态窗口：1800 s = 3600 cycles @ 0.5 s
重新加载后漂移：3600 s = 7200 cycles @ 0.5 s
```

漂移门槛：

```text
压力变化                 <= 0.10 kPa
回流罐液位变化           <= 1.0 percentage point
塔釜液位变化             <= 1.0 percentage point
任一塔板温度变化          <= 0.20 ℃
塔顶质量分数变化          <= 0.003
塔底质量分数变化          <= 0.001
```

验证期间不得启用正式 PID 来掩盖错误参考状态。真正的参考稳态必须在固定标称阀位下本身不漂移。

---

## 14. 修改九：正式文件必须原子写入且失败不覆盖

当前生成器即使 `passed=False` 也会写正式 JSON，这是禁止的。

实现：

```python
def atomic_write_reference_state(
    output_path: Path,
    payload: Dict[str, Any],
) -> None:
    temp_path = output_path.with_suffix(output_path.suffix + ".tmp")
    ...
    os.replace(temp_path, output_path)
```

固定规则：

1. 求解器未成功：不写正式文件；
2. 未达到残差门槛：不写正式文件；
3. 连续稳态窗口未通过：不写正式文件；
4. 模式等价性未通过：不写正式文件；
5. 漂移未通过：不写正式文件；
6. 只有全部通过时才先写 `.tmp`，`flush + fsync` 后 `os.replace()`；
7. 异常退出时尽量清理自己的 `.tmp`；不得删除旧正式文件。

建议定义专用异常：

```python
class ReferenceStateGenerationError(RuntimeError):
    pass
```

命令行失败必须返回非零退出码，并打印：

```text
失败门禁
最后一次未缩放指标
求解器 status/message/nfev/cost/optimality
是否修改正式文件：否
```

---

## 15. 输出 JSON 必须记录的信息

全部通过后，保留规格要求的字段，并增加求解诊断：

```json
{
  "metadata": {
    "generation_method": "steady_rhs_least_squares_then_dynamic_validation",
    "used_direct_vapor_bypass": false,
    "solver": "scipy.optimize.least_squares",
    "solver_method": "trf",
    "solver_nfev": 0,
    "solver_cost": 0.0,
    "solver_optimality": 0.0
  },
  "convergence": {
    "passed": true,
    "max_abs_dM_tray_dt": 0.0,
    "max_abs_dnE_tray_dt": 0.0,
    "abs_dM_drum_dt": 0.0,
    "abs_dM_sump_dt": 0.0,
    "abs_dN_vapor_dt": 0.0,
    "abs_dP_top_dt": 0.0,
    "max_abs_dT_dt": 0.0,
    "convergence_window_cycles": 3600,
    "mode_equivalence_passed": true,
    "drift_passed": true
  }
}
```

字段名可按现有结构适度调整，但以下事实必须能从 JSON 直接确认：

```text
没有使用 V bypass
稳态求解器成功
完整导数门槛通过
连续窗口通过
模式等价性通过
漂移通过
```

---

## 16. `STEADY` 加载语义检查

检查 `_load_steady_reference_state_strict()`，确保它拒绝：

```text
convergence.passed != true
used_direct_vapor_bypass != false
mode_equivalence_passed != true
drift_passed != true
参数哈希不匹配
数组长度不等于 12
任意 NaN/Inf
状态越界
```

通用 `load_state()` 是运行时快照恢复接口，可以保持现有宽松语义；正式 `initialization_mode=STEADY` 必须走严格检查。

不要为了让当前已提交的失败 JSON 能加载而放宽严格检查。

---

## 17. Agent 只需要运行的最少测试

本轮明确不要让 Agent 跑完整长仿真，也不要反复试 PI 参数。

Agent 只执行以下快速检查。

### 17.1 语法检查

```bash
python -m py_compile \
  components/programs/ethanol_water_distillation.py \
  tools/generate_ethanol_water_reference_state.py
```

### 17.2 三个新增快速测试

在 `tests/test_ethanol_water_distillation.py` 或独立的小型测试文件中新增：

```text
test_direct_physical_utility_flow_uses_real_reboiler_path
test_direct_and_valve_inputs_are_single_step_equivalent
test_failed_generation_does_not_replace_existing_reference_file
```

测试要求：

#### 测试 1

直接传入 `steam_flow_kg_h/cooling_flow_kg_h`，不传 `vapor_boilup`，断言：

```text
模型使用 Q_R → V_boil 路径
输入流量正确发布
没有启用 direct_vapor_bypass
```

只跑 1～3 个周期。

#### 测试 2

从同一 `WARM_GUESS` 状态建立两个实例，直接实际流量和反算阀位各运行一个周期，比较实际流量、`V_boil/V_condense/Q_R/Q_C/P` 和核心状态。

只跑一个周期。

#### 测试 3

在临时目录创建一个内容为 `sentinel` 的已有参考文件，模拟求解或门禁失败，断言：

```text
函数抛出 ReferenceStateGenerationError 或返回失败
sentinel 文件内容未变
不存在被当成正式文件的半成品
```

### 17.3 仅运行这三个测试

例如：

```bash
pytest -q tests/test_ethanol_water_distillation.py \
  -k "direct_physical_utility_flow or single_step_equivalent or failed_generation"
```

如果测试放在独立文件：

```bash
pytest -q tests/test_ethanol_water_reference_generator.py
```

### 17.4 Agent 本轮不要执行

```text
不要跑全量 pytest
不要跑 1800 s 收敛窗口
不要跑 3600 s 漂移
不要覆盖正式 reference_state.json
不要因为 solver 初次不收敛就开始随机调参数
```

完整求解和长仿真由后续审查者在提交后统一执行。

---

## 18. 实施顺序

必须按顺序完成，避免同时修改过多逻辑后无法定位。

### 步骤 A：模型入口统一

```text
增加 steam_flow_kg_h/cooling_flow_kg_h 输入
确保 direct 模式走真实 Q_R/Q_C
保留旧 V bypass 仅供遗留测试
完成快速测试 1
```

### 步骤 B：单步模式等价

```text
复用阀门反函数
同步 command/actual
比较两个模型的单步结果
完成快速测试 2
```

### 步骤 C：重写生成器求解主线

```text
引入 least_squares
实现 51 变量打包/解包
实现 51 残差及缩放
实现求解结果安装
删除正式路径中的固定 V bypass
```

### 步骤 D：补齐门禁和写盘

```text
补齐全部导数指标
连续窗口成为硬门禁
模式等价成为硬门禁
漂移成为硬门禁
原子写盘
完成快速测试 3
```

### 步骤 E：停止并提交给审查者

到此停止。不要自行进入长时间试参循环。

---

## 19. 禁止使用的“快速修复”

以下任一项都视为没有完成任务：

```text
继续用 vapor_boilup bypass 生成状态
把塔釜温度 clip 到泡点
在模式切换前强行把 U_sump 改成泡点内能但不检查全塔能量
降低冷却水来延缓压力下降，却不修复稳态
只看 P/液位/xD，不看全部状态导数
把 8000 周期增加到更大数值
把 xB 验收改成 xB < 0.020
修改 NRTL 让组成“更容易通过”
用正式 PID 掩盖固定阀位下的漂移
求解失败时仍写 convergence.passed=false 的正式 JSON
捕获所有异常后继续保存
```

---

## 20. Agent 完成后必须回报的内容

Agent 最终只需提供：

```text
1. 修改文件列表
2. execute() 新输入及优先级说明
3. 是否彻底移除正式生成路径中的 V bypass
4. 51 个未知量和 51 个残差的实现位置
5. 求解器配置
6. 完整收敛指标是否已纳入门禁
7. 单步模式等价测试结果
8. 失败不覆盖测试结果
9. 语法检查结果
10. 明确说明：未运行长稳态和漂移验收
11. 当前 git diff/stat
12. 提交 SHA（如果用户要求提交）
```

不要声称“稳态已经通过”，除非确实完成了 1800 s 连续窗口和 3600 s 漂移；本轮通常不要求 Agent 执行这两项。

---

## 21. 后续审查者负责的验收

Agent 提交后，后续审查者将统一执行：

```text
1. 检查结构修改和测试语义
2. 运行 51 变量稳态求解器
3. 检查未缩放残差
4. 检查总体质量、乙醇和能量衡算
5. 运行 1800 s 连续稳态窗口
6. 验证直接流量/阀位模式单步等价
7. 在固定标称阀位下运行 3600 s 漂移
8. 检查正式 JSON 元数据和状态边界
9. 通过后再更新正式参考文件和后续 DSL/PID 初值
```

如果稳态求解器无法满足全部残差，后续审查者会根据具体残差判断：

```text
模型方程是否存在结构不闭合
规格是否过度约束
设备额定能力是否不足
数值缩放或初猜是否需要调整
```

Agent 不需要在本轮凭经验修改工艺目标。

---

## 22. 最终实施原则

本次修复的唯一核心是：

```text
稳态求解、直接实际流量运行、阀位运行和正式 DSL
必须共享完全相同的植物物理方程。
```

允许存在不同的输入表达：

```text
直接给实际流量
阀位经过执行机构得到实际流量
```

不允许存在不同的再沸、冷凝或气相库存机理。

只有完整状态导数接近零、输入模式单步等价、固定阀位长期无漂移的状态，才有资格被命名为：

```text
ethanol_water_reference_state.json
```
