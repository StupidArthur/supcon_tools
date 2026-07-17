"""
FastAPI 入口。

提供：
- 实时模式（常驻引擎）配置与操作接口
- 一次性导出接口
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional
import os
import time
import json
import redis
from fastapi import FastAPI, HTTPException, Request, Response, BackgroundTasks, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, field_validator
# 导入程序和函数（触发注册）
from components import programs  # noqa: F401
from components import functions  # noqa: F401

from controller.parser import DSLParser, ProgramItem
from controller.engine import UnifiedEngine
from controller.clock import ClockMode
from services.export_runner import run_export
from services.service_manager import ServiceManager, ServiceManagerConfig
from datacenter.history_query import HistoryQuery, HistoryQueryConfig
from components.export_templates.template_manager import TemplateManager
from components.utils.logger import get_logger
from components.utils.doc_helper import DocHelper

logger = get_logger()

app = FastAPI(title="data_factory_next", version="0.1.0")

# 配置目录
CONFIG_DIR = Path(__file__).parent.parent / "classical_config"

# 添加 CORS 支持
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 开发环境允许所有来源，生产环境应限制
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 初始化服务管理器（统一管理所有服务）
# 实时模式默认启动 Engine、StorageService 和 OPCUA Server
service_manager = ServiceManager(
    ServiceManagerConfig(
        redis_host=os.getenv("REDIS_HOST", "localhost"),
        redis_port=int(os.getenv("REDIS_PORT", "6379")),
        redis_db=int(os.getenv("REDIS_DB", "0")),
        redis_password=os.getenv("REDIS_PASSWORD"),
        enable_engine=True,  # 默认启用 Engine
        enable_storage=True,  # 默认启用 StorageService
        enable_opcua=True,   # 默认启用 OPCUA Server
        # 历史数据库默认写入项目同级目录下的 storage 目录（避免提交代码时把数据库文件也提交上去）
        storage_db_path=os.getenv(
            "STORAGE_DB_PATH",
            str(Path(__file__).parent.parent.parent / "storage" / "storage_service.duckdb"),
        ),
        opcua_server_url=os.getenv("OPCUA_SERVER_URL", "opc.tcp://0.0.0.0:18951"),
        opcua_enable_write=os.getenv("OPCUA_ENABLE_WRITE", "true").lower() == "true",
        health_check_interval=5.0,
    )
)

# 注意：不要在模块导入阶段启动服务。
# 在 Windows + uvicorn reload 下，导入阶段可能发生多次，会导致 Storage DB 文件锁与 OPCUA 端口占用。
_services_started = False

# 初始化历史数据查询接口（独立于 StorageService，只负责查询）
history_query: Optional[HistoryQuery] = None
try:
    query_config = HistoryQueryConfig(
        db_path=os.getenv(
            "STORAGE_DB_PATH",
            str(Path(__file__).parent.parent.parent / "storage" / "storage_service.duckdb"),
        ),
        # 与 StorageService 同进程运行，避免 DuckDB 报 "different configuration than existing connections"
        read_only=False,
    )
    history_query = HistoryQuery(query_config)
    logger.info("HistoryQuery 初始化成功")
except Exception as e:
    logger.warning(f"HistoryQuery 初始化失败（查询功能将不可用）: {e}")


# ---------- Pydantic 模型 -------------------------------------------------
class ConfigRequest(BaseModel):
    config_path: Optional[str] = None  # 配置文件路径（当dsl_content为空时使用）
    dsl_content: Optional[str] = None  # DSL YAML 内容（字符串），优先使用
    namespace: Optional[str] = Field(default="")


class ParamPatch(BaseModel):
    params: Dict[str, Any]


class VariablePatch(BaseModel):
    expression: Optional[str] = None
    value: Optional[float] = None


class ProgramCreate(BaseModel):
    name: str
    type: str
    expression: str
    init_args: Dict[str, Any] = Field(default_factory=dict)
    namespace: Optional[str] = ""
    display_args: Optional[List[str]] = Field(
        default=None,
        description="与 YAML display_args 相同；None/[] 表示该实例不参与默认绘图与默认导出列",
    )


class ExportFormatOptions(BaseModel):
    """与 YAML 解耦的导出格式；提供时由请求体决定导出样式与文件类型。"""

    header_rows: int = Field(..., description="TITLE 行数：1 或 2")
    title_names: str = Field(default="", description="时间列表头：1 行时为整串；2 行时英文逗号分隔两段")
    time_format: str = Field(default="%Y/%m/%d %H:%M:%S", description="时间列 strftime 格式")
    file_format: str = Field(..., description="csv | xlsx | xls")
    sheet_name: Optional[str] = Field(default=None, description="Excel 工作表名，缺省为「控制器」")

    @field_validator("header_rows")
    @classmethod
    def _v_header_rows(cls, v: int) -> int:
        if v not in (1, 2):
            raise ValueError("header_rows 必须为 1 或 2")
        return v

    @field_validator("file_format")
    @classmethod
    def _v_file_format(cls, v: str) -> str:
        s = (v or "").lower()
        if s not in ("csv", "xlsx", "xls"):
            raise ValueError("file_format 必须为 csv、xlsx 或 xls")
        return s


class ExportRequest(BaseModel):
    dsl_content: Optional[str] = None  # DSL YAML 内容（字符串），优先使用
    config_path: Optional[str] = None  # 配置文件路径（当dsl_content为空时使用）
    steps: int
    template_name: str = Field(
        default="prediction",
        description="未提供 export_format 时用于加载 YAML；提供 export_format 时仅作记录",
    )
    output_path: str
    cycle_time: Optional[float] = Field(default=0.5, description="执行周期（秒）")
    start_time: Optional[float] = Field(default=0.0, description="起始时间")
    time_format: Optional[str] = Field(default="%Y-%m-%d %H:%M:%S", description="时钟时间格式（不影响 export_format 内 time_format）")
    selected_variables: Optional[List[str]] = Field(
        default=None,
        description="仅导出这些位号列；省略时按 DSL 非空 display_args 对应列导出",
    )
    export_format: Optional[ExportFormatOptions] = Field(
        default=None,
        description="若提供则导出选项完全由此决定，不再读取模板 YAML",
    )


class SimulatePreviewRequest(BaseModel):
    """模拟预览请求"""
    dsl_content: str  # DSL YAML 内容（字符串）
    cycle_time: float = Field(default=0.5, description="执行周期（秒）")
    preview_steps: int = Field(default=2000, description="预览周期数")
    start_time: float = Field(default=0.0, description="起始时间")
    time_format: Optional[str] = Field(default="%Y-%m-%d %H:%M:%S", description="时间格式")
    total_steps: Optional[int] = Field(default=None, description="总周期数（用于预估导出时间）")


class TemplateListResponse(BaseModel):
    """模板列表响应"""
    templates: list[str]


class SaveConfigRequest(BaseModel):
    """保存 DSL 配置请求"""
    name: str  # 文件名（无需带后缀也可）
    content: str  # YAML 内容


class ManifestUpdateRequest(BaseModel):
    """更新 engines_manifest.yaml 请求"""
    content: str


@app.get("/config/manifest")
def get_manifest_content() -> Dict[str, Any]:
    """获取 engines_manifest.yaml 内容"""
    manifest_path = Path(__file__).parent.parent / "engines_manifest.yaml"
    if not manifest_path.exists():
        return {"status": "ok", "content": ""}
    
    try:
        content = manifest_path.read_text(encoding="utf-8")
        return {"status": "ok", "content": content}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to read manifest: {exc}")


@app.post("/config/manifest")
def update_manifest_content(req: ManifestUpdateRequest) -> Dict[str, Any]:
    """更新 engines_manifest.yaml 内容"""
    manifest_path = Path(__file__).parent.parent / "engines_manifest.yaml"
    try:
        import yaml
        yaml.safe_load(req.content)
        
        manifest_path.write_text(req.content, encoding="utf-8")
        logger.info("engines_manifest.yaml updated via API")
        return {"status": "ok"}
    except yaml.YAMLError as e:
        raise HTTPException(status_code=400, detail=f"Invalid YAML content: {e}")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Failed to save manifest: {exc}")


@app.post("/services/reload")
def reload_infrastructure() -> Dict[str, Any]:
    """触发 ServiceManager 热重载基础设施"""
    try:
        success = service_manager.reload_infrastructure()
        if success:
            return {"status": "ok", "message": "Infrastructure reload initiated successfully"}
        else:
            raise HTTPException(status_code=500, detail="Reload failed (check logs)")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@app.on_event("startup")
async def startup_event() -> None:
    """应用启动时初始化并启动基础服务（仅执行一次）。"""
    global _services_started
    if _services_started:
        logger.info("startup_event: 服务已启动，跳过重复启动")
        return
    logger.info("=" * 60)
    logger.info("启动实时模式服务...")
    logger.info("=" * 60)
    start_results = service_manager.start_all()
    logger.info("=" * 60)
    logger.info("服务启动结果:")
    logger.info(f"  Engine: {'✓' if start_results.get('engine') else '✗'}")
    logger.info(f"  StorageService: {'✓' if start_results.get('storage') else '✗'}")
    logger.info(f"  OPCUA Server: {'✓' if start_results.get('opcua') else '✗'}")
    logger.info("=" * 60)
    _services_started = True


@app.on_event("shutdown")
async def shutdown_event():
    """应用关闭时优雅关闭所有服务"""
    global _services_started
    logger.info("=" * 60)
    logger.info("关闭所有服务...")
    logger.info("=" * 60)
    try:
        service_manager.close()
        logger.info("ServiceManager 已关闭")
    except Exception as e:
        logger.error(f"关闭 ServiceManager 时出错: {e}", exc_info=True)
    
    # 关闭历史数据查询接口
    global history_query
    if history_query:
        try:
            history_query.close()
            logger.info("HistoryQuery 已关闭")
        except Exception as e:
            logger.error(f"关闭 HistoryQuery 时出错: {e}", exc_info=True)
    _services_started = False
    
    logger.info("所有服务已关闭")


# ---------- 基础接口 ------------------------------------------------------
@app.get("/health")
def health() -> Dict[str, str]:
    """健康检查接口"""
    return {"status": "ok"}


@app.get("/services/status")
def get_services_status() -> Dict[str, Any]:
    """获取所有服务的状态信息"""
    try:
        return {
            "status": "ok",
            **service_manager.get_services_status(),
        }
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/services/diagnostic")
def get_diagnostic_info() -> Dict[str, Any]:
    """获取诊断信息"""
    try:
        return {
            "status": "ok",
            **service_manager.get_diagnostic_info(),
        }
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/services/diagnostic/detail")
def get_detailed_diagnostics() -> Dict[str, Any]:
    """获取详细的诊断信息（从Redis读取）"""
    try:
        redis_client = redis.Redis(
            host=os.getenv("REDIS_HOST", "localhost"),
            port=int(os.getenv("REDIS_PORT", "6379")),
            db=int(os.getenv("REDIS_DB", "0")),
            password=os.getenv("REDIS_PASSWORD"),
            decode_responses=True,
        )
        
        diagnostics = {}
        
        # 动态扫描所有诊断信息键
        diagnostic_keys = redis_client.keys("data_factory:diagnostic:*")
        
        for key in diagnostic_keys:
            # 提取服务名称
            service_name = key.split(":")[-1]
            data_json = redis_client.get(key)
            if data_json:
                try:
                    diagnostics[service_name] = json.loads(data_json)
                except json.JSONDecodeError as e:
                    logger.warning(f"Failed to parse diagnostic data for {service_name}: {e}")
        
        return {
            "status": "ok",
            "diagnostics": diagnostics,
        }
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/services/engines")
def list_active_engines() -> Dict[str, Any]:
    """获取所有活跃的 Engine 列表"""
    try:
        engines_list = []
        for engine_id, engine in service_manager.engines.items():
            engine_type = "simulation"
            if "PlaybackEngine" in engine.__class__.__name__:
                engine_type = "playback"
            
            engines_list.append({
                "id": engine_id,
                "type": engine_type,
                "status": "running"
            })
            
        return {
            "status": "ok",
            "engines": engines_list
        }
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# ---------- 实时模式接口 --------------------------------------------------
def _check_runner(engine_id: str = "default"):
    """检查 runner 是否可用"""
    runner_instance = service_manager.runners.get(engine_id)
    if not runner_instance:
        if engine_id == "default" and service_manager.engine_runner:
            return service_manager.engine_runner
            
        raise HTTPException(
            status_code=503,
            detail=f"Engine {engine_id} 服务未启动，请检查服务状态"
        )
    return runner_instance


@app.post("/realtime/configs")
def load_realtime_config(req: ConfigRequest, engine_id: str = "default") -> Dict[str, str]:
    current_runner = _check_runner(engine_id)
    try:
        if not req.dsl_content and not req.config_path:
            raise ValueError("必须提供 dsl_content 或 config_path")
        
        parser = DSLParser()
        if req.dsl_content:
            config = parser.parse(req.dsl_content)
            # 保存配置到 running_config 目录
            _save_config_to_running_config(req.dsl_content, namespace=req.namespace or "")
        else:
            config = parser.parse_file(req.config_path)
        
        current_runner.load_config(config, namespace=req.namespace or "")
        return {"status": "ok"}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _save_config_to_running_config(dsl_content: str, namespace: str = "") -> None:
    """
    保存DSL配置到 running_config 目录
    
    Args:
        dsl_content: DSL YAML 内容
        namespace: 命名空间（用于文件名，如果为空则使用 "config"）
    """
    try:
        # 创建 running_config 目录（如果不存在）
        running_config_dir = Path(__file__).parent.parent / "controller" / "running_config"
        running_config_dir.mkdir(parents=True, exist_ok=True)
        
        # 生成文件名（使用命名空间，如果没有则使用 "config"）
        if namespace:
            filename = f"{namespace}.yaml"
        else:
            filename = "config.yaml"
        
        file_path = running_config_dir / filename
        
        # 如果文件已存在，覆盖它
        file_path.write_text(dsl_content, encoding="utf-8")
        
        logger.info(f"配置已保存到: {file_path}")
    except Exception as e:
        logger.error(f"保存配置到文件失败: {e}", exc_info=True)
        # 不抛出异常，避免影响配置加载


@app.patch("/realtime/instances/{name}/params")
def patch_instance_params(name: str, req: ParamPatch, engine_id: str = "default") -> Dict[str, str]:
    current_runner = _check_runner(engine_id)
    current_runner.patch_instance_params(name, req.params)
    return {"status": "ok"}


@app.patch("/realtime/variables/{name}")
def patch_variable(name: str, req: VariablePatch, engine_id: str = "default") -> Dict[str, str]:
    current_runner = _check_runner(engine_id)
    current_runner.patch_variable(name, req.expression, req.value)
    return {"status": "ok"}


@app.post("/realtime/programs")
def add_program(req: ProgramCreate, engine_id: str = "default") -> Dict[str, str]:
    current_runner = _check_runner(engine_id)
    try:
        dsl_parser = DSLParser()
        dspec = None
        if req.display_args is not None:
            dspec = dsl_parser._parse_display_args_list(req.name, req.type, req.display_args)
        item = ProgramItem(
            name=req.name,
            type=req.type,
            expression=req.expression,
            init_args=req.init_args,
            display_specs=dspec,
        )
        ns = req.namespace or ""
        if ns:
            item.name = f"{ns}.{item.name}"
        current_runner.add_program_item(item)
        return {"status": "ok"}
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.delete("/realtime/programs/{name}")
def delete_program(name: str, engine_id: str = "default") -> Dict[str, str]:
    current_runner = _check_runner(engine_id)
    current_runner.delete_program(name)
    return {"status": "ok"}


@app.delete("/realtime/variables/{name}")
def delete_variable(name: str, engine_id: str = "default") -> Dict[str, str]:
    current_runner = _check_runner(engine_id)
    current_runner.delete_variable(name)
    return {"status": "ok"}


# 快照中与位号无关的元数据键（与 RealtimePublisher 过滤一致）
_REALTIME_SNAPSHOT_META_KEYS = frozenset(
    {"cycle_count", "need_sample", "time_str", "sim_time", "exec_ratio"}
)

# 与 RealtimePublisher.CURRENT_V2_KEY 一致（多引擎时各写各 field）
_REDIS_V2_CURRENT_HASH = "data_factory:v2:current"


def _params_from_redis_v2(redis_client: Any) -> Dict[str, Any]:
    """从 Redis Hash 解析位号当前值（field → JSON 含 v/t/e）。"""
    out: Dict[str, Any] = {}
    try:
        raw = redis_client.hgetall(_REDIS_V2_CURRENT_HASH)
        if not raw:
            return out
        for tag, j in raw.items():
            try:
                obj = json.loads(j)
                if isinstance(obj, dict) and "v" in obj:
                    out[tag] = obj["v"]
            except (json.JSONDecodeError, TypeError):
                continue
    except Exception as exc:  # noqa: BLE001
        logger.debug("读取 Redis V2 快照失败: %s", exc)
    return out


def _params_from_runner(engine_id: str) -> tuple[Dict[str, Any], Dict[str, Any]]:
    """返回 (位号字典, 元数据字典)，无 runner 或快照无效时位号字典为空。"""
    try:
        runner_instance = service_manager.runners.get(engine_id)
        if not runner_instance and engine_id == "default":
            runner_instance = service_manager.engine_runner
        if not runner_instance:
            return {}, {}
        snap = runner_instance.latest_snapshot()
        if not isinstance(snap, dict) or len(snap) == 0:
            return {}, {}
        params = {
            k: v
            for k, v in snap.items()
            if k not in _REALTIME_SNAPSHOT_META_KEYS
        }
        meta = {
            "cycle_count": snap.get("cycle_count", 0),
            "sim_time": float(snap.get("sim_time") or 0.0),
            "time_str": snap.get("time_str") or "",
        }
        return params, meta
    except Exception as exc:  # noqa: BLE001
        logger.warning("从内存 runner 读取快照失败: %s", exc)
        return {}, {}


@app.get("/realtime/snapshot")
def get_snapshot(engine_id: str = "default") -> Dict[str, Any]:
    """
    获取实时数据位号当前值。

    合并来源（后者覆盖前者，runner 优先保证与本进程引擎一致）：
    1. Redis V2 Hash ``data_factory:v2:current``（多引擎时按 field 合并，较完整）
    2. 本进程 ``RealtimeRunner`` 内存快照

    任一路径有位号即可用于「实时数据」页。
    """
    empty: Dict[str, Any] = {
        "status": "ok",
        "params": {},
        "cycle_count": 0,
        "sim_time": 0.0,
        "time_str": "",
    }

    merged: Dict[str, Any] = {}
    meta_out: Dict[str, Any] = {
        "cycle_count": 0,
        "sim_time": 0.0,
        "time_str": "",
    }

    try:
        redis_client = redis.Redis(
            host=os.getenv("REDIS_HOST", "localhost"),
            port=int(os.getenv("REDIS_PORT", "6379")),
            db=int(os.getenv("REDIS_DB", "0")),
            password=os.getenv("REDIS_PASSWORD"),
            decode_responses=True,
        )

        merged.update(_params_from_redis_v2(redis_client))

    except Exception as exc:  # noqa: BLE001
        logger.warning("从 Redis 读取快照失败: %s", exc)

    rp, rmeta = _params_from_runner(engine_id)
    merged.update(rp)
    if rmeta:
        meta_out.update({k: rmeta[k] for k in ("cycle_count", "sim_time", "time_str") if k in rmeta})

    if not merged:
        return empty

    return {
        "status": "ok",
        "params": merged,
        "cycle_count": meta_out.get("cycle_count", 0),
        "sim_time": meta_out.get("sim_time", 0.0),
        "time_str": meta_out.get("time_str") or "",
        "timestamp": meta_out.get("sim_time", 0.0),
        "datetime": meta_out.get("time_str") or "",
    }


@app.get("/realtime/config")
def get_realtime_config(engine_id: str = "default") -> Dict[str, Any]:
    """获取实时组态信息（实例列表、变量列表等）"""
    current_runner = _check_runner(engine_id)
    try:
        engine = current_runner.engine
        
        # 收集实例信息
        instances_info = {}
        if hasattr(engine, "_instances"):
            for instance_name, instance in engine._instances.items():
                stored_attrs = getattr(instance.__class__, "stored_attributes", [])
                instances_info[instance_name] = {
                    "type": instance.__class__.__name__,
                    "stored_attributes": stored_attrs,
                }
        
        # 收集变量信息
        variables_info = []
        if hasattr(engine, "_program_items"):
            for item in engine._program_items:
                if item.type.upper() == "VARIABLE":
                    variables_info.append({
                        "name": item.name,
                        "expression": item.expression,
                    })
        
        # 收集实例属性信息
        instance_attributes = {}
        if hasattr(engine, "_instances"):
            for instance_name, instance in engine._instances.items():
                stored_attrs = getattr(instance.__class__, "stored_attributes", [])
                instance_attributes[instance_name] = []
                for attr_name in stored_attrs:
                    var_key = f"{instance_name}.{attr_name}"
                    instance_attributes[instance_name].append({
                        "name": attr_name,
                        "full_name": var_key,
                    })
        
        return {
            "status": "ok",
            "instances": instances_info,
            "variables": variables_info,
            "instance_attributes": instance_attributes,
            "program_items": [
                {
                    "name": item.name,
                    "type": item.type,
                    "expression": item.expression,
                }
                for item in getattr(engine, "_program_items", [])
            ],
            "clock_config": {
                "cycle_time": engine.clock.config.cycle_time,
                "sample_interval": engine.clock.config.sample_interval,
                "mode": engine.clock.config.mode.name if hasattr(engine.clock.config.mode, 'name') else str(engine.clock.config.mode),
            },
        }
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/realtime/export")
def export_realtime(engine_id: str = "default") -> Dict[str, Any]:
    """导出实时数据（当前返回快照，可扩展为窗口导出）"""
    current_runner = _check_runner(engine_id)
    return {"status": "ok", "snapshot": current_runner.latest_snapshot()}


@app.get("/realtime/config/redis")
def get_realtime_config_from_redis() -> Dict[str, Any]:
    """从Redis获取实时组态信息（用于组态页面）"""
    try:
        # 获取Redis配置
        redis_host = os.getenv("REDIS_HOST", "localhost")
        redis_port = int(os.getenv("REDIS_PORT", "6379"))
        redis_db = int(os.getenv("REDIS_DB", "0"))
        redis_password = os.getenv("REDIS_PASSWORD")
        
        # 连接Redis
        redis_client = redis.Redis(
            host=redis_host,
            port=redis_port,
            db=redis_db,
            password=redis_password,
            decode_responses=True,
        )
        
        tree: Dict[str, Dict[str, Any]] = {}
        registry_key = "data_factory:registry:tags"
        registry_map = redis_client.hgetall(registry_key) or {}

        # 优先使用运行时注册表，确保与当前 manifest/engine 一致
        if registry_map:
            for full_tag, meta_json in registry_map.items():
                try:
                    meta = json.loads(meta_json) if isinstance(meta_json, str) else {}
                except Exception:
                    meta = {}

                parts = full_tag.split(".")
                if len(parts) < 2:
                    continue

                namespace = parts[0]
                rest = parts[1:]
                node = tree.setdefault(namespace, {"instances": {}, "variables": {}})
                kind = meta.get("kind")

                if kind == "variable" or len(rest) == 1:
                    short_name = ".".join(rest)
                    node["variables"][short_name] = {"full_name": full_tag}
                    continue

                instance_name = rest[0]
                attr_name = ".".join(rest[1:])
                instance_obj = node["instances"].setdefault(
                    instance_name,
                    {
                        "type": "",
                        "full_name": f"{namespace}.{instance_name}",
                        "attributes": [],
                    },
                )
                instance_obj["attributes"].append(
                    {"name": attr_name, "full_name": full_tag}
                )

            return {
                "status": "ok",
                "api_version": "registry-only-20260326",
                "config": {"source": "registry", "tag_count": len(registry_map)},
                "tree": tree,
            }

        return {
            "status": "ok",
            "api_version": "registry-only-20260326",
            "config": None,
            "tree": {},
        }
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# ---------- 导出模式接口 --------------------------------------------------
@app.get("/export/format-defaults/{template_name}")
def get_export_format_defaults(template_name: str) -> Dict[str, Any]:
    """
    根据模板 YAML 返回导出对话框预设默认值。
    """
    try:
        tm = TemplateManager()
        t = tm.load_template(template_name)
        return {
            "status": "ok",
            "defaults": t.to_export_format_defaults(),
        }
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/export/run")
def export_run(req: ExportRequest) -> Dict[str, Any]:
    try:
        import base64

        if not req.dsl_content and not req.config_path:
            raise ValueError("必须提供 dsl_content 或 config_path")

        export_fmt_dict = req.export_format.model_dump() if req.export_format is not None else None

        result = run_export(
            config_path=req.config_path,
            dsl_content=req.dsl_content,
            steps=req.steps,
            template_name=req.template_name,
            output_path=req.output_path,
            cycle_time=req.cycle_time,
            start_time=req.start_time,
            time_format=req.time_format,
            selected_variables=req.selected_variables,
            export_format=export_fmt_dict,
        )

        output_path = Path(result["output_path"])
        file_fmt = result.get("file_format", "csv")
        base_payload: Dict[str, Any] = {
            "status": "ok",
            **result,
            "filename": output_path.name,
        }

        if not output_path.exists():
            return base_payload

        if file_fmt == "csv":
            base_payload["file_content"] = output_path.read_text(encoding="utf-8")
            base_payload["mime_type"] = "text/csv; charset=utf-8"
            base_payload["file_content_base64"] = None
            return base_payload

        raw = output_path.read_bytes()
        base_payload["file_content"] = None
        base_payload["file_content_base64"] = base64.b64encode(raw).decode("ascii")
        if file_fmt == "xlsx":
            base_payload["mime_type"] = (
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
        else:
            base_payload["mime_type"] = "application/vnd.ms-excel"
        return base_payload
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# ---------- 模拟预览接口 --------------------------------------------------
@app.post("/simulate/preview")
def simulate_preview(req: SimulatePreviewRequest) -> Dict[str, Any]:
    """
    模拟预览接口
    
    接收 DSL 配置和参数，返回模拟数据用于前端绘图
    """
    try:
        import tempfile
        import yaml
        
        # 1. 将 DSL 内容写入临时文件
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            f.write(req.dsl_content)
            temp_path = f.name
        
        try:
            # 2. 解析 DSL 配置
            parser = DSLParser()
            config = parser.parse_file(temp_path)
            
            # 注意：预览模式通常使用前端传入的 DSL 内容，不应用命名空间
            # 如果用户需要命名空间，应该在 DSL 内容中手动添加
            
            # 3. 修改时钟配置
            config.clock.cycle_time = req.cycle_time
            # 对于预览，我们希望每个周期都采样，所以设置 sample_interval = None（每个周期都采样）
            config.clock.sample_interval = None  # None 表示每个周期都采样
            config.clock.mode = ClockMode.GENERATOR
            config.clock.start_time = req.start_time
            if req.time_format:
                config.clock.time_format = req.time_format
            
            logger.info(f"时钟配置: cycle_time={config.clock.cycle_time}, "
                       f"sample_interval={config.clock.sample_interval}, "
                       f"mode={config.clock.mode.name}")
            
            # 4. 创建引擎并运行
            engine = UnifiedEngine.from_program_config(config)
            variable_meta = engine.get_variable_meta()
            display_variables = engine.get_display_variables()

            start_time = time.time()
            snapshots = engine.run_generator(req.preview_steps)
            generation_time = time.time() - start_time
            
            # 记录模拟数据完整性日志
            logger.info(f"模拟完成: 总周期数={req.preview_steps}, 生成快照数={len(snapshots)}")
            if snapshots:
                logger.info(f"第一个快照: cycle_count={snapshots[0].get('cycle_count')}, "
                          f"need_sample={snapshots[0].get('need_sample')}, "
                          f"变量数={len([k for k in snapshots[0].keys() if k not in {'cycle_count', 'need_sample', 'time_str', 'sim_time'}])}")
                logger.info(f"最后一个快照: cycle_count={snapshots[-1].get('cycle_count')}, "
                          f"need_sample={snapshots[-1].get('need_sample')}")
            
            # 5. 检查数据完整性
            logger.info(f"模拟完成: 总周期数={req.preview_steps}, 生成快照数={len(snapshots)}")
            if len(snapshots) != req.preview_steps:
                logger.warning(f"数据不完整: 期望{req.preview_steps}个周期, 实际{len(snapshots)}个快照")
            
            # 检查采样标志分布
            sampled_count = sum(1 for s in snapshots if s.get("need_sample", True))
            not_sampled_count = len(snapshots) - sampled_count
            logger.info(f"采样标志统计: 需要采样={sampled_count}, 不需要采样={not_sampled_count}")
            
            # 检查前几个和后几个快照的采样标志
            if snapshots:
                logger.info(f"前5个快照的采样标志: {[s.get('need_sample') for s in snapshots[:5]]}")
                logger.info(f"后5个快照的采样标志: {[s.get('need_sample') for s in snapshots[-5:]]}")
                logger.info(f"前5个快照的周期计数: {[s.get('cycle_count') for s in snapshots[:5]]}")
                logger.info(f"后5个快照的周期计数: {[s.get('cycle_count') for s in snapshots[-5:]]}")
            
            # 提取数据用于绘图（只取采样周期的数据）
            sampled_snapshots = [s for s in snapshots if s.get("need_sample", True)]
            logger.info(f"采样数据: 总快照数={len(snapshots)}, 采样快照数={len(sampled_snapshots)}")
            
            # 如果采样数据为空，使用所有数据
            if len(sampled_snapshots) == 0:
                logger.warning("没有采样数据，使用所有快照数据")
                sampled_snapshots = snapshots
            
            # 6. 计算预估导出时间（线性计算）
            total_steps = req.total_steps or req.preview_steps  # 使用用户指定的总周期数，否则使用预览周期数
            estimated_export_time = (generation_time / req.preview_steps) * total_steps if req.preview_steps > 0 else 0
            
            # 7. 提取变量名（排除元数据字段）
            metadata_fields = {"cycle_count", "need_sample", "time_str", "sim_time", "exec_ratio"}
            if sampled_snapshots:
                variable_names = [
                    key for key in sampled_snapshots[0].keys() 
                    if key not in metadata_fields
                ]
                logger.info(f"变量列表: {variable_names}")
                # 检查每个变量的数据完整性
                for var_name in variable_names:
                    var_data = [s[var_name] for s in sampled_snapshots if var_name in s]
                    if len(var_data) != len(sampled_snapshots):
                        logger.warning(f"变量 {var_name} 数据不完整: 期望{len(sampled_snapshots)}个值, 实际{len(var_data)}个")
                    else:
                        logger.debug(f"变量 {var_name}: 数据点数={len(var_data)}, "
                                   f"最小值={min(var_data) if var_data else 'N/A'}, "
                                   f"最大值={max(var_data) if var_data else 'N/A'}")
            else:
                variable_names = []
                logger.warning("没有找到任何变量数据")

            display_variables_filtered = [
                k for k in display_variables if k in variable_names
            ]

            all_plot_scales = engine.get_plot_scales()
            plot_scales = {
                k: v for k, v in all_plot_scales.items() if k in variable_names
            }

            # 8. 构建返回数据
            return {
                "status": "ok",
                "data": sampled_snapshots,
                "variable_names": variable_names,
                "display_variables": display_variables_filtered,
                "variable_meta": variable_meta,
                "plot_scales": plot_scales,
                "generation_time": round(generation_time, 4),
                "data_points": len(sampled_snapshots),
                "estimated_export_time": round(estimated_export_time, 4),
                "total_steps": total_steps,
            }
        finally:
            # 清理临时文件
            Path(temp_path).unlink(missing_ok=True)
            
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/templates/list")
def get_template_list() -> TemplateListResponse:
    """获取所有可用的导出模板列表"""
    try:
        template_manager = TemplateManager()
        templates = template_manager.list_templates()
        return TemplateListResponse(templates=templates)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/config/default")
def get_default_config() -> Dict[str, str]:
    """获取默认 DSL 配置内容"""
    try:
        default_config_path = CONFIG_DIR / "display_demo.yaml"
        if default_config_path.exists():
            content = default_config_path.read_text(encoding="utf-8")
            return {"status": "ok", "content": content}
        else:
            raise HTTPException(status_code=404, detail="默认配置文件不存在")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/config/list")
def list_config_files() -> Dict[str, Any]:
    """
    获取 config 目录下的所有 YAML 配置（名称 + 文件名 + 内容）。
    供前端做快捷标签切换。
    """
    try:
        configs: List[Dict[str, Any]] = []
        if not CONFIG_DIR.exists():
            raise HTTPException(status_code=404, detail="config 目录不存在")

        for path in sorted(CONFIG_DIR.glob("*.yaml")):
            content = path.read_text(encoding="utf-8")
            configs.append(
                {
                    "name": path.stem,
                    "filename": path.name,
                    "content": content,
                }
            )

        return {"status": "ok", "configs": configs}
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/config/save")
def save_config(req: SaveConfigRequest) -> Dict[str, Any]:
    """
    保存 DSL 配置到 config 目录。
    - 自动补全 .yaml 后缀
    - 基于文件名创建/覆盖同名文件
    """
    try:
        if not req.name or not req.name.strip():
            raise HTTPException(status_code=400, detail="文件名不能为空")
        if not req.content or not req.content.strip():
            raise HTTPException(status_code=400, detail="内容不能为空")

        # 只取文件名，防止目录穿越
        filename = Path(req.name.strip()).name
        if not filename.lower().endswith(".yaml"):
            filename = f"{filename}.yaml"

        target_path = CONFIG_DIR / filename
        target_path.write_text(req.content, encoding="utf-8")

        return {"status": "ok", "filename": filename}
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/readme")
def get_readme() -> Dict[str, str]:
    """获取 README.md 内容"""
    try:
        readme_path = Path(__file__).parent.parent / "README.md"
        if readme_path.exists():
            content = readme_path.read_text(encoding="utf-8")
            return {"status": "ok", "content": content}
        else:
            raise HTTPException(status_code=404, detail="README.md 文件不存在")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# ---------- 文档接口 --------------------------------------------------
@app.get("/docs/programs/list")
def get_programs_list() -> Dict[str, Any]:
    """获取所有程序（算法和模型）列表"""
    try:
        program_list = DocHelper.get_program_list()
        return {"status": "ok", "programs": program_list}
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/docs/functions/list")
def get_functions_list() -> Dict[str, Any]:
    """获取所有函数列表"""
    try:
        function_list = DocHelper.get_function_list()
        return {"status": "ok", "functions": function_list}
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/docs/program/{program_name}")
def get_program_doc(program_name: str) -> Dict[str, Any]:
    """获取指定程序的文档信息"""
    try:
        doc_info = DocHelper.get_program_doc(program_name)
        if doc_info:
            return {"status": "ok", **doc_info.to_dict()}
        else:
            raise HTTPException(status_code=404, detail=f"程序 {program_name} 不存在或没有文档信息")
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/docs/function/{function_name}")
def get_function_doc(function_name: str) -> Dict[str, Any]:
    """获取指定函数的文档信息"""
    try:
        doc_info = DocHelper.get_function_doc(function_name)
        if doc_info:
            return {"status": "ok", **doc_info.to_dict()}
        else:
            raise HTTPException(status_code=404, detail=f"函数 {function_name} 不存在或没有文档信息")
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# ---------- 历史数据查询接口 --------------------------------------------------
class HistoryQueryRequest(BaseModel):
    """历史数据查询请求"""
    param_name: str  # 参数名称（位号名）
    end_time: Optional[str] = None  # 终止时间（ISO格式字符串，如果为None则使用当前时间）
    time_length: float = Field(default=1200.0, description="时间长度（秒），默认1200秒")
    sample_points: int = Field(default=1200, description="采样点数，默认1200点")


@app.post("/history/query")
def query_history_data(req: HistoryQueryRequest) -> Dict[str, Any]:
    """
    查询历史数据（固定采样点数）
    
    根据时间长度和采样点数，自动计算采样间隔，返回固定数量的采样点
    """
    try:
        from datetime import datetime, timedelta
        
        # 检查HistoryQuery是否可用
        if not history_query:
            raise HTTPException(status_code=503, detail="HistoryQuery未初始化")
        
        # 计算时间范围
        if req.end_time:
            try:
                # 尝试解析ISO格式时间字符串
                # 处理Z时区标识
                end_time_str = req.end_time.replace('Z', '+00:00')
                # 如果没有时区信息，添加本地时区
                if '+' not in end_time_str and end_time_str.count(':') == 2:
                    # 格式：YYYY-MM-DDTHH:mm:ss，添加时区
                    end_time_str = end_time_str + '+00:00'
                end_time = datetime.fromisoformat(end_time_str)
                
                # 如果datetime有时区信息，转换为本地时间（naive datetime）
                # 因为数据库存储的是本地时间（无时区）
                if end_time.tzinfo is not None:
                    # 转换为本地时区（使用系统默认时区）
                    # astimezone() 不带参数时使用系统默认时区
                    end_time = end_time.astimezone().replace(tzinfo=None)
                    logger.debug(f"时区转换: {req.end_time} -> {end_time}")
            except (ValueError, AttributeError) as e:
                # 如果解析失败，使用当前时间
                logger.warning(f"无法解析时间字符串: {req.end_time}，错误: {e}，使用当前时间")
                end_time = datetime.now()
        else:
            end_time = datetime.now()
        
        start_time = end_time - timedelta(seconds=req.time_length)
        
        # 计算采样间隔（确保返回固定数量的点）
        # 采样间隔 = 时间长度 / (采样点数 - 1)
        if req.sample_points > 1:
            sample_interval = req.time_length / (req.sample_points - 1)
        else:
            sample_interval = req.time_length
        
        # 记录查询参数（详细日志）
        logger.info(f"查询历史数据: param_name={req.param_name}, start_time={start_time} (类型: {type(start_time)}), end_time={end_time} (类型: {type(end_time)}), sample_interval={sample_interval}")
        
        # 执行采样查询
        try:
            records = history_query.query_sampled(
                param_name=req.param_name,
                start_time=start_time,
                end_time=end_time,
                sample_interval=sample_interval,
                limit=req.sample_points * 2  # 多查询一些，确保有足够的数据点
            )
            
            logger.info(f"查询结果: 返回 {len(records)} 条记录")
        except Exception as e:
            logger.error(f"查询历史数据失败: {e}", exc_info=True)
            raise HTTPException(status_code=500, detail=f"查询历史数据失败: {str(e)}") from e
        
        # 如果返回的点数超过要求，进行均匀采样
        if len(records) > req.sample_points:
            # 按时间排序（升序）
            records.sort(key=lambda x: x['timestamp'])
            # 均匀采样
            step = len(records) / req.sample_points
            sampled_records = []
            for i in range(req.sample_points):
                idx = int(i * step)
                if idx < len(records):
                    sampled_records.append(records[idx])
            records = sampled_records
        elif len(records) < req.sample_points and len(records) > 0:
            # 如果点数不足，重复最后一个点
            last_record = records[-1]
            while len(records) < req.sample_points:
                records.append(last_record.copy())
        
        # 确保返回固定数量的点
        records = records[:req.sample_points]
        
        # 转换为前端需要的格式
        result = {
            "status": "ok",
            "param_name": req.param_name,
            "start_time": start_time.isoformat(),
            "end_time": end_time.isoformat(),
            "time_length": req.time_length,
            "sample_points": len(records),
            "data": records,
        }
        
        return result
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        logger.error(f"查询历史数据失败: {exc}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(exc)) from exc

