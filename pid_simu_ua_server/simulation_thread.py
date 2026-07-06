"""
模拟运行线程模块
"""
from typing import Dict, Any, List
from PyQt6.QtCore import QThread, pyqtSignal

# 添加项目根目录到Python路径
import sys
from pathlib import Path
SCRIPT_DIR = Path(__file__).parent.parent.parent.absolute()
sys.path.insert(0, str(SCRIPT_DIR))

from plc.clock import Clock
from module.cylindrical_tank import CylindricalTank
from module.valve import Valve
from algorithm.pid import PID
from utils.logger import get_logger
from .constants import Constants

logger = get_logger()


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
                # 说明：
                # - pb 与 kp 数值保持一致
                # - swpn 始终为 1
                # - svsch / svh 等于水箱高度（tank_params.height）
                # - svscl / mvscl / svl / mvl 为 0
                # - mvsch / mvh 为 100
                # - mode 固定为 20，cas 固定为 0
                tank_height = float(self.tank_params.get('height', 2.0))
                record = {
                    'sim_time': clock.current_time,
                    'pid.sv': pid.input['sv'],
                    'pid.pv': pid.input['pv'],
                    'pid.mv': pid.output['mv'],
                    'pid.kp': pid.config['kp'],
                    'pid.pb': pid.config['kp'],  # PB值和KP保持一致
                    'pid.td': pid.config['td'],
                    'pid.ti': pid.config['ti'],
                    'pid.mode': 20,
                    'pid.cas': 0,
                    'pid.swpn': 1,
                    'pid.svsch': tank_height,
                    'pid.svh': tank_height,
                    'pid.svscl': 0,
                    'pid.mvscl': 0,
                    'pid.svl': 0,
                    'pid.mvl': 0,
                    'pid.mvsch': 100,
                    'pid.mvh': 100,
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


