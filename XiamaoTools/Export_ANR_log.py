"""自动导出手机Anr日志到电脑上"""

import os
import subprocess
import zipfile
from datetime import datetime

def export_anr(save_dir: str="/Users/admin/TestLog/anr_data", auto_unzip: bool = False):
    """

    :param save_dir: 文件保存目录
    :param auto_unzip: 为false不会自动解压anr文件，为true会自动解压文件
    :return:
    """
    # 1. 时间戳目录
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    target_dir = os.path.join(save_dir, timestamp)
    os.makedirs(target_dir, exist_ok=True)

    # 2. bugreport 输出文件路径
    zip_path = os.path.join(target_dir, "bugreport.zip")

    # 3. 调用 adb bugreport
    print(f"[INFO] 导出 ANR 日志到: {zip_path}")
    result = subprocess.run(["adb", "bugreport", zip_path], capture_output=True, text=True)

    if result.returncode != 0:
        print("[ERROR] adb bugreport 执行失败")
        print(result.stderr)
        return

    print("[INFO] bugreport 导出完成")

    # 4. 是否自动解压
    if auto_unzip:
        unzip_dir = os.path.join(target_dir, "bugreport")
        os.makedirs(unzip_dir, exist_ok=True)
        print(f"[INFO] 正在解压到 {unzip_dir}")
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(unzip_dir)
        print("[INFO] 解压完成")

        # 5. 定位 FS/data/anr 目录并改后缀为 .txt
        anr_dir = os.path.join(unzip_dir, "FS", "data", "anr")
        if os.path.exists(anr_dir):
            for filename in os.listdir(anr_dir):
                file_path = os.path.join(anr_dir, filename)
                if os.path.isfile(file_path):
                    new_path = os.path.splitext(file_path)[0] + ".txt"
                    os.rename(file_path, new_path)
                    print(f"[INFO] 已改名: {file_path} → {new_path}")
        else:
            print(f"[WARN] 未找到目录: {anr_dir}")

    print(f"[INFO] 所有文件已保存到: {target_dir}")
    if auto_unzip:
        print("可在解压目录的 FS/data/anr/ 下查看改为 .txt 的 ANR 日志")
    else:
        print("可解压bugreport.zip文件后到：FS/data/anr/目录找到对应anr文件，搜索关键字Subject查看日志")


if __name__ == "__main__":
    export_anr(auto_unzip=False)
