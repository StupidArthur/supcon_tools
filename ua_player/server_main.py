# -*- coding: utf-8 -*-
"""
OPC UA Data Player 主逻辑：根据 CSV 数据创建变量节点，按相对时间循环播放。
namespace_index 固定为 1，仅支持 float 与 bool。
标记为 [w] 的节点客户端可写，不参与 CSV 播放，保持被写入的值。

已知问题处理：
  - asyncua 1.1.x 的 session_watchdog_loop 存在 Bug，
    会产生 "Task cannot await on itself" 的 RuntimeError。
    通过自定义 asyncio 异常处理器予以抑制，不影响主播放循环。
  - asyncua 对客户端写入的 SourceTimestamp 处理有问题，
    客户端写入后时间戳可能被设置为异常值（如1600年或客户端本地时间）。
    通过订阅监控可写节点，检测到写入后立即用当前时间戳覆盖。
"""

import asyncio
import logging
import traceback
from datetime import datetime, timezone
from typing import Any

from asyncua import Server, ua
from asyncua.server.monitored_item_service import MonitoredItemService

from data_loader import load_csv
from session_monitor import SessionMonitor, create_session_logger

# 抑制 asyncua 库的控制台输出，保持控制台只显示约定信息。
# 原因：未配置证书时会打印 "No encrypting policy / Endpoints other than open"；
# 客户端用失效的 session 发请求时会打印 "BadSessionIdInvalid" 的 service fault。
logging.getLogger("asyncua").setLevel(logging.CRITICAL)

# 命名空间配置
NAMESPACE_INDEX = 1

# 容器对象节点名称
CONTAINER_NODE_NAME = "MYDATA"

# 会话超时时间（毫秒），设置较长时间减少 watchdog 触发
# 默认值通常为 60000ms (1分钟)，此处设为 1 小时
SESSION_TIMEOUT_MS = 3_600_000

# 写入值失败时的最大连续重试次数（超过后跳过该行继续）
MAX_WRITE_RETRIES = 3

# 控制台固定信息
CONSOLE_LOAD_OK = "数据文件加载成功"
CONSOLE_LOAD_FAIL = "数据文件加载失败"
CONSOLE_SERVER_ADDR = "服务地址"
CONSOLE_START_PLAY = "开始播放"
CONSOLE_DESIGNED_BY = "designed by yzc"
CONSOLE_ROUND_START = "开始"
CONSOLE_ROUND_DURATION = "一轮播放需要的时间"
CONSOLE_FIXED_INTERVAL = "固定周期"


def _patch_datachange_trigger() -> None:
    """
    Monkey-patch asyncua 的 MonitoredItemService，将数据变化触发模式
    从默认的 StatusValue 改为 StatusValueTimestamp。

    目的：对于数据播放器场景，即使节点值不变，只要时间戳更新就应推送通知。
    默认的 StatusValue 模式下，值不变则不推送，导致客户端看到的时间戳停滞。

    注意：此 patch 会影响当前进程中所有 asyncua 服务端实例。
    """
    _original_datachange_callback = MonitoredItemService.datachange_callback

    async def _patched_datachange_callback(
        self: MonitoredItemService, handle: int, value: ua.DataValue, error=None
    ) -> None:
        if error:
            self.logger.info(
                "subscription %s: datachange callback called with handle '%s' and error '%s'",
                self, handle, error,
            )
            await self.trigger_statuschange(error)
            return

        mid = self._monitored_datachange[handle]
        mdata = self._monitored_items[mid]
        mdata.mvalue.set_current_datavalue(value)

        # 强制使用 StatusValueTimestamp 触发模式：时间戳变化也触发通知
        trigger = ua.DataChangeTrigger.StatusValueTimestamp
        deadband_flag_pass = self._is_data_changed(mdata.mvalue, trigger)
        if mdata.filter and mdata.filter.DeadbandType != ua.DeadbandType.None_:
            deadband_flag_pass = deadband_flag_pass and self._is_deadband_exceeded(
                mdata.mvalue, mdata.filter
            )

        if deadband_flag_pass:
            event = ua.MonitoredItemNotification()
            event.ClientHandle = mdata.client_handle
            event.Value = value
            await self.isub.enqueue_datachange_event(mid, event, mdata.queue_size)

    MonitoredItemService.datachange_callback = _patched_datachange_callback


def _install_asyncio_exception_handler() -> None:
    """
    安装自定义 asyncio 全局异常处理器。

    目的：抑制 asyncua 库内部 session_watchdog_loop 产生的
    "Task cannot await on itself" RuntimeError。
    该异常是 asyncua <=1.1.x 的已知 Bug，不影响服务端正常运行。
    对于其他未处理的异常，退回到默认处理器。
    """
    loop = asyncio.get_running_loop()
    original_handler = loop.get_exception_handler()

    def _handler(loop_: asyncio.AbstractEventLoop, context: dict) -> None:
        exception = context.get("exception")
        future_repr = str(context.get("future", ""))
        # 识别 asyncua watchdog 的已知 Bug
        if (
            isinstance(exception, RuntimeError)
            and "Task cannot await on itself" in str(exception)
            and "session_watchdog" in future_repr
        ):
            # 已知问题，静默忽略
            return
        # 其他异常交给原始处理器
        if original_handler is not None:
            original_handler(loop_, context)
        else:
            loop_.default_exception_handler(context)

    loop.set_exception_handler(_handler)


async def _safe_write_values(
    nodes: list[tuple[Any, str, int]],
    values: list[Any],
) -> None:
    """
    安全地向播放节点写入值，单个节点写入失败不影响其他节点。

    同一行的所有节点使用统一的时间戳（SourceTimestamp 和 ServerTimestamp），
    确保在 OPC UA 客户端中看到的各节点时间戳一致。

    :param nodes: [(node_obj, node_type, col_idx), ...] 播放节点列表
    :param values: 当前行的完整值列表
    """
    now = datetime.now(timezone.utc)
    for node, ntype, col_idx in nodes:
        if col_idx < len(values):
            val = values[col_idx]
            try:
                dv = ua.DataValue(
                    Value=ua.Variant(val),
                    SourceTimestamp=now,
                    ServerTimestamp=now,
                )
                await node.write_value(dv)
            except Exception:
                pass


async def run_server(
    data_file: str,
    port: int = 18950,
    host: str = "0.0.0.0",
    interval: float | None = None,
) -> None:
    """
    加载 CSV、创建 OPC UA 服务端并循环播放数据。

    :param data_file: CSV 数据文件路径
    :param port: 端口，默认 18950
    :param host: 监听地址，默认 0.0.0.0
    :param interval: 固定播放间隔（秒）。若指定，则每行数据以此间隔播放，
        忽略 CSV 中的时间戳。None 表示按时间戳差值播放。
    """
    use_fixed_interval = interval is not None
    node_specs, rows, deltas_seconds = load_csv(data_file, skip_timestamp=use_fixed_interval)
    if not rows:
        print(CONSOLE_LOAD_FAIL)
        return

    # 如果指定了固定间隔，用固定值覆盖所有 deltas
    if use_fixed_interval:
        deltas_seconds = [interval] * len(rows)

    print(CONSOLE_LOAD_OK)
    endpoint = f"opc.tcp://{host}:{port}/"
    print(f"{CONSOLE_SERVER_ADDR} {endpoint}")
    print(CONSOLE_START_PLAY)
    print(CONSOLE_DESIGNED_BY)

    server = Server()
    await server.init()
    server.set_endpoint(endpoint)

    # Patch：强制数据变化触发模式为 StatusValueTimestamp，确保时间戳更新时推送通知
    _patch_datachange_trigger()

    # 安装自定义异常处理器，抑制 asyncua watchdog 已知 Bug
    _install_asyncio_exception_handler()

    # 延长会话超时时间，减少 watchdog 误触发
    # asyncua 1.1.x 的超时通过 Server.default_timeout 设置（毫秒）
    server.default_timeout = SESSION_TIMEOUT_MS

    # 使用服务器默认命名空间 ns=1
    ns_idx = NAMESPACE_INDEX

    # 获取 Objects 节点
    objects = server.get_objects_node()

    # 创建容器对象节点 MYDATA
    container = await objects.add_object(
        ns_idx,
        CONTAINER_NODE_NAME,
        ua.ObjectIds.BaseObjectType
    )
    # 在容器下创建变量节点：ns=1;s=node_name，类型 float 或 bool
    # 播放节点：只读，参与 CSV 数据播放
    # 可写节点：客户端可写，不参与播放，保持被写入的值
    play_nodes: list[tuple[Any, str, int]] = []
    writable_nodes: list[tuple[Any, str, int]] = []

    for col_idx, (node_name, node_type, writable) in enumerate(node_specs):
        node_id = ua.NodeId(node_name, ns_idx)
        qname = ua.QualifiedName(node_name, ns_idx)
        if node_type == "bool":
            initial = False
        else:
            initial = 0.0
        n = await container.add_variable(node_id, qname, initial)
        if writable:
            await n.set_writable()
            writable_nodes.append((n, node_type, col_idx))
        else:
            play_nodes.append((n, node_type, col_idx))

    print(f"容器节点: {CONTAINER_NODE_NAME}, ns={ns_idx}, "
          f"播放节点: {len(play_nodes)}, 可写节点: {len(writable_nodes)}")

    # 可写节点设置初始值（取 CSV 第一行对应列的值）
    now = datetime.now(timezone.utc)
    if writable_nodes and rows:
        _, first_values = rows[0]
        for n, ntype, col_idx in writable_nodes:
            if col_idx < len(first_values):
                try:
                    dv = ua.DataValue(
                        Value=ua.Variant(first_values[col_idx]),
                        SourceTimestamp=now,
                        ServerTimestamp=now,
                    )
                    await n.write_value(dv)
                except Exception:
                    pass

    # 可写节点 setter：拦截客户端写入，用服务器时间戳替换客户端时间戳
    # 原因：asyncua 对客户端写入的 SourceTimestamp 处理有bug，会保留客户端发送的时间戳
    # 解决：在写入时拦截，用当前服务器时间替换客户端时间戳
    _writable_node_ids = {n.nodeid for n, _, _ in writable_nodes}

    def _writable_setter(node_data, attr, dv):
        """
        可写节点的 setter：保留客户端写入的值，时间戳强制使用服务器当前时间。

        UAExpert 等客户端写入时通常不带 SourceTimestamp（为 None），
        客户端读取后会显示为 1601-01-01 00:00:00 UTC，即东八区的 08:00:00。
        必须在 SourceTimestamp 为空时也写入当前时间。

        DataValue 为 frozen dataclass，需用 object.__setattr__ 原地修改，
        以便 asyncua 后续 datachange 回调推送的也是修正后的时间戳。
        value_setter 模式下还需自行写入 attval.value。
        """
        if dv is None:
            return
        now_ts = datetime.now(timezone.utc)
        object.__setattr__(dv, "SourceTimestamp", now_ts)
        object.__setattr__(dv, "ServerTimestamp", now_ts)
        object.__setattr__(dv, "SourcePicoseconds", None)
        object.__setattr__(dv, "ServerPicoseconds", None)
        node_data.attributes[attr].value = dv

    for n, _, _ in writable_nodes:
        server.set_attribute_value_setter(n.nodeid, _writable_setter)
    if writable_nodes:
        print(f"可写节点 setter 已设置（强制使用服务器时间戳）")

    # 一轮总时长（秒）
    round_duration_seconds = sum(deltas_seconds)

    # 创建会话监控日志（日志文件生成在程序同级目录）
    session_logger = create_session_logger()
    monitor = SessionMonitor(server, session_logger)

    async with server:
        # 启动会话监控后台任务
        monitor_task = asyncio.create_task(monitor.run())

        try:
            while True:
                try:
                    # 每一轮开始时提示
                    if use_fixed_interval:
                        print(
                            f"{CONSOLE_ROUND_START} "
                            f"{CONSOLE_FIXED_INTERVAL} {interval:.2f} 秒/行 "
                            f"{CONSOLE_ROUND_DURATION} {round_duration_seconds:.2f} 秒"
                        )
                    else:
                        now_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                        print(
                            f"{CONSOLE_ROUND_START} 当前时间 "
                            f"{now_str} "
                            f"{CONSOLE_ROUND_DURATION} {round_duration_seconds:.2f} 秒"
                        )
                    for i, (ts, values) in enumerate(rows):
                        await _safe_write_values(play_nodes, values)
                        if i < len(deltas_seconds):
                            await asyncio.sleep(deltas_seconds[i])
                except asyncio.CancelledError:
                    # 正常取消，退出循环
                    raise
                except Exception as exc:
                    # 一轮播放中出现未预期的异常，打印后继续下一轮
                    print(f"[警告] 本轮播放出现异常，将自动重新开始: {exc}")
                    traceback.print_exc()
                    await asyncio.sleep(1)  # 短暂等待后重试，避免忙循环
        finally:
            # 服务退出时停止会话监控
            monitor_task.cancel()
            try:
                await monitor_task
            except asyncio.CancelledError:
                pass
