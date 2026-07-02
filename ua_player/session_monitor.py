# -*- coding: utf-8 -*-
"""
OPC UA 客户端会话监控模块。

定期轮询服务器活跃会话列表，检测客户端的连接与断开事件，
记录到日志文件，便于排查频繁断联的客户端。

日志内容包括：
  - [连接] 客户端名称、会话ID、累计连接次数
  - [断开] 客户端名称、会话ID、本次连接时长、累计断开次数
"""

import asyncio
import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

# ========== 可调参数 ==========

# 轮询间隔（秒）：每隔多久检查一次会话列表
MONITOR_POLL_INTERVAL_S = 5.0

# 日志文件名前缀
SESSION_LOG_PREFIX = "ua_player_sessions"

# ========== 常量 ==========

# 日志格式
LOG_DATETIME_FMT = "%Y-%m-%d %H:%M:%S"
LOG_LINE_FMT = "%(asctime)s | %(message)s"

# 分隔线
LOG_SEPARATOR = "=" * 60


def _get_program_directory() -> Path:
    """
    获取运行程序所在目录。

    支持 PyInstaller 打包后的 exe 和普通 Python 脚本两种场景。
    """
    if getattr(sys, "frozen", False):
        # PyInstaller 打包后的 exe
        return Path(sys.executable).parent
    else:
        # 普通 Python 脚本：取入口脚本所在目录
        return Path(sys.argv[0]).resolve().parent


def create_session_logger(log_dir: str | Path | None = None) -> logging.Logger:
    """
    创建并配置会话事件日志记录器。

    日志文件名带启动时间戳，格式：ua_player_sessions_YYYYMMDD_HHMMSS.log

    :param log_dir: 日志文件存放目录。None 则使用程序所在目录。
    :return: 配置好的 Logger 实例
    """
    logger = logging.getLogger("ua_player.sessions")
    logger.setLevel(logging.INFO)

    # 避免重复添加 handler（如多次调用）
    if logger.handlers:
        return logger

    if log_dir is None:
        log_dir = _get_program_directory()
    log_dir = Path(log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_filename = f"{SESSION_LOG_PREFIX}_{timestamp}.log"
    log_path = log_dir / log_filename

    handler = logging.FileHandler(str(log_path), encoding="utf-8")
    formatter = logging.Formatter(LOG_LINE_FMT, datefmt=LOG_DATETIME_FMT)
    handler.setFormatter(formatter)
    logger.addHandler(handler)

    # 不向上传播，避免被 root logger 或 asyncua logger 设置影响
    logger.propagate = False

    return logger


def _format_duration(seconds: float) -> str:
    """
    将秒数格式化为可读的时长字符串。

    :param seconds: 时长（秒）
    :return: 如 "45秒"、"3分12秒"、"2时15分"
    """
    if seconds < 60:
        return f"{seconds:.0f}秒"
    elif seconds < 3600:
        m = int(seconds // 60)
        s = int(seconds % 60)
        return f"{m}分{s}秒"
    else:
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        return f"{h}时{m}分"


class SessionMonitor:
    """
    OPC UA 客户端会话监控器。

    通过定期轮询服务器的活跃会话列表，对比前后两次快照，
    检测新增会话（客户端连接）和消失的会话（客户端断开），
    并将事件写入日志文件。

    同时维护每个客户端的累计连接/断开次数，帮助识别频繁断联的客户端。
    """

    def __init__(
        self,
        server: Any,
        logger: logging.Logger,
        poll_interval: float = MONITOR_POLL_INTERVAL_S,
    ):
        """
        :param server: asyncua.Server 实例
        :param logger: 日志记录器（由 create_session_logger 创建）
        :param poll_interval: 轮询间隔（秒）
        """
        self._server = server
        self._logger = logger
        self._poll_interval = poll_interval

        # 已知会话：session_id_str -> {"name": str, "peer": str, "connect_time": datetime}
        self._known_sessions: dict[str, dict] = {}

        # 统计：客户端标识(name|peer) -> 累计连接/断开次数
        self._connect_counts: dict[str, int] = {}
        self._disconnect_counts: dict[str, int] = {}

    def _get_active_sessions(self) -> dict[str, dict]:
        """
        从服务器内部获取当前活跃的会话信息。

        asyncua 1.1.x 的会话存储在 BinaryServer.clients 列表中，
        每个 client 是 OPCUAProtocol 实例，其 processor.session 为会话对象。

        :return: {唯一标识: {"name": str, "peer": str}, ...}
        """
        sessions = {}
        try:
            bserver = self._server.bserver
            if bserver is None:
                return sessions
            for client in bserver.clients:
                processor = getattr(client, "processor", None)
                if processor is None:
                    continue
                session = getattr(processor, "session", None)
                if session is None:
                    continue
                # 用 session 对象的 id 作为唯一标识（每个会话实例不同）
                sid_str = str(id(session))
                name = getattr(session, "name", None) or "unknown"
                peer = str(getattr(client, "peer_name", "unknown"))
                sessions[sid_str] = {"name": name, "peer": peer}
        except Exception:
            pass
        return sessions

    async def run(self) -> None:
        """
        主监控循环。

        持续运行直到被取消（CancelledError），
        每个轮询周期检测一次会话变化。
        """
        self._logger.info(LOG_SEPARATOR)
        self._logger.info("会话监控启动 | 轮询间隔=%.1f秒", self._poll_interval)
        self._logger.info(LOG_SEPARATOR)

        while True:
            try:
                current = self._get_active_sessions()
                current_ids = set(current.keys())
                known_ids = set(self._known_sessions.keys())

                # --- 检测新连接 ---
                new_ids = current_ids - known_ids
                for sid in new_ids:
                    info = current[sid]
                    name = info["name"]
                    peer = info.get("peer", "unknown")
                    client_key = f"{name}|{peer}"
                    self._connect_counts[client_key] = self._connect_counts.get(client_key, 0) + 1
                    # 记录到已知会话
                    self._known_sessions[sid] = {
                        "name": name,
                        "peer": peer,
                        "connect_time": datetime.now(),
                    }
                    self._logger.info(
                        "[连接] 客户端=%s | 地址=%s | 累计连接=%d次",
                        name,
                        peer,
                        self._connect_counts[client_key],
                    )

                # --- 检测断开 ---
                gone_ids = known_ids - current_ids
                for sid in gone_ids:
                    info = self._known_sessions.pop(sid)
                    name = info["name"]
                    peer = info.get("peer", "unknown")
                    client_key = f"{name}|{peer}"
                    connect_time = info.get("connect_time")
                    self._disconnect_counts[client_key] = (
                        self._disconnect_counts.get(client_key, 0) + 1
                    )

                    # 计算本次连接时长
                    duration_part = ""
                    if connect_time:
                        duration_s = (datetime.now() - connect_time).total_seconds()
                        duration_part = f" | 连接时长={_format_duration(duration_s)}"

                    self._logger.info(
                        "[断开] 客户端=%s | 地址=%s%s | 累计断开=%d次",
                        name,
                        peer,
                        duration_part,
                        self._disconnect_counts[client_key],
                    )

            except asyncio.CancelledError:
                raise
            except Exception:
                # 监控本身不应影响主服务，静默忽略
                pass

            await asyncio.sleep(self._poll_interval)
