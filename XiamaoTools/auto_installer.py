"""
根据文件扩展名aab和apk执行安装最新安装包的脚本
"""

import glob
import os
import subprocess
from pathlib import Path

# 下载目录路径
downloads_dir = "/Users/admin/Downloads"

# 查找 .apk 和 .aab 文件
all_files = glob.glob(os.path.join(downloads_dir, "*.[aA][pP][kK]")) + \
            glob.glob(os.path.join(downloads_dir, "*.[aA][aA][bB]"))

if not all_files:
    print("没有找到 .apk 或 .aab 文件。")
    exit(1)

# 获取修改时间最新的文件
latest_file = max(all_files, key=os.path.getmtime)
print(f"最新文件: {latest_file}")

PROJECT_ROOT = Path(__file__).resolve().parents[1]
VENV_PYTHON = str(PROJECT_ROOT / ".venv" / "bin" / "python3")

# 要执行的命令
if latest_file.endswith(".aab"):
    command = [
        VENV_PYTHON,
        str(PROJECT_ROOT / "XiamaoTools" / "install_aabV2.py"),
    ]
elif latest_file.endswith(".apk"):
    command = [
        VENV_PYTHON,
        str(PROJECT_ROOT / "XiamaoTools" / "AppUpdate.py"),
    ]
else:
    print("未知的文件类型。")
    exit(1)

# 执行对应的脚本
try:
    subprocess.run(command, check=True)
except subprocess.CalledProcessError as e:
    print(f"执行脚本失败: {e}")
