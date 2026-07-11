"""生产日志配置: exe 同级 logs/YYYY-MM-DD.log, 毫秒级, 双端输出.

按 production-logging-preference 规范:
  - 关键节点打 INFO/WARN/ERROR
  - 异常用 logger.exception, 自动带堆栈
  - FileHandler flush=True, 防崩溃丢最后一段
  - PyInstaller 打包后 logs/ 在 exe 同级 (sys.executable.parent)
  - 开发态 logs/ 在项目根 (__file__.parent)
"""
import logging
import sys
from datetime import datetime
from pathlib import Path

# 格式: 毫秒级时间戳 + 级别 + 模块名 + 消息
LOG_FORMAT = "%(asctime)s.%(msecs)03d [%(levelname)-5s] [%(name)s] %(message)s"
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"
_initialized = False
_log_file_path: Path | None = None


def get_log_dir() -> Path:
    """日志目录: PyInstaller 打包 -> exe 同级; 开发态 -> 项目根."""
    if getattr(sys, "frozen", False):
        base = Path(sys.executable).parent
    else:
        base = Path(__file__).parent
    log_dir = base / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir


def setup_logging(level: int = logging.INFO) -> logging.Logger:
    """初始化 root logger, 返回它.

    幂等: 重复调用不会重复添加 handler.
    文件: <log_dir>/YYYY-MM-DD.log, append 模式.
    控制台: 与文件用同一格式.
    """
    global _initialized, _log_file_path
    if _initialized:
        return logging.getLogger()

    log_dir = get_log_dir()
    log_file = log_dir / f"{datetime.now():%Y-%m-%d}.log"
    _log_file_path = log_file

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)  # 根收 DEBUG, handler 各自过滤

    # 文件 handler (DEBUG 全收)
    fh = logging.FileHandler(log_file, encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT))
    fh.flush = lambda: logging.FileHandler.flush(fh)  # 保留引用, 给 shutdown 用
    root.addHandler(fh)

    # 控制台 handler (默认 INFO)
    ch = logging.StreamHandler()
    ch.setLevel(level)
    ch.setFormatter(logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT))
    root.addHandler(ch)

    _initialized = True

    logging.getLogger(__name__).info(
        "logging initialized, file=%s", log_file
    )
    return root


def flush_all() -> None:
    """所有 handler flush, 崩溃/退出前调, 防丢最后一段."""
    for h in logging.getLogger().handlers:
        try:
            h.flush()
        except Exception:
            pass


def get_log_file_path() -> Path | None:
    return _log_file_path
