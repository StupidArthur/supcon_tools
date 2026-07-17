"""
复制namespace配置文件脚本

将 ns1.yaml 复制为 ns2.yaml ~ ns100.yaml
"""

import shutil
from pathlib import Path

# 项目根目录
project_root = Path(__file__).parent.parent

# ns1.yaml 的路径
source_file = project_root / "controller" / "running_config" / "ns1.yaml"
target_dir = project_root / "controller" / "running_config"

# 检查源文件是否存在
if not source_file.exists():
    print(f"错误: 源文件不存在: {source_file}")
    exit(1)

print(f"源文件: {source_file}")
print(f"目标目录: {target_dir}")
print()

# 复制文件
copied_count = 0
for i in range(2, 101):  # ns2.yaml 到 ns100.yaml
    target_file = target_dir / f"ns{i}.yaml"
    try:
        shutil.copy2(source_file, target_file)
        copied_count += 1
        if i <= 10 or i % 10 == 0:  # 显示前10个和每10个
            print(f"已复制: {target_file.name}")
    except Exception as e:
        print(f"错误: 复制 {target_file.name} 失败: {e}")

print()
print(f"完成! 共复制 {copied_count} 个文件 (ns2.yaml ~ ns100.yaml)")

