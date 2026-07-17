"""
组态服务器核心模块。

职责：
1. 加载并分离基础设施配置（engines_manifest.yaml）与业务逻辑配置（DSL）。
2. 执行全系统位号唯一性检查。
3. 构建全局注册表（Global Registry）。
4. 向 Redis 发布配置更新事件，驱动下游服务重载。
"""

from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Set
import yaml
from pathlib import Path
import json
import ast
from copy import deepcopy

# 尝试导入依赖，处理环境不完整的情况
try:
    from controller.parser import DSLParser
except ImportError:
    DSLParser = None

from components.utils.logger import get_logger

logger = get_logger()

@dataclass
class EngineInstanceConfig:
    """引擎实例配置"""
    id: str
    type: str = "simulation"  # 'simulation' | 'playback'
    source: str = "" # DSL 文件路径或 Excel 文件路径
    # Playback 特有配置
    time_col: Optional[str] = None
    sheet_name: str = "Sheet1"

@dataclass
class StorageConfig:
    """存储服务全局配置"""
    sample_interval: float = 1.0
    # 未来可扩展黑名单/白名单

@dataclass
class OpcuaConfig:
    """OPCUA 服务全局配置"""
    publish_interval: float = 0.5

@dataclass
class InfrastructureConfig:
    """基础设施总配置"""
    instances: List[EngineInstanceConfig] = field(default_factory=list)
    storage: StorageConfig = field(default_factory=StorageConfig)
    opcua: OpcuaConfig = field(default_factory=OpcuaConfig)

class ConfigServer:
    """
    组态服务器
    
    负责全系统配置的加载、校验和分发。
    """
    
    REGISTRY_KEY = "data_factory:registry:tags" # Hash: tag -> engine_id (meta json)
    CONFIG_EVENT = "config_published"           # PubSub channel

    def __init__(self, base_dir: str, redis_client=None):
        self.base_dir = Path(base_dir)
        self.redis_client = redis_client
        self.infra_config: Optional[InfrastructureConfig] = None
        
        # 运行时状态
        self.logic_configs: Dict[str, Any] = {} # engine_id -> Parsed Config Object
        self.global_registry: Dict[str, Dict[str, Any]] = {} # tag -> metadata

    def load_infrastructure(self, manifest_file: str = "engines_manifest.yaml") -> None:
        """加载基础设施配置文件"""
        manifest_path = self.base_dir / manifest_file
        if not manifest_path.exists():
            logger.warning(f"Manifest file not found: {manifest_path}, using default empty config")
            self.infra_config = InfrastructureConfig()
            return

        try:
            with open(manifest_path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            
            # 解析 instances
            instances = []
            for item in data.get("instances", []):
                instances.append(EngineInstanceConfig(
                    id=item["id"],
                    type=item.get("type", "simulation"),
                    source=item.get("source", ""),
                    time_col=item.get("time_col"),
                    sheet_name=item.get("sheet_name", "Sheet1")
                ))
            
            # 解析 storage
            storage_data = data.get("storage", {})
            storage_conf = StorageConfig(
                sample_interval=storage_data.get("sample_interval", 1.0)
            )
            
            # 解析 opcua
            opcua_data = data.get("opcua", {})
            opcua_conf = OpcuaConfig(
                publish_interval=opcua_data.get("publish_interval", 0.5)
            )
            
            self.infra_config = InfrastructureConfig(
                instances=instances,
                storage=storage_conf,
                opcua=opcua_conf
            )
            logger.info(f"Loaded infrastructure config with {len(instances)} instances")
            
        except Exception as e:
            logger.error(f"Failed to load manifest {manifest_path}: {e}")
            raise

    def load_all_logic(self) -> None:
        """根据 Infrastructure Config 加载所有逻辑配置并进行校验"""
        if not self.infra_config:
            raise RuntimeError("Infrastructure config not loaded")
        
        self.global_registry.clear()
        self.logic_configs.clear()
        
        for instance in self.infra_config.instances:
            try:
                if instance.type == "simulation":
                    self._load_simulation_logic(instance)
                elif instance.type == "playback":
                    self._load_playback_metadata(instance)
                else:
                    logger.warning(f"Unknown engine type: {instance.type} for {instance.id}")
            except Exception as e:
                logger.error(f"Failed to load logic for instance {instance.id}: {e}")
                raise

        # 执行完所有加载后，global_registry 已构建，且隐式完成了冲突检查
        logger.info(f"All logic loaded. Total tags in registry: {len(self.global_registry)}")

    def _load_simulation_logic(self, instance: EngineInstanceConfig) -> None:
        """加载 Simulation 类型的 DSL 配置并应用命名空间"""
        if DSLParser is None:
            raise ImportError("DSLParser module is missing, cannot load simulation logic")

        source_path = self.base_dir / instance.source
        if not source_path.exists():
            raise FileNotFoundError(f"DSL File not found: {source_path}")
            
        # 使用 DSLParser 解析
        parser = DSLParser()
        program_config = parser.parse_file(source_path)
        
        # 命名空间处理：使用 engine_id 作为 namespace
        namespace = instance.id
        
        # 1. 收集该配置文件中所有实例名，构建映射表
        # ProgramConfig.program 包含所有 ProgramItem
        all_instance_names = {item.name for item in program_config.program if item.type.upper() != "VARIABLE"}
        mapping = {name: f"{namespace}.{name}" for name in all_instance_names}
        
        # 2. 重写 Program Items 并注册位号
        new_items = []
        for item in program_config.program:
            # 应用命名空间和表达式重写
            new_item = self._apply_namespace(item, namespace, mapping)
            new_items.append(new_item)
            
            # 注册到全局注册表
            if new_item.type.upper() == "VARIABLE":
                # item.name 已经被重写为全名
                self._register_tag(new_item.name, instance.id, "variable")
            else:
                # 实例属性注册
                self._register_instance_attributes(new_item, instance.id)
                
        # 更新配置对象的 program 列表
        program_config.program = new_items
        self.logic_configs[instance.id] = program_config

    def _apply_namespace(self, item, namespace: str, mapping: Dict[str, str]):
        """应用命名空间到 ProgramItem"""
        
        new_item = deepcopy(item)
        
        # 重命名 Item
        if item.name in mapping:
            new_item.name = mapping[item.name]
        else:
            # 变量名或其他未在 mapping 中的项
            new_item.name = f"{namespace}.{item.name}"
            
        # 重写表达式
        if new_item.expression:
            new_item.expression = self._rewrite_expression(new_item.expression, mapping)
            
        return new_item

    def _rewrite_expression(self, expression: str, mapping: Dict[str, str]) -> str:
        """使用 AST 重写表达式中的变量引用"""
        try:
            tree = ast.parse(expression, mode="exec")
        except SyntaxError:
            return expression

        class _Rewriter(ast.NodeTransformer):
            def __init__(self, mapping: Dict[str, str]):
                self.mapping = mapping

            def visit_Name(self, node: ast.Name) -> ast.AST:
                if node.id in self.mapping:
                    return self._build_attr_chain(self.mapping[node.id], node)
                return node

            def visit_Attribute(self, node: ast.Attribute) -> ast.AST:
                self.generic_visit(node)
                if isinstance(node.value, ast.Name) and node.value.id in self.mapping:
                    node.value = self._build_attr_chain(self.mapping[node.value.id], node.value)
                return node

            @staticmethod
            def _build_attr_chain(name: str, ref_node: ast.AST) -> ast.AST:
                parts = name.split(".")
                if not parts:
                    return ref_node
                base = ast.Name(id=parts[0], ctx=ast.Load())
                ast.copy_location(base, ref_node)
                current = base
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
                # Fallback for old python versions or simple replacement
                return expression 
        except Exception:
            return expression

    def _register_instance_attributes(self, item, engine_id: str):
        """尝试注册实例的属性"""
        try:
            # 通过 InstanceRegistry 获取类型定义
            from controller.instance import InstanceRegistry
            cls = InstanceRegistry.get_algorithm(item.type) or InstanceRegistry.get_model(item.type)
            if cls and hasattr(cls, "stored_attributes"):
                for attr in cls.stored_attributes:
                    # item.name 已经是带有 namespace 的全名
                    tag_name = f"{item.name}.{attr}"
                    self._register_tag(tag_name, engine_id, "attribute")
        except ImportError:
            pass # Ignore if factory cannot be imported in this context
        except Exception as e:
            logger.warning(f"Error registering attributes for {item.name}: {e}")

    def _register_tag(self, tag: str, engine_id: str, kind: str):
        """注册位号并检查唯一性"""
        if tag in self.global_registry:
            existing = self.global_registry[tag]
            if existing["engine_id"] != engine_id:
                raise ValueError(
                    f"Tag conflict detected: '{tag}' is defined in both "
                    f"'{existing['engine_id']}' and '{engine_id}'"
                )
        
        self.global_registry[tag] = {
            "engine_id": engine_id,
            "kind": kind
        }

    def _load_playback_metadata(self, instance: EngineInstanceConfig) -> None:
        """加载回放文件的元数据（列头）"""
        try:
            import pandas as pd
        except ImportError:
            logger.error("Pandas is required for playback mode. Please install it.")
            raise

        file_path = self.base_dir / instance.source
        if not file_path.exists():
            raise FileNotFoundError(f"Playback source file not found: {file_path}")
        
        try:
            # 只读取表头
            if str(file_path).endswith('.csv'):
                df = pd.read_csv(file_path, nrows=0)
            elif str(file_path).endswith(('.xls', '.xlsx')):
                df = pd.read_excel(file_path, sheet_name=instance.sheet_name, nrows=0)
            else:
                raise ValueError(f"Unsupported file format: {file_path.suffix}")
            
            # 时间列检查
            if instance.time_col and instance.time_col not in df.columns:
                 raise ValueError(f"Time column '{instance.time_col}' not found in {file_path}")

            # 注册列名为 Tag
            for col in df.columns:
                if col == instance.time_col:
                    continue
                
                # 构造 Tag 名称：engine_id.col_name
                # 注意：如果 Excel 列名包含特殊字符，可能需要清洗，这里暂保持原样
                tag_name = f"{instance.id}.{col}"
                self._register_tag(tag_name, instance.id, "playback_tag")
                
            logger.info(f"Loaded playback metadata for {instance.id}: {len(df.columns)} columns")
            
            # Store config for ServiceManager
            self.logic_configs[instance.id] = instance
            
        except Exception as e:
            logger.error(f"Failed to load playback metadata from {file_path}: {e}")
            raise

    def publish_config(self) -> None:
        """
        发布配置：
        1. 将 Global Registry 写入 Redis
        2. 发送 Config Published 通知
        """
        if not self.redis_client:
            logger.warning("No Redis client, cannot publish config")
            return
            
        # 1. Write Registry
        # 这是一个 Hash: Tag -> JSON metadata
        if self.global_registry:
            # 转换为 JSON string map
            mapping = {k: json.dumps(v) for k, v in self.global_registry.items()}
            self.redis_client.delete(self.REGISTRY_KEY) # 清空旧的
            try:
                self.redis_client.hset(self.REGISTRY_KEY, mapping=mapping)
            except Exception:
                # 兼容旧版 Redis 客户端（不支持 mapping 参数）
                pipe = self.redis_client.pipeline()
                for field, value in mapping.items():
                    pipe.hset(self.REGISTRY_KEY, field, value)
                pipe.execute()
            
        # 2. Publish Notification
        # 通知内容必须包含 infra config，因为 Storage/OPCUA 需要知道采样率
        payload = {
            "event": "published",
            "storage_sample_interval": self.infra_config.storage.sample_interval,
            "opcua_publish_interval": self.infra_config.opcua.publish_interval,
            "timestamp": 0 # can define publish time
        }
        self.redis_client.publish(self.CONFIG_EVENT, json.dumps(payload))
        logger.info("Config published to Redis")
