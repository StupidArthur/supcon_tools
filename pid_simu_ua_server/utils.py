"""
工具方法模块
"""
from typing import Dict, Any, List
from PyQt6.QtWidgets import QLineEdit
from utils.logger import get_logger
from .constants import Constants

logger = get_logger()


def format_float(value: float, precision: int = 6) -> str:
    """格式化浮点数"""
    return f"{value:.{precision}f}"


def format_tag_name(instance_name: str, param_name: str) -> str:
    """
    格式化位号名：{实例名}_{param_prefix}.{param_suffix.UPPER}
    
    Args:
        instance_name: 实例名，如 "PID_TEST_1"
        param_name: 参数名，如 "pid.mv", "tank.level", "valve.current_opening"
    
    Returns:
        格式化后的位号名，如 "PID_TEST_1_pid.MV", "PID_TEST_1_tank.LEVEL"
    
    Examples:
        - "pid.mv" -> "PID_TEST_1_pid.MV"
        - "tank.level" -> "PID_TEST_1_tank.LEVEL"
        - "valve.current_opening" -> "PID_TEST_1_valve.CURRENT_OPENING"
    """
    if '.' in param_name:
        param_prefix, param_suffix = param_name.split('.', 1)
        # 将param_suffix转换为大写
        param_suffix_upper = param_suffix.upper()
        return f"{instance_name}_{param_prefix}.{param_suffix_upper}"
    else:
        # 如果没有点，直接使用参数名（转换为大写）
        return f"{instance_name}_{param_name.upper()}"


def get_float_value(line_edit: QLineEdit, default: str) -> float:
    """获取浮点数值，带默认值和验证"""
    try:
        text = line_edit.text().strip()
        value = float(text) if text else float(default)
        return value
    except ValueError:
        logger.warning(f"Invalid float value in {line_edit.objectName()}, using default: {default}")
        return float(default)


def get_tank_params(tank_height: QLineEdit, tank_radius: QLineEdit,
                    tank_inlet_area: QLineEdit, tank_inlet_velocity: QLineEdit,
                    tank_outlet_area: QLineEdit, tank_initial_level: QLineEdit) -> Dict[str, Any]:
    """获取水箱参数"""
    height = get_float_value(tank_height, "2.0")
    if height <= 0:
        raise ValueError("水箱高度必须大于0")
    
    radius = get_float_value(tank_radius, "0.5")
    if radius <= 0:
        raise ValueError("水箱半径必须大于0")
    
    inlet_area = get_float_value(tank_inlet_area, "0.06")
    if inlet_area <= 0:
        raise ValueError("入水口面积必须大于0")
    
    inlet_velocity = get_float_value(tank_inlet_velocity, "3.0")
    if inlet_velocity < 0:
        raise ValueError("入水速度不能为负数")
    
    outlet_area = get_float_value(tank_outlet_area, "0.001")
    if outlet_area <= 0:
        raise ValueError("出水口面积必须大于0")
    
    initial_level = get_float_value(tank_initial_level, "0.0")
    if initial_level < 0:
        raise ValueError("初始水位不能为负数")
    
    return {
        'height': height,
        'radius': radius,
        'inlet_area': inlet_area,
        'inlet_velocity': inlet_velocity,
        'outlet_area': outlet_area,
        'initial_level': initial_level
    }


def get_valve_params(valve_min_opening: QLineEdit, valve_max_opening: QLineEdit,
                     valve_full_travel_time: QLineEdit) -> Dict[str, Any]:
    """获取阀门参数"""
    min_opening = get_float_value(valve_min_opening, "0.0")
    max_opening = get_float_value(valve_max_opening, "100.0")
    
    if min_opening < 0 or min_opening > 100:
        raise ValueError("最小开度必须在0-100范围内")
    if max_opening < 0 or max_opening > 100:
        raise ValueError("最大开度必须在0-100范围内")
    if min_opening >= max_opening:
        raise ValueError("最大开度必须大于最小开度")
    
    full_travel_time = get_float_value(valve_full_travel_time, "5.0")
    if full_travel_time <= 0:
        raise ValueError("满行程时间必须大于0")
    
    return {
        'min_opening': min_opening,
        'max_opening': max_opening,
        'full_travel_time': full_travel_time
    }


def get_pid_params(pid_kp: QLineEdit, pid_ti: QLineEdit, pid_td: QLineEdit,
                   pid_sv: QLineEdit, pid_pv: QLineEdit, pid_mv: QLineEdit,
                   pid_h: QLineEdit, pid_l: QLineEdit) -> Dict[str, Any]:
    """获取PID参数"""
    kp = get_float_value(pid_kp, "12.0")
    if kp < 0:
        raise ValueError("比例系数不能为负数")
    
    ti = get_float_value(pid_ti, "30.0")
    if ti < 0:
        raise ValueError("积分时间不能为负数")
    
    td = get_float_value(pid_td, "0.15")
    if td < 0:
        raise ValueError("微分时间不能为负数")
    
    h = get_float_value(pid_h, "100.0")
    l = get_float_value(pid_l, "0.0")
    if h <= l:
        raise ValueError("输出上限必须大于输出下限")
    
    return {
        'kp': kp,
        'ti': ti,
        'td': td,
        'sv': float(pid_sv.text().split(',')[0] if pid_sv.text() else "0.0"),  # 使用第一个值作为初始值
        'pv': get_float_value(pid_pv, "0.0"),
        'mv': get_float_value(pid_mv, "0.0"),
        'h': h,
        'l': l
    }


def get_sv_values(pid_sv: QLineEdit) -> List[float]:
    """获取SV设定值列表（逗号分隔）"""
    sv_text = pid_sv.text().strip()
    if not sv_text:
        return [0.0]
    
    try:
        # 按逗号分割并转换为浮点数列表
        sv_values = [float(x.strip()) for x in sv_text.split(',') if x.strip()]
        return sv_values if sv_values else [0.0]
    except ValueError:
        logger.warning("SV值格式错误，使用默认值0.0")
        return [0.0]


