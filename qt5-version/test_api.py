from api import AlgAPI

api = AlgAPI("http://10.16.11.46:31501")
api.login("api_client", "Supcon@1304")

# 获取并缓存所有算法
api.get_all_algorithms()
print(f"缓存算法数量: {len(api.algorithms)}")

# 用 source_path 查
info = api.get_by_source_path("valve_anomaly_detection_train.zip")
print(f"\n通过 source_path 查到: {info.get('id')}, {info.get('zhName')}, isRelease={info.get('isRelease')}")

# 用 id 查
info2 = api.get_by_id(1003056)
print(f"通过 id 查到: {info2.get('zhName')}")

# 用 source_path 直接编辑
print("\n=== 直接用 source_path 编辑 ===")
res = api.edit_algorithm(source_path="valve_anomaly_detection_train.zip")
print(f"edit OK: id={res.get('id')}, zhName={res.get('zhName')}, isRelease={res.get('isRelease')}")

# 用 algo_id 直接编辑
print("\n=== 直接用 algo_id 编辑 ===")
res2 = api.edit_algorithm(algo_id=1003056)
print(f"edit OK: id={res2.get('id')}, zhName={res2.get('zhName')}, isRelease={res2.get('isRelease')}")

# 匹配本地文件
print("\n=== 匹配本地文件 ===")
matched = api.match_local_files("resource")
for item in matched:
    print(f"name={item['name']}, isExist={item['isExist']}, id={item.get('id')}")