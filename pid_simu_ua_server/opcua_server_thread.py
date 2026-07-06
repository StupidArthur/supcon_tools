"""
OPCUA Server运行线程模块
"""
import ast
import asyncio
from typing import Dict, Any, List
from PyQt6.QtCore import QThread, pyqtSignal

# 添加项目根目录到Python路径
import sys
from pathlib import Path
SCRIPT_DIR = Path(__file__).parent.parent.parent.absolute()
sys.path.insert(0, str(SCRIPT_DIR))

from asyncua import Server, ua
from utils.logger import get_logger
from .constants import Constants

logger = get_logger()


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


