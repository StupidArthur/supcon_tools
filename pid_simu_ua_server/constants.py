"""
常量定义模块
"""
from datetime import datetime


class Constants:
    """常量定义"""
    # 更新频率常量
    CHART_UPDATE_INTERVAL = 50  # 每50个记录更新一次图表
    DATA_UPDATE_INTERVAL = 10    # 每10个周期发送一次数据更新信号
    
    # 默认时间常量
    DEFAULT_TIME_INTERVAL = 0.5  # 默认时间间隔（秒）
    DEFAULT_BASE_TIME = datetime(2024, 6, 3, 19, 0, 0)  # 默认基准时间
    
    # 端口范围
    MIN_PORT = 1
    MAX_PORT = 65535
    
    # 位号定义（统一管理所有位号）
    # 约定：所有PID相关位号统一以 pid.* 形式登记，OPCUA/TPT等使用统一格式化规则生成完整位号名
    TAG_DEFINITIONS = [
        # PID 基本量
        ('pid.sv', 'PID设定值'),
        ('pid.pv', 'PID过程值'),
        ('pid.mv', 'PID输出值'),
        ('pid.kp', 'PID比例系数'),
        ('pid.pb', 'PID比例带（与KP数值一致）'),
        ('pid.td', 'PID微分时间'),
        ('pid.ti', 'PID积分时间'),
        # PID 模式与联锁相关位号
        ('pid.mode', 'PID模式（恒定20）'),
        ('pid.cas', '级联标志（恒定0）'),
        # PID 上下限/量程相关位号
        ('pid.swpn', 'PID开关逻辑（恒为1）'),
        ('pid.svsch', 'SV 上量程（等于水箱高度）'),
        ('pid.svh', 'SV 工程上限（等于水箱高度）'),
        ('pid.svscl', 'SV 工程下限（0）'),
        ('pid.mvscl', 'MV 工程下限（0）'),
        ('pid.svl', 'SV 显示下限（0）'),
        ('pid.mvl', 'MV 显示下限（0）'),
        ('pid.mvsch', 'MV 上量程（100）'),
        ('pid.mvh', 'MV 工程上限（100）'),
        # 过程量位号
        ('tank.level', '水箱液位'),
        ('valve.current_opening', '阀门开度')
    ]
    
    @classmethod
    def get_tag_keys(cls):
        """获取所有位号键列表"""
        return [tag[0] for tag in cls.TAG_DEFINITIONS]
    
    @classmethod
    def get_tag_descriptions(cls):
        """获取位号描述字典"""
        return {tag[0]: tag[1] for tag in cls.TAG_DEFINITIONS}


