"""
主窗口模块
包含UnifiedToolWindow类，负责UI创建和用户交互
"""
import sys
import socket
from pathlib import Path
from typing import Dict, Any, List, Optional

# 添加项目根目录到Python路径
SCRIPT_DIR = Path(__file__).parent.parent.parent.absolute()
sys.path.insert(0, str(SCRIPT_DIR))

from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QLineEdit, QPushButton, QGroupBox,
    QMessageBox, QProgressBar, QFrame, QFileDialog
)
from PyQt6.QtCore import Qt
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

# 导入项目模块
from utils.logger import get_logger

# 导入本地模块
from .constants import Constants
from .simulation_thread import SimulationThread
from .opcua_server_thread import OPCUAServerThread
from .param_handler import ParamHandler
from .chart_manager import ChartManager
from .template_manager import TemplateManager
from .export_handler import ExportHandler

# 初始化日志
logger = get_logger()


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
        self.ax1, self.ax2 = ChartManager.init_chart(self.figure)
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
            full_tag_name = ParamHandler.format_tag_name(instance_name, tag_key)
            tag_desc = tag_descriptions.get(tag_key, tag_key)
            tag_label.setText(f"{full_tag_name}\n({tag_desc})")
    
    def start_simulation(self):
        """开始模拟"""
        try:
            # 获取参数
            tank_params = ParamHandler.get_tank_params(
                self.tank_height, self.tank_radius, self.tank_inlet_area,
                self.tank_inlet_velocity, self.tank_outlet_area, self.tank_initial_level
            )
            valve_params = ParamHandler.get_valve_params(
                self.valve_min_opening, self.valve_max_opening, self.valve_full_travel_time
            )
            pid_params = ParamHandler.get_pid_params(
                self.pid_kp, self.pid_ti, self.pid_td, self.pid_sv,
                self.pid_pv, self.pid_mv, self.pid_h, self.pid_l
            )
            duration = float(self.duration_input.text() or "900.0")
            sv_values = ParamHandler.get_sv_values(self.pid_sv, self)
            
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
        ChartManager.update_chart(self.ax1, self.ax2, self.canvas, self.data_records)
    
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
        """导出模板：保存所有参数配置到JSON文件"""
        TemplateManager.export_template(
            self,
            self.tank_height, self.tank_radius, self.tank_inlet_area, self.tank_inlet_velocity,
            self.tank_outlet_area, self.tank_initial_level,
            self.valve_min_opening, self.valve_max_opening, self.valve_full_travel_time,
            self.pid_kp, self.pid_ti, self.pid_td, self.pid_sv, self.pid_pv, self.pid_mv,
            self.pid_h, self.pid_l, self.duration_input
        )
    
    def import_template(self):
        """导入模板：从JSON文件加载所有参数配置"""
        TemplateManager.import_template(
            self,
            self.tank_height, self.tank_radius, self.tank_inlet_area, self.tank_inlet_velocity,
            self.tank_outlet_area, self.tank_initial_level,
            self.valve_min_opening, self.valve_max_opening, self.valve_full_travel_time,
            self.pid_kp, self.pid_ti, self.pid_td, self.pid_sv, self.pid_pv, self.pid_mv,
            self.pid_h, self.pid_l, self.duration_input
        )
    
    def export_data_to_csv(self):
        """导出数据到CSV文件（预测模板）"""
        ExportHandler.export_prediction_template(
            self, self.data_records, self.time_stretch_input, self.instance_name_input
        )
    
    def export_pid_tuning_template(self):
        """导出PID整定模板（CSV格式）"""
        ExportHandler.export_pid_tuning_template(
            self, self.data_records, self.time_stretch_input, self.instance_name_input
        )
    
    def export_tpt_template(self):
        """导出TPT导入位号模板（Excel格式）"""
        ExportHandler.export_tpt_template(
            self, self.instance_name_input, self.tpt_datasource_input
        )

