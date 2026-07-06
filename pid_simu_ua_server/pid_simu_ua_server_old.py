"""
统一工具：PID模拟 + OPCUA Server
整合PID回路模拟和OPCUA Server功能，可以在模拟完成后直接启动OPCUA Server
"""
import sys
import os
import ast
import asyncio
import csv
import json
import socket
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Any, List, Optional

# 导入openpyxl用于Excel文件操作
try:
    from openpyxl import Workbook
    from openpyxl.styles import Font, Alignment
    OPENPYXL_AVAILABLE = True
except ImportError:
    OPENPYXL_AVAILABLE = False

# 添加项目根目录到Python路径
SCRIPT_DIR = Path(__file__).parent.parent.absolute()
sys.path.insert(0, str(SCRIPT_DIR))

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QLineEdit, QPushButton, QGroupBox,
    QMessageBox, QProgressBar, QFrame, QFileDialog
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QFont

# matplotlib相关导入
import matplotlib
matplotlib.use('Qt5Agg')  # 使用Qt5后端
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
import matplotlib.pyplot as plt

# 设置中文字体
plt.rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei']
plt.rcParams['axes.unicode_minus'] = False

# asyncua相关导入
from asyncua import Server, ua

# 导入项目模块
from plc.clock import Clock
from module.cylindrical_tank import CylindricalTank
from module.valve import Valve
from algorithm.pid import PID
from utils.logger import get_logger

# 初始化日志
logger = get_logger()


# 常量定义
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
    TAG_DEFINITIONS = [
        ('pid.sv', 'PID设定值'),
        ('pid.pv', 'PID过程值'),
        ('pid.mv', 'PID输出值'),
        ('pid.kp', 'PID比例系数'),
        ('pid.td', 'PID微分时间'),
        ('pid.ti', 'PID积分时间'),
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


class SimulationThread(QThread):
    """模拟运行线程"""
    
    # 信号：进度更新
    progress_updated = pyqtSignal(float, int)  # (进度百分比, 记录数)
    # 信号：数据更新
    data_updated = pyqtSignal(dict)  # 单条数据记录
    # 信号：完成
    finished = pyqtSignal(list)  # 所有数据记录
    
    def __init__(self, tank_params: Dict[str, Any], valve_params: Dict[str, Any],
                 pid_params: Dict[str, Any], duration: float, sv_values: List[float],
                 cycle_time: float = 0.5):
        """
        初始化模拟线程
        
        Args:
            tank_params: 水箱参数
            valve_params: 阀门参数
            pid_params: PID参数
            duration: 模拟时长（秒）
            sv_values: SV设定值列表，会在模拟时长内均匀分布
            cycle_time: 运行周期（秒）
        """
        super().__init__()
        self.tank_params = tank_params
        self.valve_params = valve_params
        self.pid_params = pid_params
        self.duration = duration
        self.sv_values = sv_values
        self.cycle_time = cycle_time
        self._running = True
        
    def stop(self):
        """停止模拟"""
        self._running = False
    
    def run(self):
        """运行模拟"""
        clock = None
        data_records = []
        try:
            # 初始化模型和算法
            tank = CylindricalTank(**self.tank_params)
            valve = Valve(**self.valve_params)
            pid = PID(**self.pid_params)
            
            # 初始化时钟
            clock = Clock(cycle_time=self.cycle_time)
            clock.start()
            
            # 数据记录
            data_records = []
            
            # 计算SV切换时间点
            # 将模拟时长均匀分成len(sv_values)段，每段使用一个SV值
            if len(self.sv_values) > 1:
                segment_duration = self.duration / len(self.sv_values)
                sv_switch_times = [i * segment_duration for i in range(len(self.sv_values))]
            else:
                sv_switch_times = [0.0]
                self.sv_values = [self.sv_values[0]]
            
            # 初始化参数值
            tank_level = tank.level
            valve_opening = valve.current_opening
            pid_pv = tank_level
            
            # 设置初始SV值
            current_sv_index = 0
            pid.input['sv'] = self.sv_values[current_sv_index]
            pid_sv = pid.input['sv']
            pid_mv = pid.output['mv']
            
            # 运行循环
            target_sim_time = self.duration
            
            while clock.current_time < target_sim_time and self._running:
                # 检查是否需要切换SV值
                if current_sv_index < len(self.sv_values) - 1:
                    next_switch_time = sv_switch_times[current_sv_index + 1]
                    if clock.current_time >= next_switch_time:
                        current_sv_index += 1
                        pid.input['sv'] = self.sv_values[current_sv_index]
                
                # 更新PID的PV（从水箱获取）
                pid.input['pv'] = tank_level
                
                # 执行PID算法
                pid.execute(input_params={'pv': tank_level, 'sv': pid.input['sv']})
                pid_mv = pid.output['mv']
                
                # PID输出 -> 阀门目标开度（通过属性设置）
                valve.target_opening = pid_mv
                valve_opening = valve.execute(step=self.cycle_time)
                
                # 阀门开度 -> 水箱输入（通过属性设置）
                tank.valve_opening = valve_opening
                tank_level = tank.execute(step=self.cycle_time)
                
                # 步进时钟
                clock.step()
                
                # 记录数据
                record = {
                    'sim_time': clock.current_time,
                    'pid.sv': pid.input['sv'],
                    'pid.pv': pid.input['pv'],
                    'pid.mv': pid.output['mv'],
                    'pid.kp': pid.config['kp'],
                    'pid.td': pid.config['td'],
                    'pid.ti': pid.config['ti'],
                    'tank.level': tank_level,
                    'valve.current_opening': valve_opening
                }
                data_records.append(record)
                
                # 发送数据更新信号（每10个周期发送一次，避免UI阻塞）
                if len(data_records) % Constants.DATA_UPDATE_INTERVAL == 0:
                    self.data_updated.emit(record)
                    progress = (clock.current_time / target_sim_time) * 100
                    self.progress_updated.emit(progress, len(data_records))
            
            # 发送完成信号
            self.finished.emit(data_records)
            
        except Exception as e:
            logger.error(f"Simulation error: {e}")
            import traceback
            traceback.print_exc()
            data_records = []
        finally:
            # 确保时钟资源被正确清理
            if clock:
                try:
                    clock.stop()
                except Exception as e:
                    logger.warning(f"Error stopping clock: {e}")
            # 如果异常发生，发送空列表
            if not data_records:
                self.finished.emit([])


class OPCUAServerThread(QThread):
    """OPCUA Server运行线程"""
    
    # 信号：进度更新
    progress_updated = pyqtSignal(float, int, str)  # (进度百分比, 当前索引, 当前时间)
    # 信号：状态更新
    status_updated = pyqtSignal(str)  # 状态消息
    # 信号：完成
    finished = pyqtSignal()
    # 信号：错误
    error_occurred = pyqtSignal(str)  # 错误消息
    
    def __init__(self, data_records: List[Dict[str, Any]], port: int, instance_name: str = "PLC"):
        """
        初始化OPCUA Server线程
        
        Args:
            data_records: 数据记录列表
            port: OPCUA Server端口
            instance_name: 实例名称，用于生成节点ID前缀，如"PID_TEST_1"
        """
        super().__init__()
        self.data_records = data_records
        self.port = port
        self.instance_name = instance_name
        self._running = False
        self._server = None
        self._nodes = {}  # 存储节点：参数名 -> 节点对象
        self._loop = None
        self._current_index = 0
        
    def stop(self):
        """停止服务器"""
        self._running = False
    
    def run(self):
        """运行OPCUA Server和数据轮询"""
        try:
            # 创建新的事件循环
            self._loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self._loop)
            
            # 运行异步任务
            self._loop.run_until_complete(self._run_server())
            
        except Exception as e:
            self.error_occurred.emit(f"服务器运行错误: {str(e)}")
            import traceback
            traceback.print_exc()
        finally:
            if self._loop:
                self._loop.close()
    
    async def _run_server(self):
        """运行OPCUA Server"""
        try:
            # 初始化服务器
            await self._init_server()
            
            # 创建节点
            await self._create_nodes()
            
            # 启动服务器
            self._running = True
            self.status_updated.emit(f"OPCUA Server已启动，端口: {self.port}")
            
            # 启动数据轮询任务（循环播放）
            asyncio.create_task(self._poll_data_loop())
            
            # 运行服务器（阻塞）
            async with self._server:
                while self._running:
                    await asyncio.sleep(0.1)
            
        except Exception as e:
            self.error_occurred.emit(f"服务器初始化错误: {str(e)}")
            import traceback
            traceback.print_exc()
        finally:
            if self._server:
                try:
                    await self._server.stop()
                except Exception as e:
                    logger.warning(f"Error stopping OPCUA server: {e}")
            self.finished.emit()
    
    async def _init_server(self):
        """初始化OPCUA Server"""
        self.status_updated.emit("正在初始化OPCUA Server...")
        
        # 创建Server
        self._server = Server()
        await self._server.init()
        
        # 设置安全策略
        try:
            self._server.set_security_policy([
                ua.SecurityPolicyType.NoSecurity
            ])
        except Exception as e:
            self.status_updated.emit(f"安全策略设置警告: {e}")
        
        # 设置端点
        self._server.set_endpoint(f"opc.tcp://0.0.0.0:{self.port}")
        
        # 设置服务器名称
        self._server.set_server_name("PID Simulation OPCUA Server")
        
        self.status_updated.emit("OPCUA Server初始化完成")
    
    async def _create_nodes(self):
        """创建OPCUA节点"""
        if not self.data_records:
            return
        
        self.status_updated.emit("正在创建OPCUA节点...")
        
        # 获取所有参数名（除了sim_time）
        param_names = set()
        for record in self.data_records:
            param_names.update(record.keys())
        param_names.discard('sim_time')
        param_names = sorted(param_names)
        
        # 获取Objects节点
        objects = self._server.get_objects_node()
        
        # 创建PLC对象（namespace=1）
        namespace_idx = 1
        plc_obj = await objects.add_object(
            namespace_idx,
            "PLC",
            ua.ObjectIds.BaseObjectType
        )
        
        # 为每个参数创建变量节点
        for param_name in param_names:
            try:
                # 获取第一个记录的值作为初始值
                initial_value = self.data_records[0].get(param_name, 0.0)
                
                # 尝试转换为数值
                if isinstance(initial_value, str):
                    try:
                        # 尝试解析字符串（可能是字典或列表）
                        parsed = ast.literal_eval(initial_value)
                        if isinstance(parsed, dict):
                            # 如果是字典，取第一个值
                            initial_value = list(parsed.values())[0] if parsed else 0.0
                        elif isinstance(parsed, list):
                            # 如果是列表，取第一个值
                            initial_value = parsed[0] if parsed else 0.0
                        else:
                            initial_value = float(parsed) if isinstance(parsed, (int, float)) else 0.0
                    except (ValueError, SyntaxError) as e:
                        logger.debug(f"Failed to parse value as literal: {e}")
                        try:
                            initial_value = float(initial_value)
                        except (ValueError, TypeError) as e2:
                            logger.debug(f"Failed to convert to float: {e2}")
                            initial_value = 0.0
                
                # 确保是数值类型
                if not isinstance(initial_value, (int, float)):
                    initial_value = 0.0
                
                # 创建变量节点（使用string类型的NodeId，值为格式化后的位号名）
                # 格式：{实例名}_{param_prefix}.{param_suffix.UPPER}
                # 例如：如果instance_name="PID_TEST_1"，param_name="pid.mv"
                # 则NodeId为字符串"PID_TEST_1_pid.MV"
                # 注意：这里需要从主窗口获取格式化函数，暂时使用简单实现
                if '.' in param_name:
                    param_prefix, param_suffix = param_name.split('.', 1)
                    param_suffix_upper = param_suffix.upper()
                    node_id_string = f"{self.instance_name}_{param_prefix}.{param_suffix_upper}"
                else:
                    node_id_string = f"{self.instance_name}_{param_name.upper()}"
                
                # 显式创建字符串类型的NodeId（传入字符串会自动创建String类型的NodeId）
                node_id = ua.NodeId(node_id_string, namespace_idx)
                # 使用NodeId对象和Variant创建变量节点，确保使用字符串类型的NodeId
                var_node = await plc_obj.add_variable(
                    node_id,  # NodeId对象（字符串类型，值为格式化后的位号名）
                    node_id_string,  # 节点的显示名称（BrowseName）
                    ua.Variant(initial_value, ua.VariantType.Double)  # 使用Variant包装值
                )
                
                # 设置节点属性
                await var_node.set_writable(False)  # 只读
                
                # 存储节点
                self._nodes[param_name] = var_node
                
            except Exception as e:
                self.status_updated.emit(f"创建节点 {param_name} 失败: {str(e)}")
        
        self.status_updated.emit(f"已创建 {len(self._nodes)} 个节点（实例名: {self.instance_name}）")
    
    async def _poll_data_loop(self):
        """循环轮询数据"""
        if not self.data_records:
            return
        
        # 计算时间间隔（从数据中获取）
        time_intervals = []
        for i in range(1, len(self.data_records)):
            prev_time = self.data_records[i-1]['sim_time']
            curr_time = self.data_records[i]['sim_time']
            interval = curr_time - prev_time
            time_intervals.append(interval)
        
        # 如果没有时间间隔，使用默认值
        if not time_intervals:
            default_interval = Constants.DEFAULT_TIME_INTERVAL
        else:
            # 使用第一个时间间隔作为默认值
            default_interval = time_intervals[0] if time_intervals else Constants.DEFAULT_TIME_INTERVAL
        
        self.status_updated.emit(f"开始数据轮询（循环播放），时间间隔: {default_interval}秒")
        
        # 循环播放数据
        cycle_count = 0
        while self._running:
            cycle_count += 1
            self.status_updated.emit(f"开始第 {cycle_count} 轮循环播放")
            
            # 从第一个记录开始
            self._current_index = 0
            
            while self._running and self._current_index < len(self.data_records):
                record = self.data_records[self._current_index]
                
                # 更新所有节点的值
                for param_name, node in self._nodes.items():
                    try:
                        value = record.get(param_name)
                        
                        # 处理字符串值（可能是字典或列表）
                        if isinstance(value, str):
                            try:
                                parsed = ast.literal_eval(value)
                                if isinstance(parsed, dict):
                                    # 如果是字典，取第一个值
                                    value = list(parsed.values())[0] if parsed else 0.0
                                elif isinstance(parsed, list):
                                    # 如果是列表，取第一个值
                                    value = parsed[0] if parsed else 0.0
                                else:
                                    value = float(parsed) if isinstance(parsed, (int, float)) else 0.0
                            except (ValueError, SyntaxError) as e:
                                logger.debug(f"Failed to parse value as literal: {e}")
                                try:
                                    value = float(value)
                                except (ValueError, TypeError) as e2:
                                    logger.debug(f"Failed to convert to float: {e2}")
                                    value = 0.0
                        
                        # 确保是数值类型
                        if not isinstance(value, (int, float)):
                            value = 0.0
                        
                        # 更新节点值
                        await node.write_value(value)
                        
                    except Exception as e:
                        self.status_updated.emit(f"更新节点 {param_name} 失败: {str(e)}")
                
                # 更新进度（相对于当前循环）
                progress = (self._current_index + 1) / len(self.data_records) * 100
                sim_time = record.get('sim_time', 0)
                self.progress_updated.emit(progress, self._current_index + 1, f"{sim_time:.1f}s (第{cycle_count}轮)")
                
                # 移动到下一个记录
                self._current_index += 1
                
                # 如果还有下一个记录，等待相应的时间间隔
                if self._current_index < len(self.data_records):
                    # 计算到下一个记录的时间间隔
                    if self._current_index < len(time_intervals):
                        interval = time_intervals[self._current_index - 1]
                    else:
                        interval = default_interval
                    
                    # 等待时间间隔
                    await asyncio.sleep(interval)
                else:
                    # 当前循环完成，等待一小段时间后开始下一轮
                    self.status_updated.emit(f"第 {cycle_count} 轮循环播放完成，准备开始下一轮...")
                    await asyncio.sleep(0.5)


class UnifiedToolWindow(QMainWindow):
    """统一工具主窗口"""
    
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PID模拟与OPCUA Server工具 v3")
        self.setGeometry(100, 100, 1600, 900)
        
        # 数据存储
        self.data_records: List[Dict[str, Any]] = []
        self.simulation_thread: Optional[SimulationThread] = None
        self.server_thread: Optional[OPCUAServerThread] = None
        
        # 创建主界面
        self._create_ui()
        
        # 设置默认值
        self._set_default_values()
    
    def _create_ui(self):
        """创建用户界面"""
        # 主窗口部件
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        
        # 主布局（垂直布局）
        main_layout = QVBoxLayout()
        main_widget.setLayout(main_layout)
        
        # 上半部分：PID模拟区域（水平布局：左侧配置 + 右侧图表）
        sim_layout = QHBoxLayout()
        
        # 左侧：参数配置区域
        left_panel = self._create_simulation_left_panel()
        sim_layout.addWidget(left_panel, stretch=1)
        
        # 右侧：图表区域
        right_panel = self._create_simulation_right_panel()
        sim_layout.addWidget(right_panel, stretch=2)
        
        main_layout.addLayout(sim_layout)
        
        # 添加分隔线
        separator = QFrame()
        separator.setFrameShape(QFrame.Shape.HLine)
        separator.setFrameShadow(QFrame.Shadow.Sunken)
        separator.setLineWidth(2)
        main_layout.addWidget(separator)
        
        # 下半部分：OPCUA Server区域
        server_panel = self._create_server_panel()
        main_layout.addWidget(server_panel)
        
        # 右下角版本信息标签
        version_layout = QHBoxLayout()
        version_layout.addStretch()  # 左侧弹性空间，将label推到右侧
        self.version_label = QLabel("pid_simu_ua_server_v3 designed by @yuzechao")
        self.version_label.setStyleSheet("color: #888888; font-size: 10px; padding: 5px;")
        version_layout.addWidget(self.version_label)
        main_layout.addLayout(version_layout)
    
    def _create_simulation_left_panel(self) -> QWidget:
        """创建模拟左侧参数配置面板"""
        panel = QWidget()
        layout = QVBoxLayout()
        panel.setLayout(layout)
        
        # 水箱参数配置
        tank_group = QGroupBox("水箱参数")
        tank_layout = QGridLayout()
        
        self.tank_height = QLineEdit()
        self.tank_radius = QLineEdit()
        self.tank_inlet_area = QLineEdit()
        self.tank_inlet_velocity = QLineEdit()
        self.tank_outlet_area = QLineEdit()
        self.tank_initial_level = QLineEdit()
        
        tank_layout.addWidget(QLabel("高度 (m):"), 0, 0)
        tank_layout.addWidget(self.tank_height, 0, 1)
        tank_layout.addWidget(QLabel("半径 (m):"), 1, 0)
        tank_layout.addWidget(self.tank_radius, 1, 1)
        tank_layout.addWidget(QLabel("入水口面积 (m²):"), 2, 0)
        tank_layout.addWidget(self.tank_inlet_area, 2, 1)
        tank_layout.addWidget(QLabel("入水速度 (m/s):"), 3, 0)
        tank_layout.addWidget(self.tank_inlet_velocity, 3, 1)
        tank_layout.addWidget(QLabel("出水口面积 (m²):"), 4, 0)
        tank_layout.addWidget(self.tank_outlet_area, 4, 1)
        tank_layout.addWidget(QLabel("初始水位 (m):"), 5, 0)
        tank_layout.addWidget(self.tank_initial_level, 5, 1)
        
        tank_group.setLayout(tank_layout)
        layout.addWidget(tank_group)
        
        # 阀门参数配置
        valve_group = QGroupBox("阀门参数")
        valve_layout = QGridLayout()
        
        self.valve_min_opening = QLineEdit()
        self.valve_max_opening = QLineEdit()
        self.valve_full_travel_time = QLineEdit()
        
        valve_layout.addWidget(QLabel("最小开度 (%):"), 0, 0)
        valve_layout.addWidget(self.valve_min_opening, 0, 1)
        valve_layout.addWidget(QLabel("最大开度 (%):"), 1, 0)
        valve_layout.addWidget(self.valve_max_opening, 1, 1)
        valve_layout.addWidget(QLabel("满行程时间 (s):"), 2, 0)
        valve_layout.addWidget(self.valve_full_travel_time, 2, 1)
        
        valve_group.setLayout(valve_layout)
        layout.addWidget(valve_group)
        
        # PID参数配置
        pid_group = QGroupBox("PID参数")
        pid_layout = QGridLayout()
        
        self.pid_kp = QLineEdit()
        self.pid_ti = QLineEdit()
        self.pid_td = QLineEdit()
        self.pid_sv = QLineEdit()  # 改为逗号分隔的多个值
        self.pid_pv = QLineEdit()
        self.pid_mv = QLineEdit()
        self.pid_h = QLineEdit()
        self.pid_l = QLineEdit()
        
        pid_layout.addWidget(QLabel("比例系数 (Kp):"), 0, 0)
        pid_layout.addWidget(self.pid_kp, 0, 1)
        pid_layout.addWidget(QLabel("积分时间 (Ti):"), 1, 0)
        pid_layout.addWidget(self.pid_ti, 1, 1)
        pid_layout.addWidget(QLabel("微分时间 (Td):"), 2, 0)
        pid_layout.addWidget(self.pid_td, 2, 1)
        pid_layout.addWidget(QLabel("设定值 (SV，逗号分隔):"), 3, 0)
        pid_layout.addWidget(self.pid_sv, 3, 1)
        pid_layout.addWidget(QLabel("过程值 (PV):"), 4, 0)
        pid_layout.addWidget(self.pid_pv, 4, 1)
        pid_layout.addWidget(QLabel("输出值 (MV):"), 5, 0)
        pid_layout.addWidget(self.pid_mv, 5, 1)
        pid_layout.addWidget(QLabel("输出上限 (H):"), 6, 0)
        pid_layout.addWidget(self.pid_h, 6, 1)
        pid_layout.addWidget(QLabel("输出下限 (L):"), 7, 0)
        pid_layout.addWidget(self.pid_l, 7, 1)
        
        pid_group.setLayout(pid_layout)
        layout.addWidget(pid_group)
        
        # 模拟时长配置
        duration_group = QGroupBox("模拟设置")
        duration_layout = QVBoxLayout()
        
        duration_input_layout = QHBoxLayout()
        duration_input_layout.addWidget(QLabel("模拟时长 (秒):"))
        self.duration_input = QLineEdit()
        duration_input_layout.addWidget(self.duration_input)
        duration_layout.addLayout(duration_input_layout)
        
        duration_group.setLayout(duration_layout)
        layout.addWidget(duration_group)
        
        # 实例名配置（移到模板按钮上方）
        instance_layout = QHBoxLayout()
        instance_layout.addWidget(QLabel("实例名:"))
        self.instance_name_input = QLineEdit()
        self.instance_name_input.setText("PID_TEST_1")
        self.instance_name_input.setMaximumWidth(150)
        self.instance_name_input.setToolTip("用于OPCUA节点和导出数据的位号前缀")
        instance_layout.addWidget(self.instance_name_input)
        instance_layout.addStretch()
        layout.addLayout(instance_layout)
        
        # 模板管理按钮（并排）
        template_layout = QHBoxLayout()
        self.export_template_button = QPushButton("导出模板")
        self.export_template_button.setStyleSheet("background-color: #FF9800; color: white; font-weight: bold; padding: 8px;")
        self.export_template_button.clicked.connect(self.export_template)
        template_layout.addWidget(self.export_template_button)
        
        self.import_template_button = QPushButton("导入模板")
        self.import_template_button.setStyleSheet("background-color: #9C27B0; color: white; font-weight: bold; padding: 8px;")
        self.import_template_button.clicked.connect(self.import_template)
        template_layout.addWidget(self.import_template_button)
        layout.addLayout(template_layout)
        
        # 控制按钮
        self.start_sim_button = QPushButton("开始模拟")
        self.start_sim_button.setStyleSheet("background-color: #4CAF50; color: white; font-weight: bold; padding: 8px;")
        self.start_sim_button.clicked.connect(self.start_simulation)
        layout.addWidget(self.start_sim_button)
        
        # 导出数据按钮和时间拉伸输入框（并排）
        export_layout = QHBoxLayout()
        
        # 时间拉伸输入框
        export_layout.addWidget(QLabel("时间拉伸:"))
        self.time_stretch_input = QLineEdit()
        self.time_stretch_input.setText("1")
        self.time_stretch_input.setMaximumWidth(80)
        self.time_stretch_input.setToolTip("时间拉伸倍数，例如：5表示将时间间隔扩展5倍")
        export_layout.addWidget(self.time_stretch_input)
        
        export_layout.addStretch()
        
        # PID整定模板导出按钮
        self.export_pid_tuning_button = QPushButton("导出数据[PID整定模板]")
        self.export_pid_tuning_button.setStyleSheet("background-color: #9C27B0; color: white; font-weight: bold; padding: 8px;")
        self.export_pid_tuning_button.clicked.connect(self.export_pid_tuning_template)
        self.export_pid_tuning_button.setEnabled(False)
        export_layout.addWidget(self.export_pid_tuning_button)
        
        # 导出数据按钮（预测模板）
        self.export_data_button = QPushButton("导出数据[预测模板]")
        self.export_data_button.setStyleSheet("background-color: #2196F3; color: white; font-weight: bold; padding: 8px;")
        self.export_data_button.clicked.connect(self.export_data_to_csv)
        self.export_data_button.setEnabled(False)
        export_layout.addWidget(self.export_data_button)
        
        layout.addLayout(export_layout)
        
        # TPT导入位号模板导出区域
        tpt_export_layout = QHBoxLayout()
        tpt_export_layout.addWidget(QLabel("数据源名称:"))
        self.tpt_datasource_input = QLineEdit()
        self.tpt_datasource_input.setText("yzc_test")
        self.tpt_datasource_input.setMaximumWidth(150)
        self.tpt_datasource_input.setToolTip("TPT导入位号模板的数据源名称")
        tpt_export_layout.addWidget(self.tpt_datasource_input)
        
        tpt_export_layout.addStretch()
        
        # TPT导入位号模板导出按钮
        self.export_tpt_template_button = QPushButton("TPT导入位号模板")
        self.export_tpt_template_button.setStyleSheet("background-color: #FF5722; color: white; font-weight: bold; padding: 8px;")
        self.export_tpt_template_button.clicked.connect(self.export_tpt_template)
        self.export_tpt_template_button.setEnabled(False)
        tpt_export_layout.addWidget(self.export_tpt_template_button)
        
        layout.addLayout(tpt_export_layout)
        
        # 进度条
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)
        
        # 添加弹性空间
        layout.addStretch()
        
        return panel
    
    def _create_simulation_right_panel(self) -> QWidget:
        """创建模拟右侧图表面板"""
        panel = QWidget()
        layout = QVBoxLayout()
        layout.setSpacing(5)  # 减小间距
        panel.setLayout(layout)
        
        # 图表标题（缩小）
        title_label = QLabel("PID控制曲线")
        title_font = QFont()
        title_font.setPointSize(10)  # 从14减小到10
        title_font.setBold(True)
        title_label.setFont(title_font)
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_label.setMaximumHeight(25)  # 限制标题高度
        layout.addWidget(title_label)
        
        # matplotlib图表（允许纵向拉伸）
        self.figure = Figure(figsize=(10, 6))
        self.canvas = FigureCanvas(self.figure)
        # 移除固定高度限制，允许拉伸
        self.canvas.setMinimumHeight(300)  # 设置最小高度
        layout.addWidget(self.canvas, stretch=1)  # 设置拉伸因子，让图表占据更多空间
        
        # 初始化图表
        self._init_chart()
        
        # 位号显示区域（两行四列）- 放在图表下方
        tag_display_group = QGroupBox("位号列表")
        tag_display_layout = QGridLayout()
        
        # 定义所有位号（8个位号，两行四列）- 使用常量定义
        self.tag_labels = {}
        tag_names = Constants.TAG_DEFINITIONS
        
        for idx, (tag_key, tag_desc) in enumerate(tag_names):
            row = idx // 4
            col = idx % 4
            # 创建标签显示完整位号名
            tag_label = QLabel()
            tag_label.setWordWrap(True)
            tag_label.setStyleSheet("padding: 4px; border: 1px solid #ddd; background-color: #f5f5f5;")
            self.tag_labels[tag_key] = tag_label
            tag_display_layout.addWidget(tag_label, row, col)
        
        tag_display_group.setLayout(tag_display_layout)
        layout.addWidget(tag_display_group)
        
        return panel
    
    def _create_server_panel(self) -> QWidget:
        """创建OPCUA Server面板"""
        panel = QWidget()
        layout = QVBoxLayout()
        panel.setLayout(layout)
        
        # 服务器配置区域
        server_group = QGroupBox("OPCUA服务器配置")
        server_layout = QHBoxLayout()
        
        server_layout.addWidget(QLabel("端口:"))
        self.port_input = QLineEdit()
        self.port_input.setText("18951")
        self.port_input.setMaximumWidth(100)
        server_layout.addWidget(self.port_input)
        
        server_layout.addStretch()
        
        # 控制按钮
        self.start_server_button = QPushButton("启动服务器")
        self.start_server_button.setStyleSheet("background-color: #4CAF50; color: white; font-weight: bold; padding: 8px;")
        self.start_server_button.clicked.connect(self.start_server)
        self.start_server_button.setEnabled(False)
        server_layout.addWidget(self.start_server_button)
        
        self.stop_server_button = QPushButton("停止服务器")
        self.stop_server_button.setStyleSheet("background-color: #f44336; color: white; font-weight: bold; padding: 8px;")
        self.stop_server_button.clicked.connect(self.stop_server)
        self.stop_server_button.setEnabled(False)
        server_layout.addWidget(self.stop_server_button)
        
        server_group.setLayout(server_layout)
        layout.addWidget(server_group)
        
        # 进度显示区域
        progress_group = QGroupBox("数据轮询进度")
        progress_layout = QVBoxLayout()
        
        self.server_progress_bar = QProgressBar()
        self.server_progress_bar.setMinimum(0)
        self.server_progress_bar.setMaximum(100)
        progress_layout.addWidget(self.server_progress_bar)
        
        self.progress_label = QLabel("等待开始...")
        progress_layout.addWidget(self.progress_label)
        
        progress_group.setLayout(progress_layout)
        layout.addWidget(progress_group)
        
        return panel
    
    def _init_chart(self):
        """初始化图表"""
        self.figure.clear()
        ax1 = self.figure.add_subplot(111)
        
        # 创建第二个y轴（用于MV）
        ax2 = ax1.twinx()
        
        # 设置标签和颜色
        ax1.set_xlabel('模拟时间 (秒)', fontsize=12)
        ax1.set_ylabel('SV / PV', fontsize=12, color='blue')
        ax1.tick_params(axis='y', labelcolor='blue')
        
        ax2.set_ylabel('MV', fontsize=12, color='orange')
        ax2.tick_params(axis='y', labelcolor='orange')
        
        ax1.grid(True, alpha=0.3)
        ax1.set_title('PID控制曲线', fontsize=14, fontweight='bold')
        
        self.ax1 = ax1
        self.ax2 = ax2
        
        self.canvas.draw()
    
    def _set_default_values(self):
        """设置默认参数值"""
        # 水箱默认值
        self.tank_height.setText("2.0")
        self.tank_radius.setText("0.5")
        self.tank_inlet_area.setText("0.06")
        self.tank_inlet_velocity.setText("3.0")
        self.tank_outlet_area.setText("0.001")
        self.tank_initial_level.setText("0.0")
        
        # 阀门默认值
        self.valve_min_opening.setText("0.0")
        self.valve_max_opening.setText("100.0")
        self.valve_full_travel_time.setText("5.0")
        
        # PID默认值
        self.pid_kp.setText("12.0")
        self.pid_ti.setText("30.0")
        self.pid_td.setText("0.15")
        self.pid_sv.setText("1.5,0.5,0")  # 默认多个SV值
        self.pid_pv.setText("0.0")
        self.pid_mv.setText("0.0")
        self.pid_h.setText("100.0")
        self.pid_l.setText("0.0")
        
        # 模拟时长默认值
        self.duration_input.setText("900.0")
        
        # 实例名默认值
        self.instance_name_input.setText("PID_TEST_1")
        
        # 连接实例名输入框的信号，当实例名改变时更新位号显示
        if hasattr(self, 'tag_labels'):
            self.instance_name_input.textChanged.connect(self._update_tag_display)
            # 初始化位号显示
            self._update_tag_display()
    
    def _update_tag_display(self):
        """更新位号显示"""
        instance_name = self.instance_name_input.text().strip() or "PID_TEST_1"
        # 使用常量定义的位号描述
        tag_descriptions = Constants.get_tag_descriptions()
        
        for tag_key, tag_label in self.tag_labels.items():
            # 使用新格式：{实例名}_{param_prefix}.{param_suffix.UPPER}
            full_tag_name = self._format_tag_name(instance_name, tag_key)
            tag_desc = tag_descriptions.get(tag_key, tag_key)
            tag_label.setText(f"{full_tag_name}\n({tag_desc})")
    
    def _format_float(self, value: float, precision: int = 6) -> str:
        """格式化浮点数"""
        return f"{value:.{precision}f}"
    
    def _format_tag_name(self, instance_name: str, param_name: str) -> str:
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
    
    def _get_float_value(self, line_edit: QLineEdit, default: str) -> float:
        """获取浮点数值，带默认值和验证"""
        try:
            text = line_edit.text().strip()
            value = float(text) if text else float(default)
            return value
        except ValueError:
            logger.warning(f"Invalid float value in {line_edit.objectName()}, using default: {default}")
            return float(default)
    
    def _get_tank_params(self) -> Dict[str, Any]:
        """获取水箱参数"""
        height = self._get_float_value(self.tank_height, "2.0")
        if height <= 0:
            raise ValueError("水箱高度必须大于0")
        
        radius = self._get_float_value(self.tank_radius, "0.5")
        if radius <= 0:
            raise ValueError("水箱半径必须大于0")
        
        inlet_area = self._get_float_value(self.tank_inlet_area, "0.06")
        if inlet_area <= 0:
            raise ValueError("入水口面积必须大于0")
        
        inlet_velocity = self._get_float_value(self.tank_inlet_velocity, "3.0")
        if inlet_velocity < 0:
            raise ValueError("入水速度不能为负数")
        
        outlet_area = self._get_float_value(self.tank_outlet_area, "0.001")
        if outlet_area <= 0:
            raise ValueError("出水口面积必须大于0")
        
        initial_level = self._get_float_value(self.tank_initial_level, "0.0")
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
    
    def _get_valve_params(self) -> Dict[str, Any]:
        """获取阀门参数"""
        min_opening = self._get_float_value(self.valve_min_opening, "0.0")
        max_opening = self._get_float_value(self.valve_max_opening, "100.0")
        
        if min_opening < 0 or min_opening > 100:
            raise ValueError("最小开度必须在0-100范围内")
        if max_opening < 0 or max_opening > 100:
            raise ValueError("最大开度必须在0-100范围内")
        if min_opening >= max_opening:
            raise ValueError("最大开度必须大于最小开度")
        
        full_travel_time = self._get_float_value(self.valve_full_travel_time, "5.0")
        if full_travel_time <= 0:
            raise ValueError("满行程时间必须大于0")
        
        return {
            'min_opening': min_opening,
            'max_opening': max_opening,
            'full_travel_time': full_travel_time
        }
    
    def _get_pid_params(self) -> Dict[str, Any]:
        """获取PID参数"""
        kp = self._get_float_value(self.pid_kp, "12.0")
        if kp < 0:
            raise ValueError("比例系数不能为负数")
        
        ti = self._get_float_value(self.pid_ti, "30.0")
        if ti < 0:
            raise ValueError("积分时间不能为负数")
        
        td = self._get_float_value(self.pid_td, "0.15")
        if td < 0:
            raise ValueError("微分时间不能为负数")
        
        h = self._get_float_value(self.pid_h, "100.0")
        l = self._get_float_value(self.pid_l, "0.0")
        if h <= l:
            raise ValueError("输出上限必须大于输出下限")
        
        return {
            'kp': kp,
            'ti': ti,
            'td': td,
            'sv': float(self.pid_sv.text().split(',')[0] if self.pid_sv.text() else "0.0"),  # 使用第一个值作为初始值
            'pv': self._get_float_value(self.pid_pv, "0.0"),
            'mv': self._get_float_value(self.pid_mv, "0.0"),
            'h': h,
            'l': l
        }
    
    def _get_sv_values(self) -> List[float]:
        """获取SV设定值列表（逗号分隔）"""
        sv_text = self.pid_sv.text().strip()
        if not sv_text:
            return [0.0]
        
        try:
            # 按逗号分割并转换为浮点数列表
            sv_values = [float(x.strip()) for x in sv_text.split(',') if x.strip()]
            return sv_values if sv_values else [0.0]
        except ValueError:
            QMessageBox.warning(self, "警告", "SV设定值格式错误，请使用逗号分隔的数字，如：0,1.5,0")
            return [0.0]
    
    def start_simulation(self):
        """开始模拟"""
        try:
            # 获取参数
            tank_params = self._get_tank_params()
            valve_params = self._get_valve_params()
            pid_params = self._get_pid_params()
            duration = float(self.duration_input.text() or "900.0")
            sv_values = self._get_sv_values()
            
            if not sv_values:
                QMessageBox.warning(self, "警告", "请至少输入一个SV设定值！")
                return
            
            # 清空之前的数据
            self.data_records = []
            
            # 重置图表
            self._init_chart()
            
            # 禁用开始按钮
            self.start_sim_button.setEnabled(False)
            self.start_sim_button.setText("模拟中...")
            
            # 显示进度条
            self.progress_bar.setVisible(True)
            self.progress_bar.setValue(0)
            
            # 创建并启动模拟线程
            self.simulation_thread = SimulationThread(
                tank_params=tank_params,
                valve_params=valve_params,
                pid_params=pid_params,
                duration=duration,
                sv_values=sv_values
            )
            self.simulation_thread.progress_updated.connect(self._on_progress_updated)
            self.simulation_thread.data_updated.connect(self._on_data_updated)
            self.simulation_thread.finished.connect(self._on_simulation_finished)
            self.simulation_thread.start()
            
        except ValueError as e:
            QMessageBox.warning(self, "输入错误", f"参数验证失败：\n{str(e)}")
            self.start_sim_button.setEnabled(True)
            self.start_sim_button.setText("开始模拟")
            self.progress_bar.setVisible(False)
        except Exception as e:
            QMessageBox.critical(self, "错误", f"启动模拟失败: {str(e)}")
            logger.exception("Error starting simulation")
            self.start_sim_button.setEnabled(True)
            self.start_sim_button.setText("开始模拟")
            self.progress_bar.setVisible(False)
    
    def _on_progress_updated(self, progress: float, record_count: int):
        """进度更新回调"""
        self.progress_bar.setValue(int(progress))
    
    def _on_data_updated(self, record: Dict[str, Any]):
        """数据更新回调（实时更新图表）"""
        self.data_records.append(record)
        
        # 每50个记录更新一次图表（避免UI阻塞）
        if len(self.data_records) % 50 == 0:
            self._update_chart()
    
    def _on_simulation_finished(self, data_records: List[Dict[str, Any]]):
        """模拟完成回调"""
        self.data_records = data_records
        
        # 更新图表
        self._update_chart()
        
        # 恢复按钮状态
        self.start_sim_button.setEnabled(True)
        self.start_sim_button.setText("开始模拟")
        self.progress_bar.setVisible(False)
        
        # 启用启动服务器按钮和导出数据按钮
        self.start_server_button.setEnabled(True)
        self.export_data_button.setEnabled(True)
        self.export_pid_tuning_button.setEnabled(True)
        self.export_tpt_template_button.setEnabled(True)
        
        QMessageBox.information(self, "完成", "模拟完成！")
    
    def _update_chart(self):
        """更新图表"""
        if not self.data_records:
            return
        
        # 清空图表
        self.ax1.clear()
        self.ax2.clear()
        
        # 提取数据
        sim_times = [r['sim_time'] for r in self.data_records]
        sv_values = [r.get('pid.sv', 0) for r in self.data_records]
        pv_values = [r.get('pid.pv', 0) for r in self.data_records]
        mv_values = [r.get('pid.mv', 0) for r in self.data_records]
        
        # 绘制SV和PV（左侧y轴）
        self.ax1.plot(sim_times, sv_values, label='SV', color='blue', linewidth=1.5, alpha=0.7)
        self.ax1.plot(sim_times, pv_values, label='PV', color='cyan', linewidth=1.5, alpha=0.7)
        
        # 绘制MV（右侧y轴）
        self.ax2.plot(sim_times, mv_values, label='MV', color='orange', linewidth=1.5, alpha=0.7, linestyle='--')
        
        # 设置标签和标题
        self.ax1.set_xlabel('模拟时间 (秒)', fontsize=12)
        self.ax1.set_ylabel('SV / PV', fontsize=12, color='blue')
        self.ax1.tick_params(axis='y', labelcolor='blue')
        self.ax1.grid(True, alpha=0.3)
        self.ax1.set_title('PID控制曲线', fontsize=14, fontweight='bold')
        
        self.ax2.set_ylabel('MV', fontsize=12, color='orange')
        self.ax2.tick_params(axis='y', labelcolor='orange')
        
        # 添加图例
        lines1, labels1 = self.ax1.get_legend_handles_labels()
        lines2, labels2 = self.ax2.get_legend_handles_labels()
        self.ax1.legend(lines1 + lines2, labels1 + labels2, loc='upper left')
        
        # 刷新画布
        self.canvas.draw()
    
    def start_server(self):
        """启动OPCUA Server"""
        if not self.data_records:
            QMessageBox.warning(self, "警告", "请先运行模拟！")
            return
        
        # 验证端口号
        try:
            port = int(self.port_input.text() or "18951")
            if not (Constants.MIN_PORT <= port <= Constants.MAX_PORT):
                QMessageBox.warning(self, "警告", f"端口号必须在{Constants.MIN_PORT}-{Constants.MAX_PORT}范围内！")
                return
        except ValueError:
            QMessageBox.warning(self, "警告", "端口号必须是数字！")
            return
        
        # 检查端口是否被占用
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(1)
            result = sock.connect_ex(('127.0.0.1', port))
            sock.close()
            if result == 0:
                reply = QMessageBox.question(
                    self, 
                    "端口占用", 
                    f"端口 {port} 已被占用，是否仍要继续？",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                )
                if reply == QMessageBox.StandardButton.No:
                    return
        except Exception as e:
            logger.warning(f"Failed to check port availability: {e}")
            # 端口检查失败不影响启动，继续执行
        
        # 获取实例名（如果为空则使用默认值）
        instance_name = self.instance_name_input.text().strip() or "PID_TEST_1"
        
        # 禁用开始按钮，启用停止按钮
        self.start_server_button.setEnabled(False)
        self.stop_server_button.setEnabled(True)
        
        # 重置进度
        self.server_progress_bar.setValue(0)
        self.progress_label.setText("正在启动服务器...")
        
        # 创建并启动服务器线程
        self.server_thread = OPCUAServerThread(
            data_records=self.data_records,
            port=port,
            instance_name=instance_name
        )
        self.server_thread.progress_updated.connect(self._on_server_progress_updated)
        self.server_thread.status_updated.connect(self._on_status_updated)
        self.server_thread.finished.connect(self._on_server_finished)
        self.server_thread.error_occurred.connect(self._on_error_occurred)
        self.server_thread.start()
    
    def stop_server(self):
        """停止OPCUA Server"""
        if self.server_thread:
            self.server_thread.stop()
            self.progress_label.setText("正在停止服务器...")
    
    def _on_server_progress_updated(self, progress: float, current_index: int, sim_time: str):
        """服务器进度更新回调"""
        self.server_progress_bar.setValue(int(progress))
        self.progress_label.setText(f"进度: {current_index}/{len(self.data_records)} ({progress:.1f}%) - {sim_time}")
    
    def _on_status_updated(self, message: str):
        """状态更新回调"""
        self.progress_label.setText(message)
    
    def _on_server_finished(self):
        """服务器完成回调"""
        self.start_server_button.setEnabled(True)
        self.stop_server_button.setEnabled(False)
        self.progress_label.setText("服务器已停止")
    
    def _on_error_occurred(self, error_message: str):
        """错误回调"""
        QMessageBox.critical(self, "错误", error_message)
        self._on_server_finished()
    
    def export_template(self):
        """
        导出模板：保存所有参数配置到JSON文件
        """
        try:
            # 收集所有参数配置
            template = {
                'tank': {
                    'height': self.tank_height.text(),
                    'radius': self.tank_radius.text(),
                    'inlet_area': self.tank_inlet_area.text(),
                    'inlet_velocity': self.tank_inlet_velocity.text(),
                    'outlet_area': self.tank_outlet_area.text(),
                    'initial_level': self.tank_initial_level.text()
                },
                'valve': {
                    'min_opening': self.valve_min_opening.text(),
                    'max_opening': self.valve_max_opening.text(),
                    'full_travel_time': self.valve_full_travel_time.text()
                },
                'pid': {
                    'kp': self.pid_kp.text(),
                    'ti': self.pid_ti.text(),
                    'td': self.pid_td.text(),
                    'sv': self.pid_sv.text(),
                    'pv': self.pid_pv.text(),
                    'mv': self.pid_mv.text(),
                    'h': self.pid_h.text(),
                    'l': self.pid_l.text()
                },
                'simulation': {
                    'duration': self.duration_input.text()
                }
            }
            
            # 选择保存文件
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            default_filename = f"pid_template_{timestamp}.json"
            
            filename, _ = QFileDialog.getSaveFileName(
                self,
                "导出模板",
                default_filename,
                "JSON Files (*.json);;All Files (*)"
            )
            
            if not filename:
                return
            
            # 验证文件路径安全性
            if not os.path.isabs(filename):
                # 处理相对路径，转换为绝对路径
                filename = os.path.abspath(filename)
            
            # 检查目录是否存在，是否有写权限
            dir_path = os.path.dirname(filename)
            if dir_path and not os.path.exists(dir_path):
                try:
                    os.makedirs(dir_path, exist_ok=True)
                except OSError as e:
                    QMessageBox.critical(self, "错误", f"无法创建目录: {dir_path}\n{str(e)}")
                    return
            
            # 保存到JSON文件
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(template, f, ensure_ascii=False, indent=4)
            
            QMessageBox.information(self, "成功", f"模板已保存到：\n{filename}")
            
        except PermissionError as e:
            QMessageBox.critical(self, "错误", f"没有权限访问文件：\n{str(e)}")
        except OSError as e:
            QMessageBox.critical(self, "错误", f"文件操作失败：\n{str(e)}")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"导出模板失败：\n{str(e)}")
            logger.exception("Error exporting template")
    
    def import_template(self):
        """
        导入模板：从JSON文件加载所有参数配置
        """
        try:
            # 选择文件
            filename, _ = QFileDialog.getOpenFileName(
                self,
                "导入模板",
                "",
                "JSON Files (*.json);;All Files (*)"
            )
            
            if not filename:
                return
            
            # 验证文件路径安全性
            if not os.path.exists(filename):
                QMessageBox.critical(self, "错误", f"文件不存在：\n{filename}")
                return
            
            # 读取JSON文件
            with open(filename, 'r', encoding='utf-8') as f:
                template = json.load(f)
            
            # 加载水箱参数
            if 'tank' in template:
                tank = template['tank']
                self.tank_height.setText(str(tank.get('height', '')))
                self.tank_radius.setText(str(tank.get('radius', '')))
                self.tank_inlet_area.setText(str(tank.get('inlet_area', '')))
                self.tank_inlet_velocity.setText(str(tank.get('inlet_velocity', '')))
                self.tank_outlet_area.setText(str(tank.get('outlet_area', '')))
                self.tank_initial_level.setText(str(tank.get('initial_level', '')))
            
            # 加载阀门参数
            if 'valve' in template:
                valve = template['valve']
                self.valve_min_opening.setText(str(valve.get('min_opening', '')))
                self.valve_max_opening.setText(str(valve.get('max_opening', '')))
                self.valve_full_travel_time.setText(str(valve.get('full_travel_time', '')))
            
            # 加载PID参数
            if 'pid' in template:
                pid = template['pid']
                self.pid_kp.setText(str(pid.get('kp', '')))
                self.pid_ti.setText(str(pid.get('ti', '')))
                self.pid_td.setText(str(pid.get('td', '')))
                self.pid_sv.setText(str(pid.get('sv', '')))
                self.pid_pv.setText(str(pid.get('pv', '')))
                self.pid_mv.setText(str(pid.get('mv', '')))
                self.pid_h.setText(str(pid.get('h', '')))
                self.pid_l.setText(str(pid.get('l', '')))
            
            # 加载模拟设置
            if 'simulation' in template:
                sim = template['simulation']
                self.duration_input.setText(str(sim.get('duration', '')))
            
            QMessageBox.information(self, "成功", f"模板已从以下文件加载：\n{filename}")
            
        except FileNotFoundError as e:
            QMessageBox.critical(self, "错误", f"文件未找到：\n{str(e)}")
        except PermissionError as e:
            QMessageBox.critical(self, "错误", f"没有权限访问文件：\n{str(e)}")
        except json.JSONDecodeError as e:
            QMessageBox.critical(self, "错误", f"JSON文件格式错误：\n{str(e)}")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"导入模板失败：\n{str(e)}")
            logger.exception("Error importing template")
    
    def export_data_to_csv(self):
        """
        导出数据到CSV文件
        
        格式要求：
        - 第一行：timeStamp PID.mv PID.sv PID.pv PID.Kp PID.Td PID.Ti
        - 第二行：时间戳 PID控制输出 PID预设值 PID输入值 比例系数 积分时间 微分时间
        - 第三行开始：时间戳（格式：2024/6/3 19:08:45） 具体数据值
        - 每秒采样一个数据
        """
        if not self.data_records:
            QMessageBox.warning(self, "警告", "没有数据可导出！请先运行模拟。")
            return
        
        # 选择保存文件
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        default_filename = f"pid_export_{timestamp}.csv"
        
        filename, _ = QFileDialog.getSaveFileName(
            self,
            "导出数据到CSV",
            default_filename,
            "CSV Files (*.csv);;All Files (*)"
        )
        
        if not filename:
            return
        
        # 验证文件路径安全性
        if not os.path.isabs(filename):
            # 处理相对路径，转换为绝对路径
            filename = os.path.abspath(filename)
        
        # 检查目录是否存在，是否有写权限
        dir_path = os.path.dirname(filename)
        if dir_path and not os.path.exists(dir_path):
            try:
                os.makedirs(dir_path, exist_ok=True)
            except OSError as e:
                QMessageBox.critical(self, "错误", f"无法创建目录: {dir_path}\n{str(e)}")
                return
        
        try:
            # 获取时间拉伸倍数
            try:
                time_stretch = float(self.time_stretch_input.text() or "1")
                if time_stretch <= 0:
                    QMessageBox.warning(self, "警告", "时间拉伸倍数必须大于0！")
                    return
            except ValueError:
                QMessageBox.warning(self, "警告", "时间拉伸倍数格式错误，请输入数字！")
                return
            
            # 获取PID参数（从第一条记录中获取，因为Kp, Td, Ti在模拟过程中是固定的）
            if not self.data_records:
                QMessageBox.warning(self, "警告", "没有数据可导出！")
                return
            
            # 每秒采样一个数据
            # 假设数据记录的时间间隔是cycle_time（默认0.5秒），所以每2个记录采样1个
            # 但用户要求每秒1个，所以需要根据sim_time来采样
            sampled_records = []
            last_sampled_time = -1.0
            
            for record in self.data_records:
                sim_time = record.get('sim_time', 0)
                # 如果当前时间与上次采样时间相差>=1秒，则采样
                if sim_time - last_sampled_time >= 1.0:
                    sampled_records.append(record)
                    last_sampled_time = sim_time
            
            # 如果没有采样到数据，至少采样第一个和最后一个
            if not sampled_records:
                sampled_records = [self.data_records[0]]
                if len(self.data_records) > 1:
                    sampled_records.append(self.data_records[-1])
            
            # 获取实例名（用于位号前缀）
            instance_name = self.instance_name_input.text().strip() or "PID_TEST_1"
            
            # 写入CSV文件
            with open(filename, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                
                # 第一行：timeStamp {实例名}_pid.MV {实例名}_pid.SV ...（使用新格式）
                writer.writerow([
                    'timeStamp',
                    self._format_tag_name(instance_name, 'pid.mv'),
                    self._format_tag_name(instance_name, 'pid.sv'),
                    self._format_tag_name(instance_name, 'pid.pv'),
                    self._format_tag_name(instance_name, 'pid.kp'),
                    self._format_tag_name(instance_name, 'pid.td'),
                    self._format_tag_name(instance_name, 'pid.ti'),
                    self._format_tag_name(instance_name, 'tank.level'),
                    self._format_tag_name(instance_name, 'valve.current_opening')
                ])
                
                # 第二行：时间戳 PID控制输出 PID预设值 PID输入值 比例系数 积分时间 微分时间 水箱液位 阀门开度
                writer.writerow([
                    '时间戳',
                    'PID控制输出',
                    'PID预设值',
                    'PID输入值',
                    '比例系数',
                    '积分时间',
                    '微分时间',
                    '水箱液位',
                    '阀门开度'
                ])
                
                # 第三行开始：时间戳（格式：2024/6/3 19:08:45） 具体数据值
                # 使用固定的基准时间，然后加上sim_time * time_stretch
                base_time = Constants.DEFAULT_BASE_TIME
                
                for record in sampled_records:
                    sim_time = record.get('sim_time', 0)
                    # 计算时间戳：基准时间 + sim_time * time_stretch秒数（应用时间拉伸）
                    stretched_time = sim_time * time_stretch
                    record_time = base_time + timedelta(seconds=stretched_time)
                    
                    # 格式：2024/6/3 19:08:45（注意：月份和日期不补零）
                    time_str = f"{record_time.year}-{record_time.month}-{record_time.day} {record_time.hour}:{record_time.minute:02d}:{record_time.second:02d}"
                    
                    # 获取数据值（包含所有8个位号）
                    pid_mv = record.get('pid.mv', 0)
                    pid_sv = record.get('pid.sv', 0)
                    pid_pv = record.get('pid.pv', 0)
                    pid_kp = record.get('pid.kp', 0)
                    pid_td = record.get('pid.td', 0)
                    pid_ti = record.get('pid.ti', 0)
                    tank_level = record.get('tank.level', 0)
                    valve_opening = record.get('valve.current_opening', 0)
                    
                    writer.writerow([
                        time_str,
                        self._format_float(pid_mv),
                        self._format_float(pid_sv),
                        self._format_float(pid_pv),
                        self._format_float(pid_kp),
                        self._format_float(pid_td),
                        self._format_float(pid_ti),
                        self._format_float(tank_level),
                        self._format_float(valve_opening)
                    ])
            
            # 计算原始时间跨度和拉伸后的时间跨度
            if sampled_records:
                original_duration = sampled_records[-1].get('sim_time', 0) - sampled_records[0].get('sim_time', 0)
                stretched_duration = original_duration * time_stretch
            else:
                original_duration = 0
                stretched_duration = 0
            
            stretch_info = f"，时间拉伸倍数：{time_stretch}" if time_stretch != 1 else ""
            QMessageBox.information(
                self, 
                "导出成功", 
                f"数据已成功导出到：\n{filename}\n\n"
                f"共导出 {len(sampled_records)} 条记录（每秒1条）{stretch_info}。\n"
                f"原始时间跨度：{original_duration:.1f}秒，拉伸后时间跨度：{stretched_duration:.1f}秒。"
            )
            
        except FileNotFoundError as e:
            QMessageBox.critical(self, "导出失败", f"文件未找到：\n{str(e)}")
        except PermissionError as e:
            QMessageBox.critical(self, "导出失败", f"没有权限访问文件：\n{str(e)}")
        except OSError as e:
            QMessageBox.critical(self, "导出失败", f"文件操作失败：\n{str(e)}")
        except Exception as e:
            QMessageBox.critical(self, "导出失败", f"导出数据时发生错误：\n{str(e)}")
            logger.exception("Error exporting data to CSV")
    
    def export_pid_tuning_template(self):
        """
        导出PID整定模板（CSV格式）
        
        格式要求：
        - 第一行：时间 PV MV SV三个格式化后的位号名
        - 第二行开始：数据行，时间格式为 yyyy-MM-dd HH:mm:ss
        - 只导出PV、MV、SV三个位号
        """
        if not self.data_records:
            QMessageBox.warning(self, "警告", "没有数据可导出！请先运行模拟。")
            return
        
        # 选择保存文件
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        default_filename = f"pid_tuning_export_{timestamp}.csv"
        
        filename, _ = QFileDialog.getSaveFileName(
            self,
            "导出PID整定模板",
            default_filename,
            "CSV Files (*.csv);;All Files (*)"
        )
        
        if not filename:
            return
        
        # 验证文件路径安全性
        if not os.path.isabs(filename):
            filename = os.path.abspath(filename)
        
        # 检查目录是否存在
        dir_path = os.path.dirname(filename)
        if dir_path and not os.path.exists(dir_path):
            try:
                os.makedirs(dir_path, exist_ok=True)
            except OSError as e:
                QMessageBox.critical(self, "错误", f"无法创建目录: {dir_path}\n{str(e)}")
                return
        
        try:
            # 获取时间拉伸倍数
            try:
                time_stretch = float(self.time_stretch_input.text() or "1")
                if time_stretch <= 0:
                    QMessageBox.warning(self, "警告", "时间拉伸倍数必须大于0！")
                    return
            except ValueError:
                QMessageBox.warning(self, "警告", "时间拉伸倍数格式错误，请输入数字！")
                return
            
            # 获取实例名
            instance_name = self.instance_name_input.text().strip() or "PID_TEST_1"
            
            # 每秒采样一个数据（与预测模板共用采样逻辑）
            sampled_records = []
            last_sampled_time = -1.0
            
            for record in self.data_records:
                sim_time = record.get('sim_time', 0)
                # 如果当前时间与上次采样时间相差>=1秒，则采样
                if sim_time - last_sampled_time >= 1.0:
                    sampled_records.append(record)
                    last_sampled_time = sim_time
            
            # 如果没有采样到数据，至少采样第一个和最后一个
            if not sampled_records:
                sampled_records = [self.data_records[0]]
                if len(self.data_records) > 1:
                    sampled_records.append(self.data_records[-1])
            
            # 写入CSV文件
            with open(filename, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                
                # 第一行：时间 PV MV SV（使用格式化后的位号名）
                writer.writerow([
                    '时间',
                    self._format_tag_name(instance_name, 'pid.pv'),
                    self._format_tag_name(instance_name, 'pid.mv'),
                    self._format_tag_name(instance_name, 'pid.sv')
                ])
                
                # 第二行开始：数据行，时间格式为 yyyy-MM-dd HH:mm:ss
                base_time = Constants.DEFAULT_BASE_TIME
                
                for record in sampled_records:
                    sim_time = record.get('sim_time', 0)
                    # 计算时间戳：基准时间 + sim_time * time_stretch秒数（应用时间拉伸）
                    stretched_time = sim_time * time_stretch
                    record_time = base_time + timedelta(seconds=stretched_time)
                    
                    # 格式：yyyy-MM-dd HH:mm:ss
                    time_str = record_time.strftime("%Y-%m-%d %H:%M:%S")
                    
                    # 获取数据值（只导出PV、MV、SV）
                    pid_pv = record.get('pid.pv', 0)
                    pid_mv = record.get('pid.mv', 0)
                    pid_sv = record.get('pid.sv', 0)
                    
                    writer.writerow([
                        time_str,
                        self._format_float(pid_pv),
                        self._format_float(pid_mv),
                        self._format_float(pid_sv)
                    ])
            
            # 计算原始时间跨度和拉伸后的时间跨度
            if sampled_records:
                original_duration = sampled_records[-1].get('sim_time', 0) - sampled_records[0].get('sim_time', 0)
                stretched_duration = original_duration * time_stretch
            else:
                original_duration = 0
                stretched_duration = 0
            
            stretch_info = f"，时间拉伸倍数：{time_stretch}" if time_stretch != 1 else ""
            QMessageBox.information(
                self,
                "导出成功",
                f"PID整定模板已成功导出到：\n{filename}\n\n"
                f"共导出 {len(sampled_records)} 条记录（每秒1条）{stretch_info}。\n"
                f"原始时间跨度：{original_duration:.1f}秒，拉伸后时间跨度：{stretched_duration:.1f}秒。"
            )
            
        except FileNotFoundError as e:
            QMessageBox.critical(self, "导出失败", f"文件未找到：\n{str(e)}")
        except PermissionError as e:
            QMessageBox.critical(self, "导出失败", f"没有权限访问文件：\n{str(e)}")
        except OSError as e:
            QMessageBox.critical(self, "导出失败", f"文件操作失败：\n{str(e)}")
        except Exception as e:
            QMessageBox.critical(self, "导出失败", f"导出数据时发生错误：\n{str(e)}")
            logger.exception("Error exporting PID tuning template")
    
    def export_tpt_template(self):
        """
        导出TPT导入位号模板（Excel格式）
        
        格式要求：
        - 1个sheet页，名字是sheet1
        - 系统位号名和描述：完整位号名（实例名.参数名）
        - 底层位号名：1_{完整位号名}（namespace=1）
        - 数据源名称：从界面配置
        - 数据类型：DOUBLE
        - 采集频率：1
        - 缓存数量：100
        - 是否向量位号：TRUE
        - 节点名：根节点
        """
        if not OPENPYXL_AVAILABLE:
            QMessageBox.critical(
                self, 
                "错误", 
                "未安装openpyxl库，无法导出Excel文件！\n\n"
                "请运行以下命令安装：\n"
                "pip install openpyxl"
            )
            return
        
        # 获取数据源名称
        datasource_name = self.tpt_datasource_input.text().strip()
        if not datasource_name:
            QMessageBox.warning(self, "警告", "请输入数据源名称！")
            return
        
        # 获取实例名
        instance_name = self.instance_name_input.text().strip() or "PID_TEST_1"
        
        # 选择保存文件
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        default_filename = f"tpt_tag_template_{timestamp}.xlsx"
        
        filename, _ = QFileDialog.getSaveFileName(
            self,
            "导出TPT导入位号模板",
            default_filename,
            "Excel Files (*.xlsx);;All Files (*)"
        )
        
        if not filename:
            return
        
        # 验证文件路径安全性
        if not os.path.isabs(filename):
            filename = os.path.abspath(filename)
        
        # 检查目录是否存在
        dir_path = os.path.dirname(filename)
        if dir_path and not os.path.exists(dir_path):
            try:
                os.makedirs(dir_path, exist_ok=True)
            except OSError as e:
                QMessageBox.critical(self, "错误", f"无法创建目录: {dir_path}\n{str(e)}")
                return
        
        try:
            # 创建Workbook
            wb = Workbook()
            ws = wb.active
            ws.title = "sheet1"
            
            # 定义所有位号（8个位号）- 使用常量定义
            tag_names = Constants.TAG_DEFINITIONS
            
            # 写入表头
            headers = [
                '系统位号名', '底层位号名', '位号类型', '数据源名称（一次位号）', '单位',
                '数据类型', '取值表达式（二次位号）', '位号值（虚位号）', '采集频率',
                '缓存数量', '是否为向量位号', '位号值高限', '位号值高二限', '位号值高三限',
                '位号值低限', '位号值低二限', '位号值低三限', '描述', '节点名'
            ]
            ws.append(headers)
            
            # 设置表头样式
            header_font = Font(bold=True)
            for cell in ws[1]:
                cell.font = header_font
                cell.alignment = Alignment(horizontal='center', vertical='center')
            
            # 写入数据行
            namespace = 1  # OPCUA命名空间索引
            for tag_key, tag_desc in tag_names:
                # 使用新格式：{实例名}_{param_prefix}.{param_suffix.UPPER}
                full_tag_name = self._format_tag_name(instance_name, tag_key)
                bottom_tag_name = f"{namespace}_{full_tag_name}"  # 底层位号名：1_{完整位号名}
                
                row_data = [
                    full_tag_name,  # 系统位号名
                    bottom_tag_name,  # 底层位号名
                    '一次位号',  # 位号类型
                    datasource_name,  # 数据源名称（一次位号）
                    '',  # 单位
                    'DOUBLE',  # 数据类型
                    '',  # 取值表达式（二次位号）
                    '',  # 位号值（虚位号）
                    1,  # 采集频率
                    100,  # 缓存数量
                    'TRUE',  # 是否为向量位号
                    '',  # 位号值高限
                    '',  # 位号值高二限
                    '',  # 位号值高三限
                    '',  # 位号值低限
                    '',  # 位号值低二限
                    '',  # 位号值低三限
                    full_tag_name,  # 描述（与系统位号名一致）
                    '根节点'  # 节点名
                ]
                ws.append(row_data)
            
            # 调整列宽（可选）
            for column in ws.columns:
                max_length = 0
                column_letter = column[0].column_letter
                for cell in column:
                    try:
                        if len(str(cell.value)) > max_length:
                            max_length = len(str(cell.value))
                    except:
                        pass
                adjusted_width = min(max_length + 2, 50)
                ws.column_dimensions[column_letter].width = adjusted_width
            
            # 保存文件
            wb.save(filename)
            
            QMessageBox.information(
                self,
                "导出成功",
                f"TPT导入位号模板已成功导出到：\n{filename}\n\n"
                f"共导出 {len(tag_names)} 个位号。\n"
                f"数据源名称：{datasource_name}\n"
                f"实例名：{instance_name}"
            )
            
        except PermissionError as e:
            QMessageBox.critical(self, "导出失败", f"没有权限访问文件：\n{str(e)}")
        except OSError as e:
            QMessageBox.critical(self, "导出失败", f"文件操作失败：\n{str(e)}")
        except Exception as e:
            QMessageBox.critical(self, "导出失败", f"导出TPT模板时发生错误：\n{str(e)}")
            logger.exception("Error exporting TPT template")


def main():
    """主函数"""
    app = QApplication(sys.argv)
    
    window = UnifiedToolWindow()
    window.show()
    
    sys.exit(app.exec())


if __name__ == '__main__':
    main()

