"""CLI 入口：python -m ua_tpt_loop check [...]"""

from __future__ import annotations

import argparse
import logging
import sys
from typing import Sequence

from .checker import check_loop
from .mocker_yaml import MockerSpec
from .report import format_loop_report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="ua_tpt_loop",
        description="闭环检查：ua_mocker 节点 → tpt 数据源 → tpt 位号 → 数据流",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_check = sub.add_parser("check", help="跑完整 4 步闭环检查")
    p_check.add_argument("--mocker-yaml", help="ua_mocker 的 YAML 组态路径")
    p_check.add_argument("--mocker-url", help="直接给 OPC UA endpoint（替代 --mocker-yaml）")
    p_check.add_argument("--mocker-nodes", nargs="+", help="直接给节点名列表（配合 --mocker-url）")
    p_check.add_argument("--tpt-url", required=True, help="tpt base URL")
    p_check.add_argument("--tpt-user", required=True, help="tpt 登录账号")
    p_check.add_argument("--tpt-password", required=True, help="tpt 登录密码")
    p_check.add_argument("--tpt-tenant-id", default="", help="HTTPS 多租户时填，HTTP 单租户留空")
    p_check.add_argument("--sample-seconds", type=int, default=10, help="数据流验证窗口（默认 10s）")
    p_check.add_argument("--no-auto-register", action="store_true", help="只检查不补")
    p_check.add_argument("--skip-step1", action="store_true", help="跳过 OPC UA 检查（仅 tpt 端）")
    p_check.add_argument("--opcua-public-host", help="tpt 用来连 ua_mocker 的 host（覆盖 YAML 里的 host）")
    p_check.add_argument("--verbose", "-v", action="store_true", help="详细输出")
    p_check.add_argument("--log-level", default="INFO", help="日志级别")

    args = parser.parse_args(argv)

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    if args.cmd == "check":
        return _cmd_check(args)
    return 1  # pragma: no cover


def _cmd_check(args: argparse.Namespace) -> int:
    # 解析 mocker spec
    if args.mocker_yaml:
        spec = MockerSpec.from_yaml(args.mocker_yaml)
    elif args.mocker_url:
        if not args.mocker_nodes:
            print("错误: --mocker-url 必须配合 --mocker-nodes", file=sys.stderr)
            return 2
        from .mocker_yaml import MockerNode
        spec = MockerSpec(
            host=args.mocker_url.split("://", 1)[-1].split(":", 1)[0],
            port=int(args.mocker_url.rsplit(":", 1)[-1].rstrip("/").split("/", 1)[0]),
            cycle_ms=1000,
            namespace_index=1,
            endpoint=args.mocker_url,
            nodes=[
                MockerNode(
                    name=n, type="Double", count=1,
                    change=False, writable=False, default=None,
                    expected_node_ids=[n], tpt_data_type=11,
                )
                for n in args.mocker_nodes
            ],
        )
    else:
        print("错误: 必须给 --mocker-yaml 或 --mocker-url", file=sys.stderr)
        return 2

    result = check_loop(
        mocker=spec,
        tpt_url=args.tpt_url,
        tpt_user=args.tpt_user,
        tpt_password=args.tpt_password,
        tpt_tenant_id=args.tpt_tenant_id,
        sample_seconds=args.sample_seconds,
        auto_register=not args.no_auto_register,
        skip_step1=args.skip_step1,
        opcua_public_host=args.opcua_public_host,
    )

    print()
    print(format_loop_report(result, verbose=args.verbose))
    print()
    return 0 if result.is_closed else 1


if __name__ == "__main__":
    sys.exit(main())
