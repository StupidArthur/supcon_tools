"""
新工业级 PID（ECS-700 对齐）的测试套件。

直接实例化 PID 类，避免与 DSL / OPC UA / 线程耦合。
覆盖：
1. 注册
2. 默认位号
3. 冷启动比例响应（§8.1）
4. PB 方向
5. 工程量程不变性
6. 正反作用
7. AUTO / CAS / RCAS
8. 手动模式
9. 无扰切换
10. 输出限幅
11. 抗积分饱和
12. TI=0（§8.2）
13. TD=0 时 KD 不参与（§8.8）
14. 微分滤波（§8.9）
15. 参数非法 + MODE 整数严格校验（§8.6）
16. Engine 外部写 SV（§8.3）
17. CAS 下写 SV 保留（§8.4）
18. CAS 返回 AUTO 保存本地 SV（§8.5）
19. 量程变化连续性（§8.7）
20. AUTO/CAS 实际 MV 断言（§8.10）
21. Engine 集成
"""

import math
import sys
from pathlib import Path

import pytest

_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

# 触发 components.programs 包加载，完成算法注册
import components.programs  # noqa: F401
from components.programs.pid import PID
from components.programs.pid_delete import PID_DELETE
from controller.instance import InstanceRegistry


# ----------------------------------------------------------------------
# 辅助
# ----------------------------------------------------------------------
def _make_pid(**overrides) -> PID:
    """用合理默认值构造一个 PID。"""
    params = {
        "PB": 100.0,
        "TI": 20.0,
        "TD": 0.0,
        "KD": 10.0,
        "MODE": 5,
        "SWPN": 1,
        "SVSCL": 0.0,
        "SVSCH": 100.0,
        "SVL": 0.0,
        "SVH": 100.0,
        "MVSCL": 0.0,
        "MVSCH": 100.0,
        "MVL": 0.0,
        "MVH": 100.0,
        "PV": 0.0,
        "SV": 0.0,
        "CSV": 0.0,
        "MV": 0.0,
    }
    params.update(overrides)
    return PID(cycle_time=0.5, **params)


# ----------------------------------------------------------------------
# 注册测试
# ----------------------------------------------------------------------
def test_registration():
    """验证 PID / PID-DELETE 注册指向正确类。"""
    assert InstanceRegistry.get_algorithm("PID") is PID
    assert InstanceRegistry.get_algorithm("PID-DELETE") is PID_DELETE
    assert InstanceRegistry.get_algorithm("PID_DELETE") is PID_DELETE


# ----------------------------------------------------------------------
# 默认位号测试
# ----------------------------------------------------------------------
def test_stored_attributes_exist():
    """实例化后所有 stored_attributes 都真实存在。"""
    pid = _make_pid()
    for attr in PID.stored_attributes:
        assert hasattr(pid, attr), f"缺少位号: {attr}"


# ----------------------------------------------------------------------
# §8.1 冷启动比例响应测试
# ----------------------------------------------------------------------
def test_cold_auto_start_has_proportional_response():
    """首次直接以 AUTO 启动必须保留比例响应。"""
    pid = _make_pid(
        MODE=5,
        PB=100.0,
        TI=0.0,
        TD=0.0,
        SWPN=1,
        PV=0.0,
        SV=50.0,
        MV=0.0,
    )

    # 第一周期：冷启动自动模式
    # SWPN=1 反作用 error = sv - pv = 50 - 0 = 50%
    # p_delta = 50（保留首次比例响应）
    # kp = 100/100 = 1
    # _mv_pct = 0 + 1*50 = 50, MV = 50
    pid.execute(PV=0.0)
    assert pid.MV == pytest.approx(50.0)

    # 后续多个周期：误差不变，p_delta=0, i_delta=0(TI=0), MV 应保持 50
    for _ in range(10):
        pid.execute(PV=0.0)
    assert pid.MV == pytest.approx(50.0)


# ----------------------------------------------------------------------
# PB 方向测试
# ----------------------------------------------------------------------
def test_pb_direction():
    """PB 越小，输出响应越强。"""
    deltas = {}
    for pb in (50.0, 100.0, 200.0):
        # 初始 MV=50 让输出有上下移动空间
        pid = _make_pid(PB=pb, TI=0.0, TD=0.0, SWPN=1, SV=50.0, PV=50.0, MV=50.0)
        # 第一周期：冷启动，误差=0，p_delta=0，MV=50
        pid.execute(PV=50.0, SV=50.0)
        # 第二周期：建立稳态
        pid.execute(PV=50.0, SV=50.0)
        mv_before = pid.MV
        # 第三周期：SV 阶跃到 60，反作用 error = sv - pv = 10
        pid.execute(PV=50.0, SV=60.0)
        # p_delta = 10 - 0 = 10，正向增量
        deltas[pb] = abs(pid.MV - mv_before)
    # PB 越小，kp=100/PB 越大，MV 变化越大
    assert deltas[50.0] > deltas[100.0] > deltas[200.0], (
        f"PB 方向错误: 50={deltas[50.0]}, 100={deltas[100.0]}, 200={deltas[200.0]}"
    )


# ----------------------------------------------------------------------
# 工程量程不变性测试
# ----------------------------------------------------------------------
def test_engineering_span_invariance():
    """相同百分比误差下，输出增量应近似相等。"""
    # 控制器 A：量程 0~100，误差 10
    pid_a = _make_pid(
        PB=100.0, TI=0.0, TD=0.0, SWPN=0,
        SVSCL=0.0, SVSCH=100.0, MVSCL=0.0, MVSCH=100.0,
        SV=50.0, PV=40.0,
    )
    # 控制器 B：量程 0~1000，误差 100
    pid_b = _make_pid(
        PB=100.0, TI=0.0, TD=0.0, SWPN=0,
        SVSCL=0.0, SVSCH=1000.0, MVSCL=0.0, MVSCH=100.0,
        SV=500.0, PV=400.0,
    )
    # 第一周期：冷启动（A/B 都因负误差粘到下限 0）
    pid_a.execute(PV=40.0, SV=50.0)
    pid_b.execute(PV=400.0, SV=500.0)
    # 第二周期：产生 p_delta
    mv_a_before = pid_a.MV
    mv_b_before = pid_b.MV
    pid_a.execute(PV=45.0, SV=50.0)  # 误差从 -10 变 -5（5% 量程变化）
    pid_b.execute(PV=450.0, SV=500.0)  # 误差从 -100 变 -50（5% 量程变化）
    delta_a = pid_a.MV - mv_a_before
    delta_b = pid_b.MV - mv_b_before
    # 都是 5% 量程的误差变化，输出增量应近似
    assert abs(delta_a - delta_b) < 0.01, f"量程不变性失败: A={delta_a}, B={delta_b}"


# ----------------------------------------------------------------------
# 正反作用测试
# ----------------------------------------------------------------------
def test_direct_reverse_action():
    """SWPN=1 反作用 PV↑→MV↓；SWPN=0 正作用 PV↑→MV↑。"""
    # 反作用，初始 MV=50 留出空间
    pid_rev = _make_pid(SWPN=1, PB=100.0, TI=0.0, TD=0.0, SV=50.0, PV=50.0, MV=50.0)
    pid_rev.execute(PV=50.0, SV=50.0)  # 冷启动 error=0
    pid_rev.execute(PV=50.0, SV=50.0)  # 建立稳态
    mv_before = pid_rev.MV
    pid_rev.execute(PV=60.0, SV=50.0)  # PV 上升 → error = sv-pv = -10 → MV 减小
    assert pid_rev.MV < mv_before, f"反作用下 PV↑应使 MV↓: before={mv_before}, after={pid_rev.MV}"

    # 正作用，初始 MV=50
    pid_dir = _make_pid(SWPN=0, PB=100.0, TI=0.0, TD=0.0, SV=50.0, PV=50.0, MV=50.0)
    pid_dir.execute(PV=50.0, SV=50.0)
    pid_dir.execute(PV=50.0, SV=50.0)
    mv_before = pid_dir.MV
    pid_dir.execute(PV=60.0, SV=50.0)  # PV 上升 → error = pv-sv = 10 → MV 增大
    assert pid_dir.MV > mv_before, f"正作用下 PV↑应使 MV↑: before={mv_before}, after={pid_dir.MV}"


# ----------------------------------------------------------------------
# AUTO 测试
# ----------------------------------------------------------------------
def test_auto_mode():
    """MODE=5 使用 SV，忽略 CSV，AUTO==5，CAS==0。"""
    pid = _make_pid(MODE=5, SV=70.0, CSV=20.0, PB=100.0, TI=0.0, TD=0.0, SWPN=0)
    pid.execute(PV=50.0, SV=70.0, CSV=20.0)
    assert pid.AUTO == 5
    assert pid.CAS == 0
    # SV 应为本地 SV=70
    assert pid.SV == 70.0


# ----------------------------------------------------------------------
# CAS 测试
# ----------------------------------------------------------------------
def test_cas_mode():
    """MODE=6 使用 CSV，对外 SV 镜像 CSV，AUTO==6，CAS==1。"""
    pid = _make_pid(MODE=6, SV=70.0, CSV=30.0, PB=100.0, TI=0.0, TD=0.0, SWPN=0)
    pid.execute(PV=50.0, SV=70.0, CSV=30.0)
    assert pid.AUTO == 6
    assert pid.CAS == 1
    # SV 镜像 CSV
    assert pid.SV == 30.0


# ----------------------------------------------------------------------
# RCAS 测试
# ----------------------------------------------------------------------
def test_rcas_mode():
    """MODE=7 使用 CSV，AUTO==7，CAS==0。"""
    pid = _make_pid(MODE=7, SV=70.0, CSV=40.0, PB=100.0, TI=0.0, TD=0.0, SWPN=0)
    pid.execute(PV=50.0, SV=70.0, CSV=40.0)
    assert pid.AUTO == 7
    assert pid.CAS == 0
    assert pid.SV == 40.0


# ----------------------------------------------------------------------
# 手动测试
# ----------------------------------------------------------------------
@pytest.mark.parametrize("mode", [2, 4, 8])
def test_manual_modes(mode):
    """MODE=2/4/8 时 MV 保持外部写入值，PB/TI/TD 不影响。"""
    pid = _make_pid(MODE=mode, PB=100.0, TI=10.0, TD=10.0, SWPN=0, MV=37.0)
    pid.MV = 37.0
    for _ in range(5):
        pid.execute(PV=50.0, SV=70.0)
    assert pid.MV == 37.0, f"MODE={mode} 下 MV 应保持 37, 实际 {pid.MV}"


# ----------------------------------------------------------------------
# 无扰切换测试
# ----------------------------------------------------------------------
def test_bumpless_transfer():
    """MAN → AUTO 切换时 MV 不应突跳。"""
    pid = _make_pid(MODE=4, PB=100.0, TI=20.0, TD=0.0, SWPN=0, MV=37.0, SV=50.0)
    pid.MV = 37.0
    # MAN 模式跑几个周期
    for _ in range(3):
        pid.execute(PV=50.0, SV=50.0)
    assert pid.MV == 37.0

    # 切到 AUTO
    pid.execute(PV=50.0, SV=50.0, MODE=5)
    # 误差为 0，第一周期只有积分增量
    # 误差=0 → i_delta=0 → MV 应保持 37
    assert abs(pid.MV - 37.0) < 0.1, f"切换后 MV 突跳: {pid.MV}"


# ----------------------------------------------------------------------
# 输出限幅测试
# ----------------------------------------------------------------------
def test_output_limits():
    """MV 限幅在 [MVL, MVH] 内。"""
    pid = _make_pid(MODE=5, PB=10.0, TI=1.0, TD=0.0, SWPN=0,
                    SV=100.0, PV=0.0, MVL=10.0, MVH=80.0)
    # 大负误差（正作用 error=pv-sv=-100），长时间运行应粘到下限 10
    for _ in range(200):
        pid.execute(PV=0.0, SV=100.0)
    assert pid.MV <= 80.0 + 1e-9, f"MV 超过上限: {pid.MV}"
    assert pid.MV >= 10.0 - 1e-9

    # 反向：大正误差，应粘到上限 80
    pid2 = _make_pid(MODE=5, PB=10.0, TI=1.0, TD=0.0, SWPN=0,
                     SV=0.0, PV=100.0, MVL=10.0, MVH=80.0, MV=50.0)
    for _ in range(200):
        pid2.execute(PV=100.0, SV=0.0)
    assert pid2.MV >= 10.0 - 1e-9, f"MV 低于下限: {pid2.MV}"
    assert pid2.MV <= 80.0 + 1e-9


def test_manual_output_limit():
    """MAN 模式写 MV=200 时应被限到 MVH=80。"""
    pid = _make_pid(MODE=4, MVH=80.0, MVL=10.0, MV=37.0)
    pid.MV = 200.0
    pid.execute(PV=50.0, SV=50.0)
    assert pid.MV == 80.0


# ----------------------------------------------------------------------
# 抗积分饱和测试
# ----------------------------------------------------------------------
def test_anti_windup():
    """饱和后反转误差方向，控制器应能在合理周期内离开上限。"""
    # 反作用 SWPN=1：error = sv - pv，SV=100 PV=0 → error=100 → MV 增大粘到上限
    pid = _make_pid(MODE=5, PB=50.0, TI=2.0, TD=0.0, SWPN=1,
                    SV=100.0, PV=0.0, MVL=0.0, MVH=100.0)
    # 长时间大正误差 → 粘在上限
    for _ in range(100):
        pid.execute(PV=0.0, SV=100.0)
    assert pid.MV >= 99.99, f"应粘到上限 100, 实际 {pid.MV}"
    # 反转误差：SV=0 PV=100 → error=-100 → MV 减小
    for _ in range(50):
        pid.execute(PV=100.0, SV=0.0)
    # 应已离开上限
    assert pid.MV < 99.0, f"抗积分饱和失败，MV 仍在上限: {pid.MV}"


# ----------------------------------------------------------------------
# §8.2 TI=0 测试修正
# ----------------------------------------------------------------------
def test_ti_zero():
    """TI=0 时首周期有比例响应，固定误差下后续不继续积分爬升。"""
    # 初始 MV=50 留出空间，避免首周期比例响应粘到下限
    pid = _make_pid(MODE=5, PB=100.0, TI=0.0, TD=0.0, SWPN=0,
                    SV=60.0, PV=40.0, MV=50.0)
    # 首周期：冷启动，正作用 error = pv - sv = -20%
    # p_delta = -20, kp = 1, _mv_pct = 50 - 20 = 30, MV = 30
    pid.execute(PV=40.0, SV=60.0)
    mv_after_first = pid.MV
    # 首周期应有比例响应，不应粘到下限 MVSCL=0
    assert mv_after_first != pytest.approx(pid.MVSCL), (
        f"首周期应有比例响应，MV={mv_after_first} 不应等于 MVSCL={pid.MVSCL}"
    )

    # 固定误差下长期运行，不应继续积分爬升（TI=0 无积分）
    for _ in range(100):
        pid.execute(PV=40.0, SV=60.0)
    assert pid.MV == pytest.approx(mv_after_first), (
        f"TI=0 下固定误差 MV 不应变化: first={mv_after_first}, last={pid.MV}"
    )


# ----------------------------------------------------------------------
# §8.8 TD=0 时 KD 不参与输出
# ----------------------------------------------------------------------
def test_td_zero_kd_no_effect():
    """TD=0 时 KD 不参与输出，两个 KD 不同的控制器输出应一致。"""
    common = dict(
        MODE=5, PB=100.0, TI=0.0, TD=0.0, SWPN=0,
        SV=50.0, PV=50.0, MV=50.0,
    )
    pid_a = _make_pid(KD=1.0, **common)
    pid_b = _make_pid(KD=100.0, **common)

    # 输入完全相同的 PV/SV 序列，包含阶跃变化
    sequence = [
        (50.0, 50.0),  # 稳态
        (50.0, 50.0),  # 稳态
        (40.0, 50.0),  # PV 阶跃
        (30.0, 50.0),  # PV 继续变化
        (45.0, 50.0),  # PV 反向
        (50.0, 60.0),  # SV 阶跃
    ]
    for pv, sv in sequence:
        pid_a.execute(PV=pv, SV=sv)
        pid_b.execute(PV=pv, SV=sv)
        assert pid_a.MV == pytest.approx(pid_b.MV), (
            f"TD=0 时 KD 不应影响输出: pv={pv}, sv={sv}, "
            f"MV_a={pid_a.MV}, MV_b={pid_b.MV}"
        )


# ----------------------------------------------------------------------
# §8.9 微分滤波测试
# ----------------------------------------------------------------------
def test_derivative_filter():
    """TD>0 时微分输出受滤波约束，小于裸差分，且符合手册公式。"""
    # 放宽 MV 量程和限幅，避免饱和；初始 MV=MVSCL 使 _mv_pct=0，便于精确断言
    common = dict(
        MODE=5, PB=100.0, TI=0.0, SWPN=1,
        SVSCL=0.0, SVSCH=100.0, SVL=0.0, SVH=100.0,
        MVSCL=-10000.0, MVSCH=10000.0, MVL=-10000.0, MVH=10000.0,
        SV=50.0, PV=50.0, MV=-10000.0,
    )
    pid_a = _make_pid(TD=0.0, KD=10.0, **common)   # 无微分
    pid_b = _make_pid(TD=0.5, KD=10.0, **common)   # 有滤波微分

    # 第一周期：冷启动，error=0
    pid_a.execute(PV=50.0, SV=50.0)
    pid_b.execute(PV=50.0, SV=50.0)
    # 第二周期：稳态
    pid_a.execute(PV=50.0, SV=50.0)
    pid_b.execute(PV=50.0, SV=50.0)
    # 第三周期：PV 阶跃到 40，反作用 error = sv - pv = 10%
    pid_a.execute(PV=40.0, SV=50.0)
    pid_b.execute(PV=40.0, SV=50.0)

    # 在百分比域比较（_mv_pct 与误差% 同单位），避免工程量换算造成单位不一致
    # pid_a: 只有比例，p_delta=10, kp=1, _mv_pct = 0 + 10 = 10
    # pid_b: 比例 + 滤波微分
    mv_a_pct = pid_a._mv_pct
    mv_b_pct = pid_b._mv_pct

    # 裸差分理论值（百分比域）：d_delta_raw = KD * (E_n - E_{n-1}) = 10 * 10 = 100 (%)
    raw_derivative_effect_pct = 10.0 * 10.0  # 100

    filtered_derivative_effect_pct = mv_b_pct - mv_a_pct

    # 滤波后微分效果应大于 epsilon（确实有微分作用）
    assert abs(filtered_derivative_effect_pct) > 0.01, (
        f"滤波微分效果应大于 0.01: {filtered_derivative_effect_pct}"
    )
    # 滤波后微分效果应小于裸差分（受滤波约束）
    assert abs(filtered_derivative_effect_pct) < abs(raw_derivative_effect_pct), (
        f"滤波微分效果应小于裸差分: filtered={filtered_derivative_effect_pct}, raw={raw_derivative_effect_pct}"
    )

    # 依据手册公式验证单周期精确期望值
    # U_n = TD / (KD·Ts + TD) × [U_{n-1} + KD·(E_n - E_{n-1})]
    # ΔU_n = U_n - U_{n-1}
    ts = 0.5
    td = 0.5
    kd = 10.0
    e_n = 10.0       # 当前误差%
    e_prev = 0.0     # 上一周期误差%
    u_prev = 0.0     # 上一周期微分状态
    denom = kd * ts + td  # 5.5
    u_now = td / denom * (u_prev + kd * (e_n - e_prev))  # 0.5/5.5 * 100 ≈ 9.0909
    d_delta = u_now - u_prev  # 9.0909
    # _mv_pct_b = 0 + kp * (p_delta + d_delta) = 1 * (10 + 9.0909) = 19.0909
    expected_mv_b_pct = 10.0 + d_delta
    assert pid_b._mv_pct == pytest.approx(expected_mv_b_pct), (
        f"微分滤波不符合手册公式: actual={pid_b._mv_pct}, expected={expected_mv_b_pct}"
    )


# ----------------------------------------------------------------------
# §8.6 参数非法测试 + MODE 整数严格校验
# ----------------------------------------------------------------------
def test_invalid_params_at_construction():
    """构造时非法参数必须抛 ValueError。"""
    with pytest.raises(ValueError, match="PB"):
        _make_pid(PB=0.0)
    with pytest.raises(ValueError, match="TI"):
        _make_pid(TI=-1.0)
    with pytest.raises(ValueError, match="SVSCH"):
        _make_pid(SVSCH=100.0, SVSCL=100.0)
    with pytest.raises(ValueError, match="MVH"):
        _make_pid(MVH=200.0, MVSCH=100.0)
    with pytest.raises(ValueError, match="MODE"):
        _make_pid(MODE=99)
    # §8.6: MODE=5.9 非整数，构造时必须拒绝
    with pytest.raises(ValueError, match="MODE"):
        _make_pid(MODE=5.9)


def test_runtime_invalid_params_restored():
    """运行时非法参数应恢复上次有效值，不抛异常。"""
    pid = _make_pid(MODE=5, PB=100.0, TI=20.0, TD=0.0, SWPN=0)
    pid.execute(PV=50.0, SV=50.0)
    # 外部写入非法 PB
    pid.PB = -10.0
    pid.execute(PV=50.0, SV=50.0)
    # 应恢复到 100.0
    assert pid.PB == 100.0, f"非法 PB 未恢复: {pid.PB}"
    # 外部写入非法 MODE
    pid.MODE = 99
    pid.execute(PV=50.0, SV=50.0)
    assert int(pid.MODE) == 5, f"非法 MODE 未恢复: {pid.MODE}"
    # 不应产生 NaN/Inf
    assert math.isfinite(pid.MV)


def test_mode_integer_strict():
    """§8.6: MODE 必须为 1~8 整数，非整数/越界/非数值都非法。"""
    # 运行时写入各种非法 MODE，都应恢复到上次合法值 5
    pid = _make_pid(MODE=5)
    pid.execute(PV=50.0, SV=50.0)

    bad_values = [
        5.9,           # 非整数
        float("nan"),  # NaN
        float("inf"),  # Inf
        0,             # 越界（小于 1）
        9,             # 越界（大于 8）
        "abc",         # 非数字字符串
    ]
    for bad_mode in bad_values:
        pid.MODE = bad_mode
        pid.execute(PV=50.0, SV=50.0)
        assert pid.MODE == 5, f"非法 MODE={bad_mode!r} 未恢复: MODE={pid.MODE!r}"
        assert pid.AUTO == 5, f"非法 MODE={bad_mode!r} 后 AUTO 不一致: AUTO={pid.AUTO!r}"


# ----------------------------------------------------------------------
# §8.3 Engine 外部写 SV 测试
# ----------------------------------------------------------------------
def test_engine_external_sv_write():
    """Engine.override_variable('pid1.SV', ...) 在 AUTO 模式应真实生效。"""
    from controller.engine import UnifiedEngine
    from controller.clock import ClockMode
    from controller.parser import DSLParser

    # 注意：inputs 为空，不连接 SV，否则连接输入按约定优先
    yaml_content = """
clock:
  mode: GENERATOR
  cycle_time: 0.5

program:
  - name: pid1
    type: PID
    execute_first: true
    params:
      PB: 100.0
      TI: 0.0
      TD: 0.0
      KD: 10.0
      MODE: 5
      SWPN: 1
      SVSCL: 0.0
      SVSCH: 100.0
      SVL: 0.0
      SVH: 100.0
      MVSCL: 0.0
      MVSCH: 100.0
      MVL: 0.0
      MVH: 100.0
      SV: 50.0
      PV: 0.0
    inputs: {}
"""
    parser = DSLParser()
    config = parser.parse(yaml_content)
    engine = UnifiedEngine.from_program_config(config)
    engine.clock.config.mode = ClockMode.GENERATOR

    # 第一周期：冷启动 AUTO，SV=50, PV=0
    # 反作用 error = sv - pv = 50, p_delta=50, MV=50
    engine.clock.start()
    snapshot1 = engine.step()
    engine.clock.stop()
    mv_before = snapshot1["pid1.MV"]
    assert snapshot1["pid1.SV"] == pytest.approx(50.0)

    # 外部覆写 SV=60（模拟 UA 写值）
    engine.override_variable("pid1.SV", 60.0)
    engine.clock.start()
    snapshot2 = engine.step()
    engine.clock.stop()

    # SV 应该是 60
    assert snapshot2["pid1.SV"] == pytest.approx(60.0), (
        f"外部写 SV 未生效: {snapshot2['pid1.SV']}"
    )
    # MV 应该改变（SV 从 50→60，error 从 50→60，p_delta=10，MV 从 50→60）
    assert snapshot2["pid1.MV"] != pytest.approx(mv_before), (
        f"外部写 SV 后 MV 未变化: before={mv_before}, after={snapshot2['pid1.MV']}"
    )


# ----------------------------------------------------------------------
# §8.4 CAS 下写 SV 测试
# ----------------------------------------------------------------------
def test_cas_write_sv_preserved():
    """CAS 模式下写 SV 保存到本地，返回 AUTO 后使用写入的本地 SV。"""
    pid = _make_pid(MODE=6, CSV=30.0, SV=0.0, PB=100.0, TI=0.0, TD=0.0, SWPN=0)

    # 第一周期 CAS: 当前有效 SV = CSV = 30
    pid.execute(PV=50.0, CSV=30.0)
    assert pid.SV == 30.0, f"CAS 时 SV 应镜像 CSV=30, 实际 {pid.SV}"

    # 外部写 SV=70（模拟 UA 写值）
    pid.SV = 70.0
    # 下一周期 CAS：当前有效 SV 仍为 CSV=30，但本地 SV 已保存为 70
    pid.execute(PV=50.0, CSV=30.0)
    assert pid.SV == 30.0, (
        f"CAS 时写 SV 不应改变当前有效 SV, 应仍为 CSV=30, 实际 {pid.SV}"
    )

    # 切换到 AUTO
    pid.execute(PV=50.0, CSV=30.0, MODE=5)
    # AUTO 使用此前写入的本地 SV=70
    assert pid.SV == 70.0, (
        f"返回 AUTO 后应使用此前写入的本地 SV=70, 实际 {pid.SV}"
    )


# ----------------------------------------------------------------------
# §8.5 CAS 返回 AUTO 保存本地 SV 测试
# ----------------------------------------------------------------------
def test_cas_return_auto_preserves_local_sv():
    """CAS 返回 AUTO 时恢复此前保存的本地 SV，不得把 CSV 误保存为本地 SV。"""
    pid = _make_pid(MODE=5, SV=60.0, CSV=0.0, PB=100.0, TI=0.0, TD=0.0, SWPN=0)

    # AUTO 本地 SV=60
    pid.execute(PV=50.0, SV=60.0)
    assert pid.SV == 60.0

    # 切 CAS, CSV=30
    pid.execute(PV=50.0, CSV=30.0, MODE=6)
    # CAS 对外 SV=30
    assert pid.SV == 30.0, f"CAS 时 SV 应镜像 CSV=30, 实际 {pid.SV}"

    # 不写 SV，切回 AUTO
    pid.execute(PV=50.0, MODE=5)
    # SV 应恢复 60，不得把 CSV=30 保存成 _local_sv
    assert pid.SV == 60.0, (
        f"返回 AUTO 后应恢复本地 SV=60, 实际 {pid.SV}"
    )


# ----------------------------------------------------------------------
# §8.7 量程变化连续性测试
# ----------------------------------------------------------------------
def test_scale_change_continuity():
    """在线修改 MV 量程不应改变当前工程量 MV。"""
    pid = _make_pid(
        MODE=5,
        MV=50.0,
        MVSCL=0.0, MVSCH=100.0, MVL=0.0, MVH=100.0,
        SV=50.0, PV=50.0,
        TI=0.0, TD=0.0,
    )

    # 第一周期：error=0, MV=50
    pid.execute(PV=50.0, SV=50.0)
    assert pid.MV == pytest.approx(50.0)

    # 修改 MV 量程上下限
    pid.MVSCH = 200.0
    pid.MVH = 200.0
    # 下一周期：量程变化，_mv_pct 重算为 25%（50/200），MV 仍为 50
    pid.execute(PV=50.0, SV=50.0)
    assert pid.MV == pytest.approx(50.0), (
        f"量程变化后 MV 应保持 50, 实际 {pid.MV}"
    )


# ----------------------------------------------------------------------
# §8.10 AUTO/CAS 实际 MV 断言
# ----------------------------------------------------------------------
def test_auto_csv_does_not_affect_mv():
    """AUTO 模式下大幅修改 CSV 不应影响 MV。"""
    pid = _make_pid(
        MODE=5, SV=50.0, CSV=20.0,
        PB=100.0, TI=0.0, TD=0.0, SWPN=1,
        PV=0.0, MV=0.0,
    )
    # 冷启动：error = sv - pv = 50, p_delta=50, MV=50
    pid.execute(PV=0.0, SV=50.0, CSV=20.0)
    mv_before = pid.MV
    assert mv_before == pytest.approx(50.0)

    # 大幅修改 CSV=80，AUTO 模式使用 SV=50，CSV 不应影响 MV
    pid.execute(PV=0.0, SV=50.0, CSV=80.0)
    assert pid.MV == pytest.approx(mv_before), (
        f"AUTO 模式下 CSV 不应影响 MV: before={mv_before}, after={pid.MV}"
    )


def test_cas_csv_affects_mv():
    """CAS 模式下修改 CSV 应影响 MV。"""
    pid = _make_pid(
        MODE=6, SV=50.0, CSV=20.0,
        PB=100.0, TI=0.0, TD=0.0, SWPN=1,
        PV=0.0, MV=0.0,
    )
    # 冷启动 CAS: effective_sv = CSV=20, error = 20-0 = 20, p_delta=20, MV=20
    pid.execute(PV=0.0, CSV=20.0)
    mv_before = pid.MV
    assert mv_before == pytest.approx(20.0)

    # 修改 CSV=80
    # 连续自动：effective_sv = 80, error = 80, p_delta = 80-20 = 60, MV = 20+60 = 80
    pid.execute(PV=0.0, CSV=80.0)
    assert pid.MV != pytest.approx(mv_before), (
        f"CAS 模式下 CSV 应影响 MV: before={mv_before}, after={pid.MV}"
    )
    assert pid.MV == pytest.approx(80.0)


# ----------------------------------------------------------------------
# Engine 集成测试
# ----------------------------------------------------------------------
def test_engine_integration():
    """最小 YAML 创建 Engine，验证位号与外部覆写。"""
    from controller.engine import UnifiedEngine
    from controller.clock import ClockMode
    from controller.parser import DSLParser

    yaml_content = """
clock:
  mode: GENERATOR
  cycle_time: 0.5

program:
  - name: pid1
    type: PID
    execute_first: true
    params:
      PB: 100.0
      TI: 20.0
      TD: 0.0
      KD: 10.0
      MODE: 5
      SWPN: 0
      SVSCL: 0.0
      SVSCH: 100.0
      SVL: 0.0
      SVH: 100.0
      MVSCL: 0.0
      MVSCH: 100.0
      MVL: 0.0
      MVH: 100.0
      SV: 50.0
      PV: 0.0
    inputs: {}
"""
    parser = DSLParser()
    config = parser.parse(yaml_content)
    engine = UnifiedEngine.from_program_config(config)
    engine.clock.config.mode = ClockMode.GENERATOR

    engine.clock.start()
    snapshot = engine.step()
    engine.clock.stop()

    expected_tags = [
        "pid1.PV", "pid1.SV", "pid1.CSV", "pid1.MV",
        "pid1.PB", "pid1.TI", "pid1.TD", "pid1.MODE",
        "pid1.AUTO", "pid1.CAS", "pid1.SWPN",
        "pid1.SVSCH", "pid1.SVSCL", "pid1.MVSCH", "pid1.MVSCL",
        "pid1.SVH", "pid1.SVL", "pid1.MVH", "pid1.MVL",
    ]
    for tag in expected_tags:
        assert tag in snapshot, f"快照缺少位号: {tag}"

    # 外部覆写：切到 MAN 并写 MV=35
    engine.override_variable("pid1.MODE", 4)
    engine.override_variable("pid1.MV", 35.0)
    engine.clock.start()
    snapshot = engine.step()
    engine.clock.stop()
    assert int(snapshot["pid1.MODE"]) == 4
    assert abs(snapshot["pid1.MV"] - 35.0) < 0.01, f"MAN 模式 MV 应为 35, 实际 {snapshot['pid1.MV']}"
