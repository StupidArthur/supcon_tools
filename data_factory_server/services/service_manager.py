"""
服务管理器

功能：
- 依次启动 Engine、StorageService、OPCUA Server
- 监控各个模块的运行状态
- 提供诊断信息查询接口
- 使用消息总线的服务注册与发现功能
"""
from __future__ import annotations

import sys
import time
import threading
from pathlib import Path
from typing import Dict, Any, Optional, List
from dataclasses import dataclass

# 添加项目根目录到 Python 路径
project_root = Path(__file__).parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

# 导入程序和函数（触发注册）
from components import programs  # noqa: F401
from components import functions  # noqa: F401
from services.config_server import EngineInstanceConfig

from controller.engine import UnifiedEngine
from controller.parser import DSLParser, ProgramConfig
from controller.realtime_publisher import RealtimeConfig
from services.realtime_runner import RealtimeRunner
import redis
from datacenter.storage_service import StorageService, StorageServiceConfig
from datacenter.opcua_server import OPCUAServer, OPCUAServerConfig
from components.message_bus import MessageBus, BusConfig, ServiceRegistry
from components.utils.logger import get_logger

logger = get_logger()


@dataclass
class ServiceManagerConfig:
    """
    服务管理器配置
    
    Attributes:
        redis_host: Redis 主机地址
        redis_port: Redis 端口
        redis_db: Redis 数据库编号
        redis_password: Redis 密码（可选）
        bus_config: 消息总线配置（如果为 None，则使用默认配置）
        enable_engine: 是否启动 Engine（默认 True）
        enable_storage: 是否启动 StorageService（默认 True）
        enable_opcua: 是否启动 OPCUA Server（默认 True）
        storage_db_path: 存储服务数据库路径
        opcua_server_url: OPCUA Server 地址
        opcua_enable_write: OPCUA Server 是否启用写值功能
        health_check_interval: 健康检查间隔（秒）
    """
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_db: int = 0
    redis_password: Optional[str] = None
    bus_config: Optional[BusConfig] = None
    enable_engine: bool = True
    enable_storage: bool = True
    enable_opcua: bool = True
    # 默认历史数据库路径：项目同级目录下的 storage/storage_service.duckdb（避免提交代码时把数据库文件也提交上去）
    storage_db_path: str = str(project_root.parent / "storage" / "storage_service.duckdb")
    opcua_server_url: str = "opc.tcp://0.0.0.0:18951"
    opcua_enable_write: bool = True
    health_check_interval: float = 5.0  # 默认 5 秒检查一次


class ServiceManager:
    """
    服务管理器
    
    功能：
    1. 依次启动 Engine、StorageService、OPCUA Server
    2. 监控各个模块的运行状态
    3. 提供诊断信息查询接口
    """
    
    def __init__(self, config: ServiceManagerConfig):
        """
        初始化服务管理器
        
        Args:
            config: 服务管理器配置
        """
        self.config = config
        
        # 消息总线（用于服务发现）
        if config.bus_config:
            self.bus_config = config.bus_config
        else:
            self.bus_config = BusConfig(
                redis_host=config.redis_host,
                redis_port=config.redis_port,
                redis_db=config.redis_db,
                redis_password=config.redis_password,
                key_prefix="service_manager"
            )
        self.bus = MessageBus(self.bus_config)
        self.registry = ServiceRegistry(self.bus)
        
        # 组态服务器
        from services.config_server import ConfigServer
        self.config_server = ConfigServer(str(project_root), self.bus.redis)
        
        # 服务实例
        self.engines: Dict[str, UnifiedEngine] = {}
        self.runners: Dict[str, RealtimeRunner] = {}
        self.storage_service: Optional[StorageService] = None
        self.opcua_server: Optional[OPCUAServer] = None
        
        # 运行控制
        self._running = False
        self._health_check_thread: Optional[threading.Thread] = None
        
        logger.info(
            "ServiceManager initialized: redis=%s:%d/%d",
            config.redis_host,
            config.redis_port,
            config.redis_db,
        )
    
    @property
    def engine(self) -> Optional[UnifiedEngine]:
        """获取默认引擎（兼容旧接口）"""
        if not self.engines:
            return None
        # 优先返回 id 为 'default' 的引擎，否则返回第一个
        return self.engines.get("default") or next(iter(self.engines.values()))

    @property
    def engine_runner(self) -> Optional[RealtimeRunner]:
        """获取默认引擎运行器（兼容旧接口）"""
        if not self.runners:
            return None
        return self.runners.get("default") or next(iter(self.runners.values()))

    def start_engine(self, config_path: Optional[str] = None, dsl_content: Optional[str] = None) -> bool:
        """
        启动 Engines (基于 ConfigServer)
        
        Args:
            config_path: (已废弃/兼容) 配置文件路径
            dsl_content: (已废弃/兼容) DSL 内容
        
        Returns:
            是否成功启动至少一个引擎
        """
        if not self.config.enable_engine:
            logger.info("Engine 启动已禁用")
            return False
        
        try:
            # 1. 加载基础设施配置
            # 如果传入了 dsl_content/config_path，这属于旧模式，我们将其视为 "default" 引擎
            if dsl_content or config_path:
                logger.info("检测到旧版配置参数，将在旧兼容模式下启动 Default Engine")
                parser = DSLParser()
                if dsl_content:
                    program_config = parser.parse(dsl_content)
                else:
                    program_config = parser.parse_file(config_path)
                
                self._start_single_engine("default", program_config)
                return True

            # 2. 新模式：使用 ConfigServer 加载
            self.config_server.load_infrastructure()
            self.config_server.load_all_logic()
            self.config_server.publish_config()
            self._reset_realtime_keys()
            
            if not self.config_server.logic_configs:
                logger.warning("ConfigServer 未加载任何逻辑配置，尝试旧版回退逻辑")
                parser = DSLParser()
                program_config = self._load_running_configs(parser)
                if program_config.program:
                     self._start_single_engine("default", program_config)
                     return True
                return False

            # 3. 启动所有加载的 Engines
            for engine_id, program_config in self.config_server.logic_configs.items():
                self._start_single_engine(engine_id, program_config)
            self._cleanup_stale_engine_services(set(self.config_server.logic_configs.keys()))
            
            logger.info(f"成功启动 {len(self.engines)} 个 Engine 实例")
            return len(self.engines) > 0
            
        except Exception as e:
            logger.error(f"Failed to start Engines: {e}", exc_info=True)
            return False

    def reload_infrastructure(self) -> bool:
        """
        热重载基础设施配置 (Manifest)
        """
        try:
            logger.info("开始热重载基础设施...")
            
            # 保存旧 ID
            current_engine_ids = set(self.engines.keys())
            
            # 清理并重新加载
            self.config_server.logic_configs.clear()
            self.config_server.global_registry.clear()
            
            self.config_server.load_infrastructure()
            self.config_server.load_all_logic() 
            self.config_server.publish_config()
            self._reset_realtime_keys()
            
            new_configs = self.config_server.logic_configs
            new_engine_ids = set(new_configs.keys())
            
            # 停止已删除的
            to_stop = current_engine_ids - new_engine_ids
            for eid in to_stop:
                logger.info(f"Reload: 停止已移除的 Engine {eid}")
                self._stop_single_engine(eid)
                
            # 启动新增的
            to_start = new_engine_ids - current_engine_ids
            for eid in to_start:
                logger.info(f"Reload: 启动新增的 Engine {eid}")
                self._start_single_engine(eid, new_configs[eid])
                
            # 检查变更 (主要是 Playback 路径变更)
            common_ids = current_engine_ids & new_engine_ids
            for eid in common_ids:
                new_conf = new_configs[eid]
                if isinstance(new_conf, EngineInstanceConfig):
                    old_engine = self.engines.get(eid)
                    if hasattr(old_engine, 'file_path'):
                        new_full_path = str(project_root / new_conf.source)
                        if old_engine.file_path != new_full_path:
                             logger.info(f"Reload: Engine {eid} 配置变更 (Source)，正在重启...")
                             self._stop_single_engine(eid)
                             self._start_single_engine(eid, new_conf)
                
            self._cleanup_stale_engine_services(new_engine_ids)
            logger.info("基础设施热重载完成")
            return True
        except Exception as e:
            logger.error(f"热重载失败: {e}", exc_info=True)
            return False

    def _stop_single_engine(self, engine_id: str) -> None:
        """停止并移除单个引擎"""
        if engine_id in self.runners:
            logger.info(f"Stopping runner for {engine_id}...")
            self.runners[engine_id].stop()
            del self.runners[engine_id]
        
        if engine_id in self.engines:
            logger.info(f"Removing engine {engine_id}...")
            del self.engines[engine_id]

    def _reset_realtime_keys(self) -> None:
        """清理实时数据键，避免旧命名空间残留污染前端展示。"""
        try:
            self.bus.redis.delete("data_factory:v2:current")
            logger.info("已清理 Redis 键: data_factory:v2:current")
        except Exception as e:
            logger.warning(f"清理实时 Redis 键失败: {e}")

    def _cleanup_stale_engine_services(self, active_engine_ids: set[str]) -> None:
        """注销已不再活动的 engine.* 服务注册，避免诊断页出现旧 default 幽灵节点。"""
        try:
            service_names = self.registry.list_all()
            active_services = {f"engine.{eid}" for eid in active_engine_ids}
            for name in service_names:
                if not name.startswith("engine."):
                    continue
                if name not in active_services:
                    self.registry.unregister(name)
                    logger.info(f"已注销过期服务注册: {name}")
        except Exception as e:
            logger.warning(f"清理过期 engine 服务注册失败: {e}")
            
    def _start_single_engine(self, engine_id: str, program_config: Any) -> None:
        """启动单个引擎实例"""
        logger.info(f"正在启动 Engine: {engine_id} ...")
        
        if engine_id in self.engines:
             logger.warning(f"Engine {engine_id} 已经在运行，跳过启动")
             return

        engine = None
        
        # Simulation
        if isinstance(program_config, ProgramConfig):
            engine = UnifiedEngine.from_program_config(program_config)
        # Playback
        elif isinstance(program_config, EngineInstanceConfig):
            from controller.playback_engine import PlaybackEngine
            full_path = str(project_root / program_config.source)
            engine = PlaybackEngine(
                engine_id=engine_id,
                file_path=full_path,
                time_col=program_config.time_col,
                sheet_name=program_config.sheet_name,
                cycle_time=1.0
            )
        else:
            logger.error(f"Unknown config type for {engine_id}")
            return
        
        realtime_config = RealtimeConfig(
            redis_host=self.config.redis_host,
            redis_port=self.config.redis_port,
            redis_db=self.config.redis_db,
            redis_password=self.config.redis_password,
            bus_config=self.bus_config,
            engine_id=engine_id,
        )
        engine.enable_realtime_data(realtime_config, enable_message_bus=True)
        
        runner = RealtimeRunner(engine)
        runner.start()
        
        self.engines[engine_id] = engine
        self.runners[engine_id] = runner
        logger.info(f"Engine {engine_id} 启动成功")
    
    def _load_running_configs(self, parser: DSLParser) -> ProgramConfig:
        """
        从 running_config 目录加载所有配置文件
        
        Args:
            parser: DSL解析器
        
        Returns:
            合并后的 ProgramConfig
        """
        running_config_dir = project_root / "controller" / "running_config"
        
        if not running_config_dir.exists():
            logger.info("running_config 目录不存在，使用空配置")
            return ProgramConfig(
                clock=parser._parse_clock_config({}),
                program=[],
                record_length=0,
                lag_requirements={}
            )
        
        # 查找所有 yaml 文件
        config_files = sorted(running_config_dir.glob("*.yaml"))
        
        if not config_files:
            logger.info("running_config 目录下没有配置文件，使用空配置")
            return ProgramConfig(
                clock=parser._parse_clock_config({}),
                program=[],
                record_length=0,
                lag_requirements={}
            )
        
        logger.info(f"从 running_config 目录加载 {len(config_files)} 个配置文件")
        
        # 合并所有配置
        merged_program = []
        merged_lag_requirements = {}
        clock_config = None
        
        for config_file in config_files:
            try:
                config = parser.parse_file(str(config_file))
                
                # 从文件名提取 namespace（去掉 .yaml 后缀）
                namespace = config_file.stem  # stem 是文件名不带扩展名
                
                logger.info(f"加载配置文件: {config_file.name}, namespace: {namespace}")
                
                # 第一步：收集该配置文件中所有实例名，构建完整的映射表
                all_instance_names = {item.name for item in config.program if item.type.upper() != "VARIABLE"}
                # 构建映射表：所有实例名 -> namespace.实例名
                mapping: Dict[str, str] = {name: f"{namespace}.{name}" for name in all_instance_names}
                
                # 第二步：应用命名空间并合并 program items
                ns_items = []
                for item in config.program:
                    ns_item = self._apply_namespace_to_item_with_mapping(item, namespace, mapping)
                    ns_items.append(ns_item)
                    # 记录表达式重写结果（用于调试）
                    if item.expression and item.expression != ns_item.expression:
                        logger.info(f"表达式重写 [{namespace}]: {item.name}: {item.expression} -> {ns_item.expression}")
                    elif item.expression:
                        logger.debug(f"表达式未变化 [{namespace}]: {item.name}: {item.expression}")
                merged_program.extend(ns_items)
                
                # 合并 lag_requirements（也需要应用命名空间）
                for var_name, max_lag_steps in config.lag_requirements.items():
                    # 如果变量名是实例属性（包含点号），需要应用命名空间
                    if '.' in var_name:
                        parts = var_name.split('.', 1)
                        instance_name = parts[0]
                        attr_name = parts[1]
                        ns_var_name = f"{namespace}.{instance_name}.{attr_name}"
                    else:
                        # 变量名，应用命名空间
                        ns_var_name = f"{namespace}.{var_name}"
                    merged_lag_requirements[ns_var_name] = max_lag_steps
                
                # 使用第一个配置的 clock（后续可以考虑合并策略）
                if clock_config is None:
                    clock_config = config.clock
            except Exception as e:
                logger.error(f"加载配置文件失败: {config_file.name}, 错误: {e}", exc_info=True)
        
        if clock_config is None:
            clock_config = parser._parse_clock_config({})
        
        return ProgramConfig(
            clock=clock_config,
            program=merged_program,
            record_length=0,  # record_length 不再使用
            lag_requirements=merged_lag_requirements
        )
    
    def _apply_namespace_to_item_with_mapping(self, item, namespace: str, mapping: Dict[str, str]):
        """
        为 ProgramItem 添加命名空间前缀，并重写表达式中的名称。
        
        使用提供的完整映射表（包含所有实例名的映射）。
        
        Args:
            item: ProgramItem 对象
            namespace: 命名空间
            mapping: 完整的名称映射表（所有实例名 -> namespace.实例名）
        
        Returns:
            应用命名空间后的 ProgramItem
        """
        from copy import deepcopy
        
        if not namespace:
            return deepcopy(item)
        
        new_item = deepcopy(item)
        
        # 应用命名空间到 item 名称
        if item.name in mapping:
            new_item.name = mapping[item.name]
        else:
            new_item.name = f"{namespace}.{item.name}"
        
        # 重写表达式中的名称
        if new_item.expression:
            original_expr = new_item.expression
            new_item.expression = self._rewrite_expression_with_mapping(
                new_item.expression, mapping
            )
            # 记录表达式重写结果（用于调试）
            if original_expr != new_item.expression:
                logger.debug(f"表达式重写: {item.name}: {original_expr} -> {new_item.expression}")
        
        return new_item
    
    def _rewrite_expression_with_mapping(self, expression: str, mapping: Dict[str, str]) -> str:
        """
        使用 AST 将表达式中的名称按映射表替换。
        
        与 UnifiedEngine._rewrite_expression_with_mapping 相同的逻辑。
        """
        import ast
        
        try:
            tree = ast.parse(expression, mode="exec")
        except SyntaxError:
            return expression

        class _Rewriter(ast.NodeTransformer):
            def __init__(self, mapping: Dict[str, str]) -> None:
                self.mapping = mapping

            def visit_Name(self, node: ast.Name) -> ast.AST:
                if node.id in self.mapping:
                    return self._build_attr_chain(self.mapping[node.id], node)
                return node

            def visit_Attribute(self, node: ast.Attribute) -> ast.AST:
                # 先递归访问子节点（处理嵌套属性访问）
                # 注意：generic_visit 会递归访问 node.value，但不会自动更新 node.value
                # 所以我们需要手动检查并更新
                self.generic_visit(node)
                # 然后处理 instance.attr 的情况：如果 instance 在映射中，替换它
                if isinstance(node.value, ast.Name) and node.value.id in self.mapping:
                    # 替换 node.value 为命名空间后的属性链
                    node.value = self._build_attr_chain(self.mapping[node.value.id], node.value)
                return node

            @staticmethod
            def _build_attr_chain(name: str, ref_node: ast.AST) -> ast.AST:
                """
                将 'ns.item' 转换为 Attribute 链，保持位置信息。
                与 UnifiedEngine._rewrite_expression_with_mapping 中的实现保持一致。
                """
                parts = name.split(".")
                if not parts:
                    return ref_node
                base = ast.Name(id=parts[0], ctx=ast.Load())
                ast.copy_location(base, ref_node)
                current: ast.AST = base
                for attr in parts[1:]:
                    attr_node = ast.Attribute(value=current, attr=attr, ctx=ast.Load())
                    ast.copy_location(attr_node, ref_node)
                    current = attr_node
                return current

        try:
            rewriter = _Rewriter(mapping)
            new_tree = rewriter.visit(tree)
            ast.fix_missing_locations(new_tree)
            if hasattr(ast, "unparse"):
                return ast.unparse(new_tree)
            else:
                # Python < 3.9 没有 unparse，使用简单替换作为fallback
                # 注意：这个fallback可能不够准确，但对于简单情况可以工作
                result = expression
                for old_name, new_name in mapping.items():
                    import re
                    # 使用单词边界，避免部分匹配
                    pattern = r'\b' + re.escape(old_name) + r'\b'
                    result = re.sub(pattern, new_name, result)
                return result
        except Exception:
            return expression
    
    def start_storage_service(self) -> bool:
        """
        启动 StorageService
        
        Returns:
            是否成功启动
        """
        if not self.config.enable_storage:
            logger.info("StorageService 启动已禁用")
            return False
        
        try:
            config = StorageServiceConfig(
                redis_host=self.config.redis_host,
                redis_port=self.config.redis_port,
                redis_db=self.config.redis_db,
                redis_password=self.config.redis_password,
                db_path=self.config.storage_db_path,
                bus_config=self.bus_config,
                use_message_bus=True,
            )
            
            self.storage_service = StorageService(config)
            self.storage_service.start()
            
            logger.info("StorageService 启动成功")
            return True
        except Exception as e:
            logger.error(f"Failed to start StorageService: {e}", exc_info=True)
            return False
    
    def start_opcua_server(self) -> bool:
        """
        启动 OPCUA Server
        
        Returns:
            是否成功启动
        """
        if not self.config.enable_opcua:
            logger.info("OPCUA Server 启动已禁用")
            return False
        
        try:
            config = OPCUAServerConfig(
                server_url=self.config.opcua_server_url,
                redis_host=self.config.redis_host,
                redis_port=self.config.redis_port,
                redis_db=self.config.redis_db,
                redis_password=self.config.redis_password,
                bus_config=self.bus_config,
                enable_write=self.config.opcua_enable_write,
            )
            
            self.opcua_server = OPCUAServer(config)
            self.opcua_server.start()
            
            logger.info("OPCUA Server 启动成功")
            return True
        except Exception as e:
            logger.error(f"Failed to start OPCUA Server: {e}", exc_info=True)
            return False
    
    def start_all(
        self,
        config_path: Optional[str] = None,
        dsl_content: Optional[str] = None
    ) -> Dict[str, bool]:
        """
        依次启动所有服务
        
        Args:
            config_path: Engine 配置文件路径
            dsl_content: Engine DSL 内容（字符串）
        
        Returns:
            启动结果字典 {"engine": bool, "storage": bool, "opcua": bool}
        """
        results = {}
        
        # 1. 启动 Engine
        logger.info("=" * 60)
        logger.info("启动 Engine...")
        logger.info("=" * 60)
        results["engine"] = self.start_engine(config_path, dsl_content)
        if results["engine"]:
            time.sleep(1)  # 等待服务注册
        
        # 2. 启动 StorageService
        logger.info("=" * 60)
        logger.info("启动 StorageService...")
        logger.info("=" * 60)
        results["storage"] = self.start_storage_service()
        if results["storage"]:
            time.sleep(1)  # 等待服务注册
        
        # 3. 启动 OPCUA Server
        logger.info("=" * 60)
        logger.info("启动 OPCUA Server...")
        logger.info("=" * 60)
        results["opcua"] = self.start_opcua_server()
        if results["opcua"]:
            time.sleep(1)  # 等待服务注册
        
        # 启动健康检查线程
        self._running = True
        if self.config.health_check_interval > 0:
            self._health_check_thread = threading.Thread(
                target=self._health_check_loop,
                daemon=True
            )
            self._health_check_thread.start()
            logger.info("健康检查线程已启动")
        
        logger.info("=" * 60)
        logger.info("所有服务启动完成")
        logger.info("=" * 60)
        
        return results
    
    def _health_check_loop(self) -> None:
        """健康检查循环"""
        while self._running:
            try:
                time.sleep(self.config.health_check_interval)
                
                # 检查各个服务的健康状态
                services_status = self.get_services_status()
                
                # 输出状态信息
                for service_name, status in services_status.items():
                    if status.get("registered"):
                        health = status.get("health", "unknown")
                        logger.debug(f"Service {service_name}: {health}")
                    else:
                        logger.warning(f"Service {service_name}: not registered")

                # 自愈：storage/opcua 非运行态时自动尝试重启
                if self.config.enable_storage and not self._is_storage_running():
                    logger.warning("检测到 StorageService 未运行，尝试自动重启...")
                    self.start_storage_service()
                if self.config.enable_opcua and not self._is_opcua_running():
                    logger.warning("检测到 OPCUA Server 未运行，尝试自动重启...")
                    self.start_opcua_server()
                
            except Exception as e:
                logger.error(f"Error in health check loop: {e}", exc_info=True)
                time.sleep(self.config.health_check_interval)

    def _is_storage_running(self) -> bool:
        """StorageService 当前是否运行。"""
        if self.storage_service is None:
            return False
        th = getattr(self.storage_service, "_thread", None)
        return bool(th is not None and th.is_alive() and getattr(self.storage_service, "_running", False))

    def _is_opcua_running(self) -> bool:
        """OPCUA Server 当前是否运行。"""
        if self.opcua_server is None:
            return False
        th = getattr(self.opcua_server, "_server_thread", None)
        server_obj = getattr(self.opcua_server, "server", None)
        return bool((th is not None and th.is_alive()) or (server_obj is not None))
    
    def get_services_status(self) -> Dict[str, Dict[str, Any]]:
        """
        获取所有服务的状态信息
        
        Returns:
            服务状态字典
        """
        # 动态获取所有已注册的服务
        all_registered = self.registry.list_all()
        # 确保基础服务名也在列表中（即使尚未注册也能显示状态）
        base_services = ["storage_service", "opcua_server"]
        services = sorted(list(set(all_registered) | set(base_services)))
        
        status = {}
        logger.debug(f"正在获取状态的服务列表: {services}")
        
        for service_name in services:
            try:
                service_info = self.registry.get_service_info(service_name)
                if service_info:
                    status[service_name] = {
                        "registered": True,
                        "health": "healthy" if self.registry.check_health(service_name) else "unhealthy",
                        "metadata": service_info.get("metadata", {}),
                        "last_heartbeat": service_info.get("last_heartbeat"),
                    }
                    logger.debug(f"服务 {service_name} 状态: registered=True, health={status[service_name]['health']}")
                else:
                    status[service_name] = {
                        "registered": False,
                        "health": "unknown",
                    }
                    logger.debug(f"服务 {service_name} 未注册")
            except Exception as e:
                logger.error(f"Failed to get status for {service_name}: {e}", exc_info=True)
                status[service_name] = {
                    "registered": False,
                    "health": "error",
                    "error": str(e),
                }
        
        return status
    
    def get_diagnostic_info(self) -> Dict[str, Any]:
        """
        获取诊断信息
        
        Returns:
            诊断信息字典
        """
        # 获取服务状态
        services_status = self.get_services_status()
        all_services = self.registry.list_all()
        
        # 添加详细的OPCUA Server状态日志
        if self.opcua_server:
            logger.debug(
                f"OPCUA Server 详细状态: "
                f"_running={self.opcua_server._running}, "
                f"_server_thread={self.opcua_server._server_thread}, "
                f"thread_alive={self.opcua_server._server_thread.is_alive() if self.opcua_server._server_thread else False}, "
                f"server={self.opcua_server.server is not None}"
            )
        
        logger.debug(f"诊断信息 - 所有服务列表: {all_services}")
        logger.debug(f"诊断信息 - 服务状态: {services_status}")
        
        diagnostic = {
            "services_status": services_status,
            "all_services": all_services,
            "engine_running": self.engine is not None and (
                self.engine_runner._thread.is_alive() if self.engine_runner and self.engine_runner._thread else False
            ),
            "storage_running": self._is_storage_running(),
            "opcua_running": self._is_opcua_running(),
        }
        
        # 添加所有活跃引擎的运行状态
        for eid, runner in self.runners.items():
            diagnostic[f"engine.{eid}_running"] = runner._thread.is_alive() if runner._thread else False
        
        # 添加 Engine 统计信息 (多引擎支持)
        if self.engines:
            diagnostic["engines_statistics"] = {}
            for eid, engine in self.engines.items():
                if hasattr(engine, 'get_statistics'):
                    try:
                        diagnostic["engines_statistics"][eid] = engine.get_statistics()
                    except Exception:
                        pass
        elif self.engine and hasattr(self.engine, 'get_statistics'):
            try:
                diagnostic["engine_statistics"] = self.engine.get_statistics()
            except Exception:
                pass
        
        # 添加 StorageService 统计信息（如果有）
        if self.storage_service and hasattr(self.storage_service, 'get_statistics'):
            try:
                diagnostic["storage_statistics"] = self.storage_service.get_statistics()
            except Exception:
                pass
        
        return diagnostic
    
    def stop_all(self) -> None:
        """停止所有服务"""
        logger.info("=" * 60)
        logger.info("停止所有服务...")
        logger.info("=" * 60)
        
        self._running = False
        
        # 停止 OPCUA Server
        if self.opcua_server:
            try:
                self.opcua_server.stop()
                self.opcua_server.close()
                logger.info("OPCUA Server 已停止")
            except Exception as e:
                logger.error(f"Failed to stop OPCUA Server: {e}", exc_info=True)
        
        # 停止 StorageService
        if self.storage_service:
            try:
                self.storage_service.stop()
                self.storage_service.close()
                logger.info("StorageService 已停止")
            except Exception as e:
                logger.error(f"Failed to stop StorageService: {e}", exc_info=True)
        
        # 停止 Engines
        for eid, runner in list(self.runners.items()):
            try:
                runner.stop()
                logger.info(f"Engine {eid} 已停止")
            except Exception as e:
                logger.error(f"Failed to stop Engine {eid}: {e}", exc_info=True)
        self.runners.clear()
        
        for eid, engine in list(self.engines.items()):
            try:
                if engine._realtime_publisher:
                    engine._realtime_publisher.close()
            except Exception as e:
                logger.error(f"Failed to close Engine {eid} publisher: {e}", exc_info=True)
        self.engines.clear()
        
        # 等待健康检查线程结束
        if self._health_check_thread:
            self._health_check_thread.join(timeout=2)
        
        logger.info("所有服务已停止")
    
    def close(self) -> None:
        """关闭服务管理器"""
        self.stop_all()
        
        try:
            self.bus.close()
        except Exception:
            pass
        
        logger.info("ServiceManager 已关闭")


def run_service_manager(
    config_path: Optional[str] = None,
    dsl_content: Optional[str] = None,
    redis_host: str = "localhost",
    redis_port: int = 6379,
    redis_db: int = 0,
    redis_password: Optional[str] = None,
    enable_engine: bool = True,
    enable_storage: bool = True,
    enable_opcua: bool = True,
    storage_db_path: str = str(project_root.parent / "storage" / "storage_service.duckdb"),
    opcua_server_url: str = "opc.tcp://0.0.0.0:18951",
    opcua_enable_write: bool = True,
    health_check_interval: float = 5.0,
) -> None:
    """
    运行服务管理器
    
    Args:
        config_path: Engine 配置文件路径
        dsl_content: Engine DSL 内容（字符串）
        redis_host: Redis 主机地址
        redis_port: Redis 端口
        redis_db: Redis 数据库编号
        redis_password: Redis 密码
        enable_engine: 是否启动 Engine
        enable_storage: 是否启动 StorageService
        enable_opcua: 是否启动 OPCUA Server
        storage_db_path: 存储服务数据库路径
        opcua_server_url: OPCUA Server 地址
        opcua_enable_write: OPCUA Server 是否启用写值功能
        health_check_interval: 健康检查间隔（秒）
    """
    config = ServiceManagerConfig(
        redis_host=redis_host,
        redis_port=redis_port,
        redis_db=redis_db,
        redis_password=redis_password,
        enable_engine=enable_engine,
        enable_storage=enable_storage,
        enable_opcua=enable_opcua,
        storage_db_path=storage_db_path,
        opcua_server_url=opcua_server_url,
        opcua_enable_write=opcua_enable_write,
        health_check_interval=health_check_interval,
    )
    
    manager = ServiceManager(config)
    
    # 注册信号处理（优雅关闭）
    import signal
    def signal_handler(sig, frame):
        logger.info("Received signal, shutting down...")
        manager.close()
        sys.exit(0)
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    try:
        # 启动所有服务
        results = manager.start_all(config_path, dsl_content)
        
        # 输出启动结果
        logger.info("=" * 60)
        logger.info("服务启动结果:")
        logger.info(f"  Engine: {'✓' if results.get('engine') else '✗'}")
        logger.info(f"  StorageService: {'✓' if results.get('storage') else '✗'}")
        logger.info(f"  OPCUA Server: {'✓' if results.get('opcua') else '✗'}")
        logger.info("=" * 60)
        
        # 定期输出诊断信息
        import time
        while True:
            time.sleep(30)  # 每 30 秒输出一次诊断信息
            diagnostic = manager.get_diagnostic_info()
            logger.info("=" * 60)
            logger.info("服务诊断信息:")
            for service_name, status in diagnostic["services_status"].items():
                registered = "✓" if status.get("registered") else "✗"
                health = status.get("health", "unknown")
                logger.info(f"  {service_name}: {registered} (health: {health})")
            logger.info("=" * 60)
        
    except KeyboardInterrupt:
        logger.info("Received keyboard interrupt, shutting down...")
    except Exception as e:
        logger.error(f"Error: {e}", exc_info=True)
    finally:
        manager.close()


if __name__ == "__main__":
    run_service_manager()
