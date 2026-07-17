"""
OPCUA Server 诊断提供者

收集 OPCUA Server 的诊断信息
"""
from typing import Dict, Any, List
import time
from datetime import datetime

from components.diagnostics.base import DiagnosticProvider, DiagnosticItem
from datacenter.opcua_server import OPCUAServer


class OPCUADiagnosticProvider(DiagnosticProvider):
    """OPCUA Server 诊断提供者"""
    
    def __init__(self, opcua_server: OPCUAServer, redis_client):
        """
        初始化 OPCUA Server 诊断提供者
        
        Args:
            opcua_server: OPCUAServer 实例
            redis_client: Redis 客户端实例
        """
        super().__init__("opcua_server", redis_client)
        self.opcua_server = opcua_server
        self._update_count = 0  # 更新次数计数器
        self._last_update_time: float = 0.0  # 最后更新时间戳
    
    def get_diagnostic_schema(self) -> Dict[str, Any]:
        """
        返回诊断结构定义
        
        Returns:
            诊断结构字典
        """
        return {
            "items": [
                {"name": "node_count", "unit": "", "description": "节点数量", "data_type": "int"},
                {"name": "server_url", "unit": "", "description": "服务器地址", "data_type": "string"},
                {"name": "write_enabled", "unit": "", "description": "写值功能启用", "data_type": "bool"},
                {"name": "update_cycle", "unit": "s", "description": "更新周期", "data_type": "float"},
                {"name": "update_count", "unit": "", "description": "更新次数", "data_type": "int"},
                {"name": "server_running", "unit": "", "description": "服务器运行状态", "data_type": "bool"},
                {"name": "last_update_time", "unit": "", "description": "最后更新时间", "data_type": "string"},
            ],
            "update_interval": 1.0,  # 每1秒更新一次
        }
    
    def collect_diagnostics(self) -> List[DiagnosticItem]:
        """
        收集诊断数据
        
        Returns:
            诊断项列表
        """
        items = []
        
        try:
            # 节点数量
            node_count = len(self.opcua_server.node_map) if hasattr(self.opcua_server, 'node_map') else 0
            items.append(DiagnosticItem(
                name="node_count",
                value=node_count,
                unit="",
                description="节点数量",
                data_type="int"
            ))
            
            # 服务器地址
            server_url = self.opcua_server.config.server_url if hasattr(self.opcua_server, 'config') else ""
            items.append(DiagnosticItem(
                name="server_url",
                value=server_url,
                unit="",
                description="服务器地址",
                data_type="string"
            ))
            
            # 写值功能启用
            write_enabled = (
                self.opcua_server.config.enable_write and 
                hasattr(self.opcua_server, '_client') and 
                self.opcua_server._client is not None
            ) if hasattr(self.opcua_server, 'config') else False
            items.append(DiagnosticItem(
                name="write_enabled",
                value=write_enabled,
                unit="",
                description="写值功能启用",
                data_type="bool"
            ))
            
            # 更新周期
            update_cycle = self.opcua_server.config.update_cycle if hasattr(self.opcua_server, 'config') else 0.0
            items.append(DiagnosticItem(
                name="update_cycle",
                value=update_cycle,
                unit="s",
                description="更新周期",
                data_type="float"
            ))
            
            # 更新次数（使用内部计数器）
            items.append(DiagnosticItem(
                name="update_count",
                value=self._update_count,
                unit="",
                description="更新次数",
                data_type="int"
            ))
            
            # 服务器运行状态
            server_running = (
                hasattr(self.opcua_server, 'server') and 
                self.opcua_server.server is not None and
                hasattr(self.opcua_server, '_server_thread') and
                self.opcua_server._server_thread is not None and
                self.opcua_server._server_thread.is_alive()
            )
            items.append(DiagnosticItem(
                name="server_running",
                value=server_running,
                unit="",
                description="服务器运行状态",
                data_type="bool"
            ))
            
            # 最后更新时间
            if self._last_update_time > 0:
                last_update_time_str = datetime.fromtimestamp(self._last_update_time).strftime("%Y-%m-%d %H:%M:%S")
            else:
                last_update_time_str = "N/A"
            items.append(DiagnosticItem(
                name="last_update_time",
                value=last_update_time_str,
                unit="",
                description="最后更新时间",
                data_type="string"
            ))
            
        except Exception as e:
            # 如果收集过程中出错，至少返回一个错误项
            items.append(DiagnosticItem(
                name="error",
                value=str(e),
                unit="",
                description="诊断收集错误",
                data_type="string"
            ))
        
        return items
    
    def increment_update_count(self) -> None:
        """增加更新次数计数并更新最后更新时间"""
        self._update_count += 1
        self._last_update_time = time.time()

