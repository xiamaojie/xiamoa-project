#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import subprocess
import datetime
import time
import glob


def ensure_timestamp_dir(root_dir):
    """
    确保存在当前时间戳目录（年_月_日_时），
    返回该目录的绝对路径。
    """
    now = datetime.datetime.now()
    timestamp_dir = now.strftime("%Y_%m_%d_%H")  # 例如 2025_09_23_10
    target_dir = os.path.join(root_dir, timestamp_dir)

    if not os.path.exists(target_dir):
        os.makedirs(target_dir)
        print(f"[INFO] 已创建目录: {target_dir}")
    else:
        print(f"[INFO] 使用已存在目录: {target_dir}")

    return target_dir


def check_and_clean_dir_if_needed(target_dir, max_minutes=5):
    """
    检查目录下最新图片的修改时间 (mtime)，
    如果 >= max_minutes 分钟，则清空目录。
    返回 True 表示已清空，False 表示未清空。
    """
    png_files = glob.glob(os.path.join(target_dir, "*.png"))
    if not png_files:
        return False  # 没有图片，无需处理

    # 获取最新图片的修改时间
    latest_file = max(png_files, key=os.path.getmtime)
    latest_mtime = os.path.getmtime(latest_file)
    now = time.time()
    minutes_diff = (now - latest_mtime) / 60

    if minutes_diff >= max_minutes:
        print(f"[INFO] 最新图片已超过 {max_minutes} 分钟 ({minutes_diff:.1f} 分钟)，清空目录。")
        for f in png_files:
            try:
                os.remove(f)
                print(f"[INFO] 已删除旧图片: {f}")
            except Exception as e:
                print(f"[WARN] 删除文件失败: {f}, 原因: {e}")
        print("[INFO] 目录已清空，编号将从 1.png 重新开始。")
        return True
    else:
        print(f"[INFO] 最新图片距今 {minutes_diff:.1f} 分钟，保留目录内容。")
        return False


def get_next_filename(target_dir):
    """
    找到下一个可用的递增文件名，如 1.png, 2.png ...
    """
    i = 1
    while True:
        filename = f"{i}.png"
        filepath = os.path.join(target_dir, filename)
        if not os.path.exists(filepath):
            return filepath
        i += 1


def take_screenshot(save_path):
    """
    执行 adb 截图并保存到指定路径。
    """
    try:
        print("[INFO] 正在执行 adb 截图...")
        result = subprocess.run(
            ["adb", "exec-out", "screencap", "-p"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True
        )

        with open(save_path, "wb") as f:
            f.write(result.stdout)

        abs_path = os.path.abspath(save_path)
        print(f"[✅ 成功] 截图已保存至: {abs_path}")
        return abs_path

    except subprocess.CalledProcessError as e:
        print(f"[❌ 错误] ADB 命令执行失败: {e.stderr.decode('utf-8', errors='ignore').strip()}")
    except FileNotFoundError:
        print("[❌ 错误] 未找到 adb 命令，请确保已安装 Android SDK 并配置环境变量 PATH。")
    except Exception as e:
        print(f"[❌ 未知错误]: {e}")


def run_screenshot(root_dir, max_minutes=5):
    """
    截图完整流程：确保目录 -> 判断是否清空目录 -> 获取文件名 -> 截图保存。
    """
    target_dir = ensure_timestamp_dir(root_dir)

    check_and_clean_dir_if_needed(target_dir, max_minutes=max_minutes)

    # 获取下一个文件名（如果清空过，会自动从 1.png 开始）
    screenshot_path = get_next_filename(target_dir)

    return take_screenshot(screenshot_path)


if __name__ == "__main__":
    default_output_dir = "/Users/admin/TestLog/img_upload"
    run_screenshot(default_output_dir, max_minutes=5)
