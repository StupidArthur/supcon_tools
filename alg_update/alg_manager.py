"""
alg_manager - 算法管理模块（非 GUI）
为 FastAPI Web 后端提供算法管理能力

典型使用流程:
    manager = AlgManager(base_url="http://10.16.11.1:31501")
    manager.connect()
    manager.fetch_algorithms()
    manager.load_template("publish_list.csv")
    diff = manager.compare()

    # 释放待发布列表
    result = manager.release_pending(concurrent=5)

    # 取消释放误发布列表
    result = manager.unrelease_misreleased(concurrent=5)
"""

import csv
import threading
from dataclasses import dataclass, field
from datetime import datetime
from typing import Callable, List, Dict, Optional, Any

from common.api import AlgAPI


@dataclass
class AlgoEntry:
    """
    单个算法的完整信息。

    包含算法在模板和平台两端的完整信息，用于对比差异和执行发布操作。

    Attributes:
        name: 算法名称。
        in_template: 模板中是否存在。
        in_platform: 平台上是否存在。
        template_release: 模板中是否设置为发布（"是" -> True，其他 -> False）。
        platform_released: 平台上是否已发布（isRelease == 1 -> True）。
        platform_cores: 平台记录的核数。
        platform_num_replicas: 平台记录的副本数。
        platform_resource_type: 平台记录的资源类型（1=CPU，2=GPU）。
        template_cores: 模板中配置的核数。
        template_num_replicas: 模板中配置的副本数。
        template_resource_type: 模板中配置的资源类型（GPU -> 2，其他 -> 1）。
        cores_diff: 模板与平台的核数是否不一致。
        replicas_diff: 模板与平台的副本数是否不一致。
        resource_type_diff: 模板与平台的资源类型是否不一致。

    Example:
        entry = AlgoEntry(name="deepSearch")
        entry.in_template = True
        entry.in_platform = True
        entry.template_release = True
        entry.platform_released = False
        entry.template_cores = 1.0
        entry.platform_cores = 2.0
        entry.cores_diff = True
    """
    name: str

    # 存在性
    in_template: bool = False
    in_platform: bool = False

    # 发布状态
    template_release: bool = False
    platform_released: bool = False

    # 平台参数
    platform_cores: float = 0
    platform_num_replicas: int = 0
    platform_resource_type: int = 0  # 1=CPU, 2=GPU

    # 模板参数
    template_cores: float = 0
    template_num_replicas: int = 0
    template_resource_type: int = 0  # 1=CPU, 2=GPU

    # 差异标记
    cores_diff: bool = False
    replicas_diff: bool = False
    resource_type_diff: bool = False

    def to_dict(self) -> Dict[str, Any]:
        """
        将 AlgoEntry 实例转换为字典格式。

        Returns:
            包含所有字段的字典。
        """
        return {
            "name": self.name,
            "in_template": self.in_template,
            "in_platform": self.in_platform,
            "template_release": self.template_release,
            "platform_released": self.platform_released,
            "platform_cores": self.platform_cores,
            "platform_num_replicas": self.platform_num_replicas,
            "platform_resource_type": self.platform_resource_type,
            "template_cores": self.template_cores,
            "template_num_replicas": self.template_num_replicas,
            "template_resource_type": self.template_resource_type,
            "cores_diff": self.cores_diff,
            "replicas_diff": self.replicas_diff,
            "resource_type_diff": self.resource_type_diff,
        }


@dataclass
class DiffResult:
    """
    差异对比结果。

    包含全量算法信息表以及从多个关键维度筛选出的算法列表。

    Attributes:
        all_algos: 模板与平台的算法并集（全量表），每项为 AlgoEntry。
        to_release: 待释放列表——模板中设置为发布、但平台中尚未发布的算法。
        should_unrelease: 误释放列表——模板中设置为不发布、但平台中已发布的算法。
        only_in_template: 仅在模板中存在的算法名称列表。
        only_in_platform: 仅在平台中存在的算法名称列表。

    Example:
        diff = manager.compare()
        for entry in diff.all_algos:
            print(entry.name, entry.cores_diff)

        print(f"待释放: {len(diff.to_release)}")
        print(f"误释放: {len(diff.should_unrelease)}")
    """
    all_algos: List[AlgoEntry] = field(default_factory=list)

    # 待释放列表（模板要发布 && 平台未发布）
    to_release: List[AlgoEntry] = field(default_factory=list)

    # 误释放列表（模板不发布 && 平台已发布）
    should_unrelease: List[AlgoEntry] = field(default_factory=list)

    # 总量差异
    only_in_template: List[str] = field(default_factory=list)
    only_in_platform: List[str] = field(default_factory=list)

    def summary(self) -> Dict[str, int]:
        """
        返回各分类的计数统计。

        Returns:
            包含 total、to_release_count、should_unrelease_count、
            only_in_template_count、only_in_platform_count 的字典。
        """
        return {
            "total": len(self.all_algos),
            "to_release_count": len(self.to_release),
            "should_unrelease_count": len(self.should_unrelease),
            "only_in_template_count": len(self.only_in_template),
            "only_in_platform_count": len(self.only_in_platform),
        }


@dataclass
class ReleaseResult:
    """
    单次释放（或取消释放）操作的结果。

    Attributes:
        algo_id: 算法的平台 ID。
        name: 算法名称。
        success: 操作是否成功。
        message: 成功时为 "释放成功" 或 "取消释放成功"，失败时为错误信息。
        timestamp: 操作执行的时间戳。

    Example:
        result = ReleaseResult(
            algo_id=1003056,
            name="deepSearch",
            success=True,
            message="释放成功",
        )
    """
    algo_id: int
    name: str
    success: bool
    message: str
    timestamp: datetime = field(default_factory=datetime.now)

    def to_dict(self) -> Dict[str, Any]:
        """
        将 ReleaseResult 实例转换为字典格式。

        Returns:
            包含 algo_id、name、success、message、timestamp 的字典。
        """
        return {
            "algo_id": self.algo_id,
            "name": self.name,
            "success": self.success,
            "message": self.message,
            "timestamp": self.timestamp.isoformat(),
        }


class AlgManager:
    """
    算法管理器——非 GUI 版本的算法发布管理模块。

    为 FastAPI Web 后端提供算法管理能力，支持：
    - 连接平台并登录
    - 从平台拉取算法列表
    - 加载标准 CSV 发布模板
    - 对比模板与平台的差异，产出全量算法信息表
    - 批量释放（发布）待发布算法
    - 批量取消释放误发布算法

    典型使用流程::

        manager = AlgManager(base_url="http://10.16.11.1:31501")
        manager.connect()
        manager.fetch_algorithms()
        manager.load_template("publish_list.csv")
        diff = manager.compare()

        # 发布待发布
        result = manager.release_pending(concurrent=5)

        # 取消发布误发布
        result = manager.unrelease_misreleased(concurrent=5)

    Attributes:
        base_url: 平台 API 基础 URL。
        username: 登录用户名。
        password: 登录密码。
        api: AlgAPI 实例，connect() 后初始化。
        platform_algos: 平台算法列表（Dict），fetch_algorithms() 后填充。
        platform_map: 平台算法名称到完整记录的映射（name.lower() -> Dict），
            fetch_algorithms() 后填充。
        csv_records: CSV 模板记录列表，load_template() 后填充。
        diff_result: 差异对比结果，compare() 后填充。

    Args:
        base_url: 平台 API 基础 URL，如 "http://10.16.11.1:31501"。
        username: 登录用户名，默认为 "api_client"。
        password: 登录密码，默认为 "Supcon@1304"。
    """

    def __init__(
        self,
        base_url: str = "http://10.16.11.45:31501",
        username: str = "admin",
        password: str = "123456",
    ):
        self.base_url = base_url
        self.username = username
        self.password = password
        self.api: Optional[AlgAPI] = None

        self.platform_algos: List[Dict] = []
        self.platform_map: Dict[str, Dict] = {}  # name.lower() -> algo
        self.csv_records: List[Dict] = []
        self.diff_result: Optional[DiffResult] = None

    def connect(self) -> bool:
        """
        连接平台并登录。

        初始化 AlgAPI 实例并使用预设凭据登录。登录成功后会持有 token，
        后续请求自动携带认证信息。

        Returns:
            True 表示连接成功。

        Raises:
            Exception: 登录失败时抛出异常。

        Example:
            manager.connect()
        """
        self.api = AlgAPI(self.base_url)
        self.api.login(self.username, self.password)
        return True

    def fetch_algorithms(self) -> List[Dict]:
        """
        获取平台上所有算法并缓存到实例属性。

        自动翻页拉取完整的算法列表，存入 platform_algos 和 platform_map。

        Returns:
            平台算法完整记录列表（List[Dict]），每项为平台返回的算法对象。

        Raises:
            RuntimeError: 未连接平台时抛出。

        Example:
            algos = manager.fetch_algorithms()
            print(f"平台共有 {len(algos)} 个算法")
        """
        if not self.api:
            raise RuntimeError("未连接平台，请先调用 connect()")
        self.platform_algos = self.api.get_all_algorithms()
        self.platform_map = {
            a.get("zhName", "").lower(): a
            for a in self.platform_algos
            if a.get("zhName")
        }
        return self.platform_algos

    def load_template(self, csv_path: str) -> List[Dict]:
        """
        加载本地 CSV 标准发布模板。

        CSV 文件格式（列名必须精确匹配）::

            算法名称,是否发布,核数,副本数,发布位置
            deepSearch,是,1,1,CPU
            valve_anomaly_detection_train,是,2,1,GPU

        Args:
            csv_path: CSV 文件路径，支持相对路径和绝对路径。

        Returns:
            CSV 记录列表（List[Dict]），每项为一行数据的字典。

        Raises:
            FileNotFoundError: CSV 文件不存在时抛出。
            Exception: CSV 解析失败时抛出。

        Example:
            records = manager.load_template("publish_list.csv")
            print(f"CSV 共有 {len(records)} 条记录")
        """
        with open(csv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            self.csv_records = list(reader)
        return self.csv_records

    def compare(self) -> DiffResult:
        """
        对比 CSV 模板与平台数据的差异，构建全量算法信息表。

        以算法名称（不区分大小写）为基准，计算模板和平台两端的并集。
        对每条算法记录填充存在性、发布状态、参数及差异标记。
        并将算法按以下维度分类：
        - 待释放（模板要发布 && 平台未发布）
        - 误释放（模板不发布 && 平台已发布）
        - 仅模板有
        - 仅平台有

        Returns:
            DiffResult 对象，包含全量表和各分类列表。

        Raises:
            RuntimeError: 平台算法未加载时抛出，需先调用 fetch_algorithms()。

        Example:
            diff = manager.compare()

            # 全量表
            for entry in diff.all_algos:
                print(entry.name, entry.cores_diff)

            # 统计
            print(diff.summary())

            # 待释放列表
            for entry in diff.to_release:
                print(entry.name, entry.template_cores)
        """
        if not self.platform_map:
            raise RuntimeError("平台算法未加载，请先调用 fetch_algorithms()")

        all_names: set = set()
        for row in self.csv_records:
            name = row.get("算法名称", "").strip()
            if name:
                all_names.add(name.lower())

        for name in self.platform_map.keys():
            all_names.add(name)

        all_algos: List[AlgoEntry] = []
        to_release: List[AlgoEntry] = []
        should_unrelease: List[AlgoEntry] = []
        only_in_template: List[str] = []
        only_in_platform: List[str] = []

        for name in all_names:
            entry = AlgoEntry(name=name)

            # 检查模板中是否存在
            template_row = None
            for row in self.csv_records:
                if row.get("算法名称", "").strip().lower() == name:
                    template_row = row
                    break
            if template_row:
                entry.in_template = True
                entry.template_release = template_row.get("是否发布", "否").strip() == "是"
                csv_cores = template_row.get("核数", "").strip()
                csv_replicas = template_row.get("副本数", "").strip()
                csv_position = template_row.get("发布位置", "").strip()
                entry.template_cores = float(csv_cores) if csv_cores else 0
                entry.template_num_replicas = int(csv_replicas) if csv_replicas else 0
                entry.template_resource_type = 2 if csv_position == "GPU" else 1

            # 检查平台中是否存在
            platform_algo = self.platform_map.get(name)
            if platform_algo:
                entry.in_platform = True
                entry.platform_released = platform_algo.get("isRelease", 0) == 1
                entry.platform_cores = float(platform_algo.get("cores", 0))
                entry.platform_num_replicas = int(platform_algo.get("numReplicas", 0))
                entry.platform_resource_type = int(platform_algo.get("resourceType", 0))

            # 计算差异
            if entry.in_template and entry.in_platform:
                if entry.template_cores != entry.platform_cores:
                    entry.cores_diff = True
                if entry.template_num_replicas != entry.platform_num_replicas:
                    entry.replicas_diff = True
                if entry.template_resource_type != entry.platform_resource_type:
                    entry.resource_type_diff = True

            all_algos.append(entry)

            # 分类到 to_release / should_unrelease
            if entry.in_template and not entry.in_platform:
                only_in_template.append(entry.name)
            elif entry.in_platform and not entry.in_template:
                only_in_platform.append(entry.name)
            elif entry.in_template and entry.in_platform:
                if entry.template_release and not entry.platform_released:
                    to_release.append(entry)
                elif not entry.template_release and entry.platform_released:
                    should_unrelease.append(entry)

        self.diff_result = DiffResult(
            all_algos=all_algos,
            to_release=to_release,
            should_unrelease=should_unrelease,
            only_in_template=only_in_template,
            only_in_platform=only_in_platform,
        )
        return self.diff_result

    def _release_single(self, entry: AlgoEntry, is_release: int = 1) -> ReleaseResult:
        """
        内部方法：释放或取消释放单个算法。

        Args:
            entry: AlgoEntry 实例，从中获取算法名称和发布参数。
            is_release: 1=释放（发布），0=取消释放。

        Returns:
            ReleaseResult 对象。
        """
        if not self.api:
            raise RuntimeError("未连接平台，请先调用 connect()")

        algo_id = self.platform_map.get(entry.name.lower(), {}).get("id", 0)
        if not algo_id:
            return ReleaseResult(
                algo_id=0,
                name=entry.name,
                success=False,
                message="平台算法 ID 未找到",
            )

        try:
            self.api.release_algorithm(
                algo_id=algo_id,
                is_release=is_release,
                cores=int(entry.template_cores if is_release == 1 else entry.platform_cores),
                resource_type=entry.template_resource_type if is_release == 1 else entry.platform_resource_type,
                num_replicas=int(entry.template_num_replicas if is_release == 1 else entry.platform_num_replicas),
            )
            return ReleaseResult(
                algo_id=algo_id,
                name=entry.name,
                success=True,
                message="释放成功" if is_release == 1 else "取消释放成功",
            )
        except Exception as e:
            return ReleaseResult(
                algo_id=algo_id,
                name=entry.name,
                success=False,
                message=str(e),
            )

    def release_pending(
        self,
        concurrent: int = 3,
        progress_callback: Optional[Callable[[int, int, AlgoEntry, ReleaseResult], None]] = None,
    ) -> Dict[str, Any]:
        """
        释放（发布）待发布列表中的算法。

        从 compare() 产生的 diff_result.to_release 获取待发布算法列表，
        释放时使用模板中配置的参数（cores、numReplicas、resourceType）。

        Args:
            concurrent: 并发线程数，默认为 3。
            progress_callback: 进度回调函数，签名为
                ``callback(processed: int, total: int, entry: AlgoEntry, result: ReleaseResult)``。
                每完成一个算法调用一次。

        Returns:
            包含以下键的字典：
            - ``total``: 总数
            - ``success_count``: 成功数
            - ``fail_count``: 失败数
            - ``failed_items``: 失败的 AlgoEntry 列表
            - ``results``: ReleaseResult 列表

        Raises:
            RuntimeError: 未调用 compare() 时抛出。

        Example:
            def on_progress(p, t, entry, result):
                print(f"[{p}/{t}] {entry.name}: {'✓' if result.success else '✗'}")

            result = manager.release_pending(concurrent=5, progress_callback=on_progress)
            print(f"成功 {result['success_count']}, 失败 {result['fail_count']}")
        """
        if not self.diff_result:
            raise RuntimeError("请先调用 compare()")

        items = self.diff_result.to_release
        return self._do_release_batch(items, concurrent, progress_callback, is_release=1)

    def unrelease_misreleased(
        self,
        concurrent: int = 3,
        progress_callback: Optional[Callable[[int, int, AlgoEntry, ReleaseResult], None]] = None,
    ) -> Dict[str, Any]:
        """
        取消释放（取消发布）误发布列表中的算法。

        从 compare() 产生的 diff_result.should_unrelease 获取误发布算法列表，
        取消释放时使用平台当前参数。

        Args:
            concurrent: 并发线程数，默认为 3。
            progress_callback: 进度回调函数，签名为
                ``callback(processed: int, total: int, entry: AlgoEntry, result: ReleaseResult)``。
                每完成一个算法调用一次。

        Returns:
            包含以下键的字典：
            - ``total``: 总数
            - ``success_count``: 成功数
            - ``fail_count``: 失败数
            - ``failed_items``: 失败的 AlgoEntry 列表
            - ``results``: ReleaseResult 列表

        Raises:
            RuntimeError: 未调用 compare() 时抛出。

        Example:
            result = manager.unrelease_misreleased(concurrent=5)
            print(f"成功 {result['success_count']}, 失败 {result['fail_count']}")
        """
        if not self.diff_result:
            raise RuntimeError("请先调用 compare()")

        items = self.diff_result.should_unrelease
        return self._do_release_batch(items, concurrent, progress_callback, is_release=0)

    def _do_release_batch(
        self,
        items: List[AlgoEntry],
        concurrent: int,
        progress_callback: Optional[Callable],
        is_release: int,
    ) -> Dict[str, Any]:
        """
        内部方法：批量并发执行释放或取消释放。

        Args:
            items: 待处理的 AlgoEntry 列表。
            concurrent: 并发数。
            progress_callback: 进度回调。
            is_release: 1=释放，0=取消释放。

        Returns:
            同 release_pending() 返回值结构。
        """
        total = len(items)
        results: List[ReleaseResult] = []
        lock = threading.Lock()

        def release_one(entry: AlgoEntry) -> ReleaseResult:
            result = self._release_single(entry, is_release=is_release)
            with lock:
                results.append(result)
                if progress_callback:
                    progress_callback(len(results), total, entry, result)
            return result

        threads: List[threading.Thread] = []
        for entry in items:
            t = threading.Thread(target=release_one, args=(entry,))
            threads.append(t)
            t.start()

            if len(threads) >= concurrent:
                for th in threads:
                    th.join()
                threads = []

        for th in threads:
            th.join()

        failed_items = [r.name for r in results if not r.success]
        return {
            "total": total,
            "success_count": total - len(failed_items),
            "fail_count": len(failed_items),
            "failed_items": [self._find_algo_entry(name) for name in failed_items],
            "results": results,
        }

    def _find_algo_entry(self, name: str) -> Optional[AlgoEntry]:
        """
        内部方法：根据算法名称在 all_algos 中查找对应的 AlgoEntry。

        Args:
            name: 算法名称（大小写不敏感）。

        Returns:
            找到返回 AlgoEntry，否则返回 None。
        """
        if not self.diff_result:
            return None
        for entry in self.diff_result.all_algos:
            if entry.name.lower() == name.lower():
                return entry
        return None


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("用法: python alg_manager.py <csv_path> [base_url]")
        sys.exit(1)

    csv_path = sys.argv[1]
    base_url = sys.argv[2] if len(sys.argv) > 2 else "http://10.16.11.45:31501"

    manager = AlgManager(base_url)

    print("连接平台...")
    manager.connect()

    print("获取平台算法...")
    manager.fetch_algorithms()
    print(f"  平台共有 {len(manager.platform_algos)} 个算法")

    print("加载 CSV 模板...")
    manager.load_template(csv_path)
    print(f"  CSV 共有 {len(manager.csv_records)} 条记录")

    print("对比差异...")
    diff = manager.compare()
    print(f"  全量算法: {diff.summary()['total']} 个")
    print(f"  待释放: {diff.summary()['to_release_count']} 个")
    print(f"  误释放: {diff.summary()['should_unrelease_count']} 个")
    print(f"  仅模板有: {diff.summary()['only_in_template_count']} 个")
    print(f"  仅平台有: {diff.summary()['only_in_platform_count']} 个")

    if diff.to_release:
        print(f"\n开始释放 {len(diff.to_release)} 个待发布算法...")
        result = manager.release_pending(concurrent=3)
        print(f"释放完成: 成功 {result['success_count']}, 失败 {result['fail_count']}")

    if diff.should_unrelease:
        print(f"\n开始取消释放 {len(diff.should_unrelease)} 个误发布算法...")
        result = manager.unrelease_misreleased(concurrent=3)
        print(f"取消释放完成: 成功 {result['success_count']}, 失败 {result['fail_count']}")
