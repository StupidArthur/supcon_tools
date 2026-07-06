#!/usr/bin/env python3
"""位号清理工具 (合并版): 软删 + 物理清回收站 + 诊断残留.

业务流程:
  soft     软删全部位号 (batchDeleteLogic → 进回收站, 可恢复)
  hard     物理清空回收站 (batchDelete → 不可恢复)
  all      软删全部 + 物理清回收站 (一条龙, 彻底清空)
  diagnose 诊断: 遍历所有 tagType 拉取全部位号, 列分布, 检测遗漏/残留

通用选项:
  --yes              真删 (默认 dry-run 仅预览)
  --batch-size N     分批删 + 折半探上限 (不传 = 单次全删)
  --page-size N      拉取每页条数 (默认 2000)

连接参数已写死, 直接跑; 换环境用环境变量 DATA_HUB_URL / _USER / _PASSWORD 覆盖.

用法:
  python scripts/tag_cleaner.py diagnose                       # 诊断 (看 tagType 分布)
  python scripts/tag_cleaner.py soft --yes --batch-size 1000   # 软删, 分批探上限
  python scripts/tag_cleaner.py hard --yes --batch-size 1000   # 物理清回收站
  python scripts/tag_cleaner.py all  --yes --batch-size 1000   # 一条龙彻底清空
"""
import os
import sys
import argparse
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from common_api import AlgAPI  # noqa: E402

# 默认连接参数 (直接写死, 跑 python 即可; 环境变量可覆盖)
DEFAULT_URL = "http://10.10.58.179:31501"
DEFAULT_USER = "admin"
DEFAULT_PASSWORD = "123456"
DEFAULT_TENANT = ""

TAG_TYPE_NAMES = {1: "一次位号", 4: "虚位号", 0: "type0", 2: "type2", 3: "type3", 5: "type5"}


def get_conn():
    url = os.environ.get("DATA_HUB_URL", DEFAULT_URL)
    user = os.environ.get("DATA_HUB_USER", DEFAULT_USER)
    pwd = os.environ.get("DATA_HUB_PASSWORD", DEFAULT_PASSWORD)
    tenant = os.environ.get("DATA_HUB_TENANT_ID", DEFAULT_TENANT)
    return url, user, pwd, tenant


def delete_in_batches(api, delete_fn, ids, batch_size=None, tag="删"):
    """通用分批删除. delete_fn = api.delete_tags / api.delete_tags_physical.

    batch_size=None → 单次全删; 否则分批, 遇失败折半重试, 记录能稳定通过的最大批次.
    """
    if not ids:
        print(f"  没有 id 需要{tag}除")
        return {"deleted": 0, "failed": 0, "max_ok_batch": None}

    def _one(batch, label=""):
        r = delete_fn(batch)
        ok = r["is_success"] and r["code"] == "00000"
        info = f"is_success={r['is_success']} code={r['code']} msg={r['msg']}"
        if label:
            print(f"  [{label}] {len(batch)} 个 → {info}")
        return ok, info

    if batch_size is None:
        ok, info = _one(ids, label="单次全删")
        return {"deleted": len(ids) if ok else 0, "failed": 0 if ok else len(ids),
                "max_ok_batch": None, "last_info": info}

    deleted, failed = 0, 0
    max_ok_batch = 0
    i, n = 0, len(ids)
    cur_bs = batch_size
    while i < n:
        batch = ids[i:i + cur_bs]
        ok, info = _one(batch, label=f"批 {i//batch_size + 1}")
        if ok:
            deleted += len(batch)
            max_ok_batch = max(max_ok_batch, len(batch))
            i += len(batch)
        else:
            if cur_bs > 1:
                print(f"    失败, 折半重试 (批次 {cur_bs} → {cur_bs // 2})")
                cur_bs = max(1, cur_bs // 2)
                continue
            else:
                print(f"    单个 id 也失败, 跳过: {batch} ({info})")
                failed += len(batch)
                i += len(batch)
                cur_bs = batch_size
    return {"deleted": deleted, "failed": failed, "max_ok_batch": max_ok_batch}


def collect_ids(tags):
    return [t["id"] for t in tags if t.get("id") is not None]


def show_distribution(tags):
    """打印 tagType / groupId 分布."""
    by_type = Counter(t.get("tagType") for t in tags)
    by_group = Counter(t.get("groupId") for t in tags)
    print(f"  总数: {len(tags)}")
    print("  tagType 分布:")
    for tt, n in sorted(by_type.items(), key=lambda x: (x[0] is None, x[0])):
        print(f"    tagType={tt} ({TAG_TYPE_NAMES.get(tt, '?')}): {n}")
    print("  groupId 分布 (前 10):")
    for gid, n in by_group.most_common(10):
        print(f"    groupId={gid}: {n}")


# ============================================================
# 子命令
# ============================================================

def cmd_soft(api, args):
    """软删全部位号 (batchDeleteLogic → 进回收站)."""
    print("[拉取] 遍历所有 tagType 拉取全部位号 ...")
    tags = api.get_all_tags_all_types(page_size=args.page_size)
    print(f"[拉取] 共 {len(tags)} 个位号")
    show_distribution(tags)
    ids = collect_ids(tags)
    if not ids:
        print("没有可删除的位号, 退出"); return
    sample = [t.get("tagName") for t in tags[:5]]
    print(f"[预览] 将软删 {len(ids)} 个, 例: {sample} ...")
    print(f"[模式] {'分批 ' + str(args.batch_size) + ' (探上限)' if args.batch_size else '单次全删'}")
    if not args.yes:
        print("[dry-run] 未实际删除. 加 --yes 真删."); return
    print("[删除] 开始软删 ...")
    r = delete_in_batches(api, api.delete_tags, ids, args.batch_size, "软删")
    print(f"[完成] 软删 {r['deleted']} 个, 失败 {r['failed']} 个")
    if r.get("max_ok_batch"):
        print(f"[探上限] 单次能稳定通过的最大批次 ≈ {r['max_ok_batch']}")


def cmd_hard(api, args):
    """物理清空回收站 (batchDelete → 不可恢复)."""
    print(f"[拉取] 拉取回收站位号 (groupId=1, 每页 {args.page_size}) ...")
    def _prog(page, n):
        print(f"  已拉第 {page} 页, 累计 {n} 个", flush=True)
    tags = api.get_all_recycle_tags(page_size=args.page_size, on_page=_prog)
    print(f"[拉取] 回收站共 {len(tags)} 个位号")
    ids = collect_ids(tags)
    if not ids:
        print("回收站为空, 退出"); return
    sample = [t.get("tagName") for t in tags[:5]]
    print(f"[预览] 将物理删除 {len(ids)} 个, 例: {sample} ...")
    print("[注意] 物理删除不可恢复!")
    print(f"[模式] {'分批 ' + str(args.batch_size) + ' (探上限)' if args.batch_size else '单次全删'}")
    if not args.yes:
        print("[dry-run] 未实际删除. 加 --yes 真删."); return
    print("[删除] 开始物理删除 ...")
    r = delete_in_batches(api, api.delete_tags_physical, ids, args.batch_size, "物理删")
    print(f"[完成] 物理删除 {r['deleted']} 个, 失败 {r['failed']} 个")
    if r.get("max_ok_batch"):
        print(f"[探上限] 单次能稳定通过的最大批次 ≈ {r['max_ok_batch']}")


def cmd_all(api, args):
    """一条龙: 软删全部 + 物理清回收站."""
    print("====== 阶段 1/2: 软删全部位号 ======")
    cmd_soft(api, args)
    print("\n====== 阶段 2/2: 物理清空回收站 ======")
    cmd_hard(api, args)
    print("\n[全部完成]")


def cmd_diagnose(api, args):
    """诊断: 列 tagType 分布, 检测遗漏/残留 (排查删不掉的位号)."""
    print("[诊断] 遍历所有 tagType 拉取全部位号 ...")
    tags = api.get_all_tags_all_types(page_size=args.page_size)
    print(f"[诊断] 共 {len(tags)} 个位号")
    show_distribution(tags)

    if not args.yes:
        print("\n[dry-run] 仅诊断未删除. 加 --yes 会: 软删全部 → 重拉 → 列残留 → 逐个重试.")
        return

    # 真删 + 残留排查
    ids = collect_ids(tags)
    print(f"\n[诊断] 软删全部 {len(ids)} 个 ...")
    r = delete_in_batches(api, api.delete_tags, ids, args.batch_size, "软删")
    print(f"[诊断] 软删 {r['deleted']} 个, 失败 {r['failed']} 个")

    print("[诊断] 重新拉取, 检查残留 ...")
    remain = api.get_all_tags_all_types(page_size=args.page_size)
    if not remain:
        print("[诊断] ✅ 无残留, 全部删除成功")
        return
    print(f"[诊断] ⚠ 仍有 {len(remain)} 个残留, 逐个重试并打印平台原因:")
    for t in remain:
        tid = t.get("id")
        rr = api.delete_tags([tid])
        print(f"  id={tid} tag={t.get('tagName')} tagType={t.get('tagType')} "
              f"groupId={t.get('groupId')} → code={rr['code']} msg={rr['msg']}")


# ============================================================
# 入口
# ============================================================

def main():
    ap = argparse.ArgumentParser(description="位号清理工具 (软删/物理清/诊断)",
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name, fn in [("soft", cmd_soft), ("hard", cmd_hard),
                     ("all", cmd_all), ("diagnose", cmd_diagnose)]:
        p = sub.add_parser(name, help=fn.__doc__.splitlines()[0] if fn.__doc__ else name)
        p.add_argument("--yes", action="store_true", help="真删 (默认 dry-run)")
        p.add_argument("--batch-size", type=int, default=None,
                       help="分批大小; 不传=单次全删; 传了=分批探上限")
        p.add_argument("--page-size", type=int, default=2000, help="拉取每页条数")
        p.set_defaults(func=fn)
    args = ap.parse_args()

    url, user, pwd, tenant = get_conn()
    api = AlgAPI(url)
    api.login(user, pwd, tenant)
    print(f"[login] OK, token 长度 {len(api.token)}\n")
    args.func(api, args)


if __name__ == "__main__":
    main()
