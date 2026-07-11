import csv
import time
import threading
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from common.api import AlgAPI

ip = "10.16.11.45"
username = "admin"
password = "123456"
BATCH_SIZE = 3

success_algorithms = []
failed_algorithms = []
skipped_algorithms = []
already_released_algorithms = []
lock = threading.Lock()


def load_algorithms_from_csv(csv_file):
    algorithms = []
    # 按优先级尝试常见中文编码：UTF-8 BOM / UTF-8 / GBK / GB18030
    last_err = None
    for enc in ("utf-8-sig", "utf-8", "gbk", "gb18030"):
        try:
            with open(csv_file, 'r', encoding=enc) as f:
                reader = csv.DictReader(f)
                for row in reader:
                    alg = (
                        row['算法名称'],
                        row['是否发布'],
                        float(row['核数']),
                        int(row['副本数']),
                        row['发布位置']
                    )
                    algorithms.append(alg)
            return algorithms
        except UnicodeDecodeError as e:
            last_err = e
            algorithms = []
            continue
    raise RuntimeError(f"无法识别 CSV 编码（已尝试 utf-8-sig/utf-8/gbk/gb18030），最后错误: {last_err}")


def login(ip=ip, username=username, password=password):
    url_login = f"http://{ip}:31501/tpt-admin/system-manager/umsAdmin/login"
    login_body = {"data": {"username": "admin", "password": "123456", "remember": False, "accountType": "0",
                           "generateCode": False}}

    try:
        response = requests.post(url=url_login, json=login_body, headers={'Content-Type': 'application/json'})
        token = response.json()['content']['token']
        result = {
            "key": 1,
            'content': token
        }
        return result

    except:
        result = {
            "key": 0,
            'content': response.text
        }
        return result


def getalg(token):
    url = f"http://{ip}:31501/alg-manager-web-v2.2-tpt/api/algorithm/page/1?extend=0"
    body = {"data": {"createTime_begin": "", "createTime_end": ""},
            "requestBase": {"page": "1-200", "sort": "-createTime"}}

    headers = {
        "Accept-Language": "zh-CN",
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}"
    }
    try:
        response = requests.post(url=url, json=body, headers=headers)
        algs = response.json()['content']['records']
        algs_name = []
        for alg in algs:
            alg_name = alg['zhName']
            alg_id = alg['id']
            alg_release = alg['isRelease']
            algid_name = (alg_id, alg_name.lower(), alg_release)
            algs_name.append(algid_name)

        return algs_name

    except Exception as e:
        print("获取算法列表失败")
        return []


def algdev(token, alginfo):
    url = f"http://{ip}:31501/alg-manager-web-v2.2-tpt/api/algorithm/release"
    if alginfo[5] == "GPU":
        mode = 2
    else:
        mode = 1
    body = {"id": alginfo[0], "isRelease": 1, "resourceType": mode, "cores": alginfo[3],
            "numReplicas": alginfo[4]}
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}"
    }
    try:
        response = requests.post(url=url, json=body, headers=headers)
        result = response.json()['code']
        if result == "00000":
            return True
        else:
            return False

    except Exception as e:
        return False


def process_single_algorithm(token, alg, algall, algallnames):
    algname = alg[0]
    if algname.lower() not in algallnames:
        return (algname, "不在系统", "failed", -1)
    else:
        for alg2 in algall:
            if algname.lower() == alg2[1]:
                current_release_status = alg2[2]
                alginfo = (alg2[0], alg[0], alg[1], alg[2], alg[3], alg[4], current_release_status)

                if alginfo[2] == "否":
                    return (algname, "设置为不发布", "skipped", current_release_status)

                if current_release_status == 1:
                    return (algname, "已发布", "already_released", current_release_status)

                if current_release_status == 0:
                    print(f"正在发布: {algname} (当前状态: 未发布)")
                    success = algdev(token, alginfo)
                    time.sleep(3)
                    if success:
                        print(f"发布成功: {algname}")
                        return (algname, "发布成功", "success", current_release_status)
                    else:
                        print(f"发布失败: {algname}")
                        return (algname, "发布失败", "failed", current_release_status)

    return (algname, "未知状态", "failed", -1)


def process_batch(token, batch, algall, algallnames):
    threads = []
    results = [None] * len(batch)

    def run_algorithm(index, alg):
        result = process_single_algorithm(token, alg, algall, algallnames)
        results[index] = result

    for i, alg in enumerate(batch):
        t = threading.Thread(target=run_algorithm, args=(i, alg))
        threads.append(t)
        t.start()

    for t in threads:
        t.join()

    return results


def checkalg_batch(token, algnamedevs):
    algall = getalg(token)
    if not algall:
        print("获取算法列表失败")
        return

    algallnames = []
    for alga in algall:
        algallnames.append(alga[1])

    algorithms_to_release = []
    for alg in algnamedevs:
        algname = alg[0]
        if algname.lower() not in algallnames:
            failed_algorithms.append((algname, "不在系统"))
        else:
            for alg2 in algall:
                if algname.lower() == alg2[1]:
                    current_release_status = alg2[2]
                    if alg[1] == "否":
                        skipped_algorithms.append((algname, current_release_status))
                    elif current_release_status == 1:
                        already_released_algorithms.append((algname, current_release_status))
                    elif current_release_status == 0:
                        algorithms_to_release.append(alg)
                    break

    total_to_release = len(algorithms_to_release)
    if total_to_release > 0:
        print(f"\n共有 {total_to_release} 个算法需要发布，将分 {(total_to_release + BATCH_SIZE - 1) // BATCH_SIZE} 批进行发布\n")

    for i in range(0, len(algorithms_to_release), BATCH_SIZE):
        batch = algorithms_to_release[i:i + BATCH_SIZE]
        batch_num = i // BATCH_SIZE + 1
        print(f"========== 第 {batch_num} 批发布开始 ==========")
        print(f"本批算法: {', '.join([alg[0] for alg in batch])}")
        print()

        results = process_batch(token, batch, algall, algallnames)

        for result in results:
            if result:
                algname = result[0]
                reason = result[1]
                status = result[2]
                release_status = result[3] if len(result) > 3 else -1

                if status == "success":
                    success_algorithms.append((algname, release_status))
                elif status == "failed":
                    failed_algorithms.append((algname, reason))

        print(f"========== 第 {batch_num} 批发布完成 ==========\n")


if __name__ == '__main__':
    csv_file = 'algorithms.csv'
    algnamedevs = load_algorithms_from_csv(csv_file)
    print(f"从CSV文件加载了 {len(algnamedevs)} 个算法配置")

    tokenold = login(ip, username, password)
    if tokenold['key'] == 0:
        print("登录失败")
        exit(1)
    token = tokenold['content']

    checkalg_batch(token, algnamedevs)

    print("\n" + "=" * 60)
    print("=== 发布成功的算法列表 ===")
    print("=" * 60)
    if success_algorithms:
        for alg_name, release_status in success_algorithms:
            print(f"✓ {alg_name} (发布前状态: {release_status})")
    else:
        print("无发布成功的算法")

    print("\n" + "=" * 60)
    print("=== 已发布的算法列表（无需重复发布）===")
    print("=" * 60)
    if already_released_algorithms:
        for alg_name, release_status in already_released_algorithms:
            print(f"○ {alg_name} (状态: {release_status})")
    else:
        print("无已发布的算法")

    print("\n" + "=" * 60)
    print("=== 跳过发布的算法列表（设置为不发布）===")
    print("=" * 60)
    if skipped_algorithms:
        for alg_name, release_status in skipped_algorithms:
            print(f"- {alg_name} (当前状态: {release_status})")
    else:
        print("无跳过发布的算法")

    print("\n" + "=" * 60)
    print("=== 发布失败的算法列表 ===")
    print("=" * 60)
    if failed_algorithms:
        for alg_name, reason in failed_algorithms:
            print(f"✗ {alg_name} - 原因: {reason}")
    else:
        print("无发布失败的算法")

    print("\n" + "=" * 60)
    print(f"统计结果:")
    print(f"  本次发布成功: {len(success_algorithms)} 个")
    print(f"  已发布（跳过）: {len(already_released_algorithms)} 个")
    print(f"  设置不发布: {len(skipped_algorithms)} 个")
    print(f"  发布失败: {len(failed_algorithms)} 个")
    print("=" * 60)
