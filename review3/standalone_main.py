"""
Data Factory Next - Standalone 启动器

单进程、可执行程序入口。
整合 Engine Thread 和 OPC UA 协程，通过内存队列通信。

支持多实例运行（每个实例有独立的 shared_data 和 cmd_queue）。
"""

from __future__ import annotations

import argparse
import asyncio
import os
import queue
import sys
import threading
import time
from pathlib import Path
from typing import Dict, Any, Tuple, List, Optional, Callable

# 获取脚本所在目录（打包后指向exe所在目录）
_script_dir = Path(sys.argv[0] if sys.argv else __file__).resolve().parent
if str(_script_dir) not in sys.path:
    sys.path.insert(0, str(_script_dir))

# 确保 components/programs 能够被正确导入（触发算法/模型的自动注册）
import components.programs  # noqa: F401

from controller.parser import DSLParser
from controller.engine import UnifiedEngine
from datacenter.opcua_server import StandaloneOpcuaServer, OPCUAServerConfig


def run_engine_thread(
    yaml_path: str,
    instance_name: str,
    shared_data: dict,
    cmd_queue: queue.Queue,
    server_url: str,
    stop_event: threading.Event,
    mode_override: str = None,
    cycle_time_override: float = None,
    on_snapshot: Optional[Callable[[Dict[str, Any]], None]] = None,
    engine_holder: Optional[Dict[str, Any]] = None,
) -> None:
    """
    引擎线程逻辑。

    Args:
        yaml_path: YAML 配置文件路径
        instance_name: 实例名称（用于日志区分）
        shared_data: 共享内存数据字典
        cmd_queue: 命令队列（接收外部写值命令）
        server_url: OPCUA 服务器地址（用于日志）
        stop_event: 停止信号，主线程设置后引擎线程退出循环
        mode_override: CLI 覆盖时钟模式（REALTIME / GENERATOR）
        cycle_time_override: CLI 覆盖周期时间（秒）
        on_snapshot: 每周期回调，传入完整 snapshot（含元数据）。供 FastAPI WS 等用。
        engine_holder: 若提供，引擎实例创建后会写入 ``engine_holder["engine"]``，供外部线程取用。
    """
    parser = DSLParser()
    config = parser.parse_file(yaml_path)

    if mode_override:
        from controller.clock import ClockMode
        config.clock.mode = ClockMode[mode_override.upper()]
    if cycle_time_override is not None:
        config.clock.cycle_time = cycle_time_override

    engine = UnifiedEngine.from_program_config(config)

    if engine_holder is not None:
        engine_holder["engine"] = engine

    print(f"[Engine:{instance_name}] Started with config: {yaml_path}")
    print(f"[Engine:{instance_name}] Cycle time: {config.clock.cycle_time}s, Mode: {config.clock.mode}")

    engine.clock.start()

    try:
        while not stop_event.is_set():
            # a. 处理写指令回传（来自 OPCUA 等外部系统）
            while not cmd_queue.empty():
                try:
                    cmd = cmd_queue.get_nowait()
                    engine.override_variable(cmd["tag"], cmd["value"])
                    print(f"[Engine:{instance_name}] Override: {cmd['tag']} = {cmd['value']}")
                except queue.Empty:
                    break

            # b. 执行步进计算（_step_once 内部会调用 clock.step 处理 sleep）
            snapshot = engine.step()

            # c. 更新全局内存字典
            # 快照中包含 cycle_count, need_sample, time_str, sim_time 等元数据
            # 以及所有变量的当前值
            for key, value in snapshot.items():
                if key not in ("cycle_count", "need_sample", "time_str", "sim_time", "exec_ratio"):
                    shared_data[key] = value

            # d. 完整 snapshot 回调（FastAPI WS / export 用）
            if on_snapshot is not None:
                try:
                    on_snapshot(snapshot)
                except Exception as e:
                    print(f"[Engine:{instance_name}] on_snapshot callback error: {e}")

    except KeyboardInterrupt:
        print(f"[Engine:{instance_name}] Stopped by user")
    except Exception as e:
        print(f"[Engine:{instance_name}] Error: {e}")
        raise
    finally:
        engine.clock.stop()
        print(f"[Engine:{instance_name}] Stopped")


def run_opcua_async(
    instance_name: str,
    server: StandaloneOpcuaServer,
) -> None:
    """
    OPCUA 协程线程入口（阻塞等待 server 后台线程结束）。

    Args:
        instance_name: 实例名称（用于日志区分）
        server: 已创建的 StandaloneOpcuaServer 实例（由 run_instance 传入）
    """
    print(f"[OPCUA:{instance_name}] Waiting for server thread to exit")
    try:
        server.join()
    except KeyboardInterrupt:
        print(f"[OPCUA:{instance_name}] Stopped by user")
        server.stop()
    except Exception as e:
        print(f"[OPCUA:{instance_name}] Error: {e}")
        raise
    finally:
        print(f"[OPCUA:{instance_name}] Stopped")


def find_config_path(config_arg: str) -> Path:
    """查找配置文件路径"""
    config_path = Path(config_arg)
    if config_path.exists():
        return config_path

    # 尝试 config 目录下的常见路径
    alternative_paths = [
        Path("config") / config_arg,
        Path("config") / f"{config_arg}.yaml",
        Path("config") / f"{config_arg}.yml",
    ]

    for alt_path in alternative_paths:
        if alt_path.exists():
            return alt_path

    print(f"Error: Config file not found: {config_arg}")
    sys.exit(1)


def discover_configs(config_dir: Path = Path("config")) -> Dict[str, Path]:
    """
    自动发现 config 目录下（含子目录）的所有 YAML 文件。

    使用 ``rglob`` 递归扫描，子目录里的 yaml 也会被发现（例如
    ``config/tank/foo.yaml`` 会被作为 ``tank/foo`` 注册）。

    历史归档目录 ``old_version`` 会被显式跳过，避免旧语法文件覆盖正式配置。
    如需读取旧语法样例，请由测试代码显式指定路径。

    Returns:
        {实例名: 配置文件路径} 字典。
        不同路径下同名 stem 的 yaml 会触发 warning 并后者覆盖前者（保持向后兼容）。
    """
    configs: Dict[str, Path] = {}

    if not config_dir.exists():
        return configs

    for pattern in ("*.yaml", "*.yml"):
        for yaml_file in config_dir.rglob(pattern):
            # 跳过历史归档目录（old_version），避免旧语法文件覆盖正式配置
            if "old_version" in yaml_file.parts:
                continue
            instance_name = yaml_file.stem
            if instance_name in configs:
                print(
                    f"[Main] WARNING: 实例名冲突 '{instance_name}'，"
                    f"{configs[instance_name]} 将被 {yaml_file} 覆盖"
                )
            configs[instance_name] = yaml_file

    return configs


def run_instance(
    yaml_path: str,
    instance_name: str,
    server_url: str,
    as_daemon: bool = False,
    mode_override: str = None,
    cycle_time_override: float = None,
    on_snapshot: Optional[Callable[[Dict[str, Any]], None]] = None,
    engine_holder: Optional[Dict[str, Any]] = None,
) -> Tuple[threading.Thread, threading.Thread, StandaloneOpcuaServer, threading.Event, Dict[str, float]]:
    """
    运行一个引擎+OPCUA 实例。

    Args:
        yaml_path: YAML 配置文件路径
        instance_name: 实例名称（用于日志区分和端口区分）
        server_url: OPCUA 服务器地址
        as_daemon: 是否以守护线程方式运行
        mode_override: CLI 覆盖时钟模式
        cycle_time_override: CLI 覆盖周期时间
        on_snapshot: 每周期回调，传入完整 snapshot
        engine_holder: 若提供，引擎实例写入 ``engine_holder["engine"]``

    Returns:
        (engine_thread, opcua_thread, server, stop_event, shared_data)
    """
    shared_data: Dict[str, float] = {}
    cmd_queue: queue.Queue = queue.Queue()
    stop_event = threading.Event()

    # 启动引擎守护线程
    engine_thread = threading.Thread(
        target=run_engine_thread,
        args=(yaml_path, instance_name, shared_data, cmd_queue, server_url, stop_event,
              mode_override, cycle_time_override, on_snapshot, engine_holder),
        daemon=as_daemon,
        name=f"EngineThread-{instance_name}"
    )
    engine_thread.start()
    print(f"[Main:{instance_name}] Engine thread started")

    # 等待引擎线程初始化
    time.sleep(0.5)

    # 创建 OPCUA Server 实例（让主线程可以同步等待 ready）
    opcua_config = OPCUAServerConfig(
        server_url=server_url,
        update_cycle=0.1,
        enable_write=True,
    )
    server = StandaloneOpcuaServer(
        config=opcua_config,
        shared_data=shared_data,
        cmd_queue=cmd_queue,
    )
    print(f"[OPCUA:{instance_name}] Server instance created at {opcua_config.server_url}")

    # 启动 OPCUA Server（内部创建后台线程运行 asyncio 循环）
    server.start()
    print(f"[Main:{instance_name}] OPCUA server starting...")

    # 启动 OPCUA 线程（阻塞等待 server 后台线程结束）
    opcua_thread = threading.Thread(
        target=run_opcua_async,
        args=(instance_name, server),
        daemon=as_daemon,
        name=f"OPCUAServer-{instance_name}"
    )
    opcua_thread.start()
    print(f"[Main:{instance_name}] OPCUA thread started")

    # 等待 server 真正监听端口（避免客户端在 start() 后立即连接失败）
    if server.wait_ready(timeout=5.0):
        print(f"[Main:{instance_name}] OPCUA server ready at {server_url}")
    else:
        print(f"[Main:{instance_name}] WARNING: OPCUA server 未在 5s 内就绪，请检查端口 {server_url}")

    return engine_thread, opcua_thread, server, stop_event, shared_data


def _write_rows_export(rows, columns, output_path, fmt, sheet_name):
    """将内存结果行（_cycle 序号列 + 数据列）写为 csv/xlsx/xls，不重新仿真。"""
    if fmt == "csv":
        import csv as _csv
        with open(output_path, "w", newline="", encoding="utf-8") as f:
            w = _csv.writer(f)
            w.writerow(columns)
            for row in rows:
                w.writerow(["" if row.get(c) is None else row.get(c) for c in columns])
        return
    if fmt == "xlsx":
        from openpyxl import Workbook
        wb = Workbook()
        ws = wb.active
        ws.title = (sheet_name or "控制器")[:31]
        ws.append(columns)
        for row in rows:
            ws.append([row.get(c) for c in columns])
        wb.save(output_path)
        return
    if fmt == "xls":
        import xlwt
        book = xlwt.Workbook(encoding="utf-8")
        sheet = book.add_sheet((sheet_name or "控制器")[:31])
        for j, c in enumerate(columns):
            sheet.write(0, j, c)
        for i, row in enumerate(rows, start=1):
            for j, c in enumerate(columns):
                v = row.get(c)
                sheet.write(i, j, "" if v is None else v)
        book.save(output_path)
        return
    raise ValueError(f"不支持的导出格式: {fmt}")


def _run_convert_export(args):
    """--convert-export：读取 rows JSON，转换为格式化导出文件（不运行仿真）。"""
    import json as _json
    if not args.rows_json or not args.export:
        print("Error: --convert-export requires --rows-json and --export")
        sys.exit(1)
    with open(args.rows_json, "r", encoding="utf-8-sig") as f:
        payload = _json.load(f)
    columns = payload.get("columns", [])
    rows = payload.get("rows", [])
    fmt = (args.format or "csv").lower()
    _write_rows_export(rows, columns, args.export, fmt, args.sheet_name or "控制器")
    print(f"Done! Converted {len(rows)} rows to {args.export} ({fmt})")


def main() -> None:
    """主程序入口"""
    parser = argparse.ArgumentParser(description="Data Factory Next - Standalone")
    parser.add_argument(
        "-c", "--config",
        default=None,
        help="Path to a specific YAML config file"
    )
    parser.add_argument(
        "-n", "--name",
        default="default",
        help="Instance name (for logging and server URL)"
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="OPCUA server port (default: auto-assign per instance starting from 18951)"
    )
    parser.add_argument(
        "--daemon",
        action="store_true",
        help="Run as daemon threads"
    )
    parser.add_argument(
        "--config-dir",
        default="config",
        help="Directory to scan for YAML configs (default: config)"
    )
    parser.add_argument(
        "--mode",
        choices=["REALTIME", "GENERATOR"],
        default=None,
        help="Override clock mode from YAML config"
    )
    parser.add_argument(
        "--cycle-time",
        type=float,
        default=None,
        help="Override cycle time in seconds"
    )
    parser.add_argument(
        "--batch",
        type=int,
        default=None,
        help="Run in batch mode: execute N cycles and export CSV (GENERATOR mode)"
    )
    parser.add_argument(
        "--export",
        type=str,
        default=None,
        help="CSV export path for batch mode (e.g., output.csv)"
    )
    parser.add_argument(
        "--format",
        choices=["csv", "xlsx", "xls"],
        default=None,
        help="批量导出文件格式；指定后走引擎模板导出（时间列+表头），否则输出全列裸 CSV"
    )
    parser.add_argument(
        "--columns",
        type=str,
        default=None,
        help="导出列，英文逗号分隔；留空则用 DSL display_args（get_display_variables）"
    )
    parser.add_argument(
        "--template",
        type=str,
        default="prediction",
        help="导出模板名（决定表头行数/时间格式等），默认 prediction"
    )
    parser.add_argument(
        "--sheet-name",
        type=str,
        default=None,
        help="Excel 工作表名（仅 xlsx/xls），缺省「控制器」"
    )
    parser.add_argument(
        "--convert-export",
        action="store_true",
        help="将 --rows-json 指定的内存结果行转换为格式化导出文件（csv/xlsx/xls），不运行仿真"
    )
    parser.add_argument(
        "--rows-json",
        type=str,
        default=None,
        help="--convert-export 的输入：{\"columns\": [...], \"rows\": [{...}, ...]}"
    )
    parser.add_argument(
        "--api",
        action="store_true",
        help="Enable FastAPI debug HTTP+WebSocket server (for Wails GUI tooling)"
    )
    parser.add_argument(
        "--api-host",
        type=str,
        default="127.0.0.1",
        help="FastAPI host (default: 127.0.0.1)"
    )
    parser.add_argument(
        "--api-port",
        type=int,
        default=8000,
        help="FastAPI port (default: 8000)"
    )
    args = parser.parse_args()

    # 内存结果行转换导出（不运行仿真，也不需要配置文件）
    if args.convert_export:
        _run_convert_export(args)
        sys.exit(0)

    # 收集所有要运行的实例
    instances: Dict[str, Tuple[str, str]] = {}  # {instance_name: (yaml_path, server_url)}

    if args.config:
        # 单个配置文件模式
        config_path = find_config_path(args.config)
        instance_name = args.name
        port = args.port or 18951
        server_url = f"opc.tcp://0.0.0.0:{port}"
        instances[instance_name] = (str(config_path), server_url)
        print(f"Using config: {config_path}")
    else:
        # 自动发现模式：扫描 config 目录
        config_dir = Path(args.config_dir)
        discovered = discover_configs(config_dir)

        if not discovered:
            print(f"No YAML configs found in {config_dir}/")
            print("Place YAML files in the config directory or use -c to specify a file")
            sys.exit(1)

        base_port = args.port or 18951
        for i, (instance_name, yaml_path) in enumerate(sorted(discovered.items())):
            port = base_port + i
            server_url = f"opc.tcp://0.0.0.0:{port}"
            instances[instance_name] = (str(yaml_path), server_url)

        print(f"Discovered {len(instances)} config(s) in {config_dir}/:")
        for name, (path, url) in instances.items():
            print(f"  - {name}: {path} -> {url}")

    # Batch模式：快速运行并导出CSV
    if args.batch:
        if not args.config:
            print("Error: --batch requires -c to specify a config file")
            sys.exit(1)
        if args.api:
            print("Error: --api 与 --batch 互斥（批量模式不开 API）")
            sys.exit(1)

        yaml_path = list(instances.values())[0][0]

        # 创建引擎
        parser = DSLParser()
        config = parser.parse_file(yaml_path)
        # 模板导出（--format）需要每个周期都采样，导出器只取 need_sample=True 的行。
        if args.format:
            config.clock.sample_interval = None
        engine = UnifiedEngine.from_program_config(config)

        print(f"Batch mode: running {args.batch} cycles in GENERATOR mode...")
        print(f"Config: {yaml_path}")
        print(f"Cycle time: {config.clock.cycle_time}s")

        # 强制切换到GENERATOR模式
        from controller.clock import ClockMode
        engine.clock.config.mode = ClockMode.GENERATOR
        engine.clock.config.cycle_time = args.cycle_time if args.cycle_time is not None else config.clock.cycle_time

        # 执行
        engine.clock.start()
        results = []
        for i in range(args.batch):
            snapshot = engine.step()
            results.append(snapshot)
            if (i + 1) % 100 == 0:
                print(f"  Progress: {i + 1}/{args.batch} cycles")
        engine.clock.stop()

        # 导出
        output_path = args.export or "output.csv"
        print(f"Exporting to {output_path}...")

        if args.format:
            # 模板导出：engine.export_snapshots（时间列 + 表头，csv/xlsx/xls）。
            # 列由 --columns 指定，留空则用 DSL display_args。
            from components.export_templates import TemplateManager
            template = TemplateManager().load_template(args.template)
            if args.columns:
                export_columns = [c.strip() for c in args.columns.split(",") if c.strip()]
            else:
                export_columns = engine.get_display_variables()
            engine.export_snapshots(
                results,
                output_path,
                template,
                file_format=args.format,
                sheet_name=args.sheet_name,
                selected_variables=export_columns,
            )
            print(
                f"Done! Exported {len(results)} cycles to {output_path} "
                f"({args.format}, {len(export_columns)} columns)"
            )
            sys.exit(0)

        # 裸 CSV（供趋势图展示）：全部数据列 + display.json sidecar
        import csv
        if results:
            # 获取所有键
            keys = set()
            for r in results:
                keys.update(r.keys())

            # 过滤掉内部元数据
            exclude_keys = {"cycle_count", "need_sample", "time_str", "sim_time", "exec_ratio"}
            export_keys = sorted([k for k in keys if k not in exclude_keys])

            with open(output_path, 'w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=export_keys, extrasaction='ignore')
                writer.writeheader()
                writer.writerows(results)

            # 默认绘图列：来自 DSL display_args（引擎权威实现 get_display_variables）。
            # 写为 CSV 旁的 sidecar，供组态工具前端做默认选中，避免前端自行猜测。
            import json
            display_columns = engine.get_display_variables()
            with open(output_path + ".display.json", "w", encoding="utf-8") as f:
                json.dump({"display_columns": display_columns}, f, ensure_ascii=False)

        print(f"Done! Exported {len(results)} rows to {output_path}")
        sys.exit(0)

    # 启动所有实例
    threads: List[Tuple[threading.Thread, threading.Thread, StandaloneOpcuaServer, threading.Event, Dict[str, float]]] = []
    api_thread: Optional[threading.Thread] = None
    api_binding = None

    # 如果启用了 --api，则只支持单实例（MVP）
    if args.api and len(instances) > 1:
        print("Error: --api MVP 仅支持单实例；请用 -c 指定单个 config")
        sys.exit(1)

    for instance_name, (yaml_path, server_url) in instances.items():
        engine_holder: Dict[str, Any] = {}

        if args.api:
            # 延迟导入：避免未启用 --api 时也要装 fastapi/uvicorn
            from datacenter.engine_api import EngineBinding
            api_binding = EngineBinding(
                instance_name=instance_name,
                engine=None,  # 引擎在 run_engine_thread 里建好后通过 holder 注入
                shared_data={},
            )

            def _on_snapshot(snap: Dict[str, Any]) -> None:
                api_binding.push_snapshot(snap)

            t1, t2, server, stop_ev, shared_data = run_instance(
                yaml_path=yaml_path,
                instance_name=instance_name,
                server_url=server_url,
                as_daemon=args.daemon,
                mode_override=args.mode,
                cycle_time_override=args.cycle_time,
                on_snapshot=_on_snapshot,
                engine_holder=engine_holder,
            )
            # 等引擎线程创建出 engine 实例
            for _ in range(50):
                if engine_holder.get("engine") is not None:
                    break
                time.sleep(0.1)
            api_binding.engine = engine_holder.get("engine")
            api_binding.shared_data = shared_data
            if api_binding.engine is None:
                print(f"[Main] WARNING: 引擎未在 5s 内初始化完，API 可能无法使用")
            threads.append((t1, t2, server, stop_ev, shared_data))
        else:
            t1, t2, server, stop_ev, shared_data = run_instance(
                yaml_path=yaml_path,
                instance_name=instance_name,
                server_url=server_url,
                as_daemon=args.daemon,
                mode_override=args.mode,
                cycle_time_override=args.cycle_time,
            )
            threads.append((t1, t2, server, stop_ev, shared_data))

    # 启动 FastAPI server（如启用）
    if args.api and api_binding is not None:
        from datacenter.engine_api import run_api_server
        api_thread = run_api_server(
            api_binding, host=args.api_host, port=args.api_port,
        )
        print(f"[Main] FastAPI debug API on http://{args.api_host}:{args.api_port}")
        print(f"[Main] WebSocket: ws://{args.api_host}:{args.api_port}/ws/snapshot")

    try:
        # 阻塞主线程，周期性检查引擎线程存活状态。
        # - daemon 标志只控制线程本身在主线程退出时是否被强 kill（用于嵌入式 import 场景），
        #   CLI 调用时主线程应无条件阻塞，否则 server 会随 main() 一起退出。
        # - 若任一引擎线程异常退出，主动触发关闭流程，避免 OPC UA 静默提供陈旧数据。
        while True:
            time.sleep(1)
            for engine_t, _, _, _, _ in threads:
                if not engine_t.is_alive():
                    raise RuntimeError(
                        f"引擎线程 {engine_t.name} 已异常退出，主动关闭所有实例"
                    )
    except KeyboardInterrupt:
        print("[Main] Interrupted by user")
    except RuntimeError as e:
        print(f"[Main] {e}")
    finally:
        # 优雅关闭：先发停止信号 + 停 OPC UA Server（释放端口），再等线程退出
        print("[Main] Shutting down...")
        for engine_t, opcua_t, server, stop_ev, _ in threads:
            stop_ev.set()
            server.stop()
        for engine_t, opcua_t, server, stop_ev, _ in threads:
            opcua_t.join(timeout=3.0)
            engine_t.join(timeout=3.0)
        # FastAPI 是 daemon 线程，进程退出时自动结束，无需显式 stop
        if api_thread is not None:
            api_thread.join(timeout=1.0)
        print("[Main] All instances stopped")
        sys.exit(0)


if __name__ == "__main__":
    main()
