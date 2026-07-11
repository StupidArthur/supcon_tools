from api import AlgAPI, list_local_resources


def run_task(base_url: str = "http://10.16.11.1:31501"):
    print("=" * 60)
    print("同步本地算法文件与平台发布状态")
    print("=" * 60)

    # 1. 登录
    print("\n[步骤 1/7] 登录平台...")
    api = AlgAPI(base_url)
    login_res = api.login("api_client", "Supcon@1304")
    print(f"  登录成功: api_client")
    print(f"  token: {api.token[:40]}...")
    print(f"  expiresIn: {login_res.get('expiresIn')} 秒")

    # 2. 获取所有算法信息
    print("\n[步骤 2/7] 拉取平台全部算法信息...")
    api.get_all_algorithms()
    print(f"  平台共有 {len(api.algorithms)} 个算法，已缓存到实例")

    # 3. 检索本地文件
    print("\n[步骤 3/7] 扫描本地 resource 目录...")
    local_files = list_local_resources("resource")
    print(f"  发现 {len(local_files)} 个本地文件:")
    for f in local_files:
        print(f"    - {f}")

    # 4. 匹配本地文件与平台算法
    print("\n[步骤 4/7] 匹配本地文件与平台 sourcePath...")
    matched = api.match_local_files("resource")
    found = [item for item in matched if item["isExist"]]
    not_found = [item for item in matched if not item["isExist"]]
    print(f"  匹配完成: 命中 {len(found)} 个，未命中 {len(not_found)} 个")
    for item in found:
        release_str = "已发布" if item["isRelease"] == 1 else "未发布"
        print(f"    - {item['name']}  id={item['id']}  {release_str}")

    # 5. 筛选出已发布的算法
    print("\n[步骤 5/7] 筛选已发布的算法...")
    published = [item for item in found if item["isRelease"] == 1]
    print(f"  已发布 {len(published)} 个:")
    for item in published:
        print(f"    - {item['name']}  id={item['id']}")

    if not published:
        print("  无已发布的算法，跳过取消发布")

    # 6. 取消发布已发布的算法
    print("\n[步骤 6/7] 取消发布已发布的算法...")
    if not published:
        print("  无需取消发布")
    else:
        for item in published:
            print(f"  取消发布: {item['name']} (id={item['id']})...", end=" ")
            api.release_algorithm(
                algo_id=item["id"],
                is_release=0,
                cores=item["cores"],
                resource_type=item["resourceType"],
                num_replicas=item["numReplicas"],
            )
            print("[OK]")

    # 7. 上传并编辑所有命中的算法
    print("\n[步骤 7/7] 上传并编辑所有命中的算法...")
    if not found:
        print("  无命中的算法")
    else:
        for item in found:
            print(f"\n  处理: {item['name']}")
            print(f"    id={item['id']}, zhName={item.get('zhName')}")

            # 上传文件
            file_path = f"resource/{item['name']}"
            print(f"    上传文件: {file_path}", end=" ")
            upload_res = api.upload_file(file_path)
            print(f"[OK] -> {upload_res.get('message', '')}")

            # 编辑算法
            print(f"    编辑算法 (source_path={item['name']})...", end=" ")
            edit_res = api.edit_algorithm(source_path=item["name"])
            print(f"[OK] -> id={edit_res.get('id')}, zhName={edit_res.get('zhName')}, isRelease={edit_res.get('isRelease')}")

    # 8. 重新发布刚才取消发布的算法
    if published:
        print("\n[步骤 8/8] 重新发布刚才取消发布的算法...")
        for item in published:
            print(f"  发布: {item['name']} (id={item['id']})...", end=" ")
            api.release_algorithm(
                algo_id=item["id"],
                is_release=1,
                cores=item["cores"],
                resource_type=item["resourceType"],
                num_replicas=item["numReplicas"],
            )
            print("[OK]")

    print("\n" + "=" * 60)
    print("任务完成")
    print("=" * 60)
    print(f"  本地文件: {len(local_files)} 个")
    print(f"  命中平台: {len(found)} 个")
    print(f"  已发布待处理: {len(published)} 个")


if __name__ == "__main__":
    run_task()