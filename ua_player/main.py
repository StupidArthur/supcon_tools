# -*- coding: utf-8 -*-
"""
OPC UA Data Player 入口：通过函数参数传入数据文件路径、端口与播放间隔，
__main__ 中解析命令行后调用。
"""

import argparse
import asyncio
import sys

from server_main import run_server

DEFAULT_PORT = 18950
DEFAULT_HOST = "0.0.0.0"


def main(
    data_file: str,
    port: int = DEFAULT_PORT,
    interval: float | None = None,
) -> None:
    """
    启动 OPC UA Data Player。

    :param data_file: CSV 数据文件路径
    :param port: 服务端口，默认 18950
    :param interval: 固定播放间隔（秒）。若指定，则忽略 CSV 中的时间戳，
        每行数据以此间隔播放。None 表示按时间戳差值播放。
    """
    asyncio.run(run_server(data_file, port=port, host=DEFAULT_HOST, interval=interval))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="OPC UA Data File Player")
    parser.add_argument("data_file", help="CSV 数据文件路径")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"服务端口，默认 {DEFAULT_PORT}")
    parser.add_argument(
        "--interval", type=float, default=None,
        help="固定播放间隔（秒），如 0.5 表示每 0.5 秒播放一行。指定后忽略 CSV 中的时间戳",
    )
    args = parser.parse_args()
    try:
        main(data_file=args.data_file, port=args.port, interval=args.interval)
    except KeyboardInterrupt:
        pass
