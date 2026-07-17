"""
StorageService 诊断提供者

收集 StorageService 的诊断信息
"""
from typing import Dict, Any, List
from pathlib import Path
from datetime import datetime

from components.diagnostics.base import DiagnosticProvider, DiagnosticItem
from datacenter.storage_service import StorageService


class StorageDiagnosticProvider(DiagnosticProvider):
    """StorageService 诊断提供者"""
    
    def __init__(self, storage_service: StorageService, redis_client):
        """
        初始化 StorageService 诊断提供者
        
        Args:
            storage_service: StorageService 实例
            redis_client: Redis 客户端实例
        """
        super().__init__("storage_service", redis_client)
        self.storage_service = storage_service
    
    def get_diagnostic_schema(self) -> Dict[str, Any]:
        """
        返回诊断结构定义
        
        Returns:
            诊断结构字典
        """
        return {
            "items": [
                {"name": "buffer_size", "unit": "", "description": "缓冲区大小", "data_type": "int"},
                {"name": "db_size", "unit": "MB", "description": "数据库大小", "data_type": "float"},
                {"name": "cycle_time", "unit": "s", "description": "Clock周期时间", "data_type": "float"},
                {"name": "sample_interval", "unit": "s", "description": "采样间隔", "data_type": "float"},
                {"name": "clock_status", "unit": "", "description": "时钟状态", "data_type": "string"},
                {"name": "cycle_time", "unit": "s", "description": "执行周期时间", "data_type": "float"},
                {"name": "sample_interval", "unit": "s", "description": "采样间隔", "data_type": "float"},
                {"name": "last_write_time", "unit": "", "description": "最后写入时间", "data_type": "string"},
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
            # 缓冲区大小
            buffer_size = len(self.storage_service._buffer) if hasattr(self.storage_service, '_buffer') else 0
            items.append(DiagnosticItem(
                name="buffer_size",
                value=buffer_size,
                unit="",
                description="缓冲区大小",
                data_type="int"
            ))
            
            # 数据库大小
            try:
                if hasattr(self.storage_service, 'config') and hasattr(self.storage_service.config, 'db_path'):
                    db_path = Path(self.storage_service.config.db_path)
                    if db_path.exists():
                        db_size_mb = db_path.stat().st_size / (1024 * 1024)
                        items.append(DiagnosticItem(
                            name="db_size",
                            value=round(db_size_mb, 2),
                            unit="MB",
                            description="数据库大小",
                            data_type="float"
                        ))
                    else:
                        items.append(DiagnosticItem(
                            name="db_size",
                            value=0.0,
                            unit="MB",
                            description="数据库大小（文件不存在）",
                            data_type="float"
                        ))
                else:
                    items.append(DiagnosticItem(
                        name="db_size",
                        value=0.0,
                        unit="MB",
                        description="数据库大小（配置不可用）",
                        data_type="float"
                    ))
            except Exception as e:
                items.append(DiagnosticItem(
                    name="db_size",
                    value=-1.0,
                    unit="MB",
                    description=f"数据库大小（查询失败: {str(e)}）",
                    data_type="float"
                ))
            
            # 时钟状态
            clock_status = "waiting" if self.storage_service._clock is None else "running"
            items.append(DiagnosticItem(
                name="clock_status",
                value=clock_status,
                unit="",
                description="时钟状态",
                data_type="string"
            ))
            
            # 执行周期时间
            if self.storage_service._clock is not None and hasattr(self.storage_service._clock, 'config'):
                cycle_time = self.storage_service._clock.config.cycle_time
                items.append(DiagnosticItem(
                    name="cycle_time",
                    value=cycle_time,
                    unit="s",
                    description="执行周期时间",
                    data_type="float"
                ))
            else:
                items.append(DiagnosticItem(
                    name="cycle_time",
                    value=0.0,
                    unit="s",
                    description="执行周期时间（时钟未初始化）",
                    data_type="float"
                ))
            
            # 采样间隔
            if self.storage_service._clock is not None and hasattr(self.storage_service._clock, 'config'):
                sample_interval = self.storage_service._clock.config.sample_interval
                items.append(DiagnosticItem(
                    name="sample_interval",
                    value=sample_interval if sample_interval is not None else 0.0,
                    unit="s",
                    description="采样间隔",
                    data_type="float"
                ))
            else:
                items.append(DiagnosticItem(
                    name="sample_interval",
                    value=0.0,
                    unit="s",
                    description="采样间隔（时钟未初始化）",
                    data_type="float"
                ))
            
            # 最后写入时间
            last_write_time_str = "N/A"
            if hasattr(self.storage_service, "_last_write_time") and self.storage_service._last_write_time > 0:
                try:
                    last_write_time_str = datetime.fromtimestamp(
                        self.storage_service._last_write_time
                    ).strftime("%Y-%m-%d %H:%M:%S")
                except Exception:
                    # 如果格式化失败，回退为原始时间戳字符串
                    last_write_time_str = str(self.storage_service._last_write_time)
            
            items.append(DiagnosticItem(
                name="last_write_time",
                value=last_write_time_str,
                unit="",
                description="最后写入时间",
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

