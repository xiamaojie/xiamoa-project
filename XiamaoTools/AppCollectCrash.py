import os
import subprocess
import re
import shutil
from datetime import datetime

def parse_crash_log(log_content):
    """
    从崩溃日志中提取关键信息。
    """
    crash_info = {}
    patterns = {
        "Date": r"Date:\s+(.+)",
        "Exception Type": r"Exception Type:\s+(.+)",
        "Exception Codes": r"Exception Codes:\s+(.+)",
        "Crashed Thread": r"Thread (\d+) Crashed:",
    }
    for key, pattern in patterns.items():
        match = re.search(pattern, log_content)
        if match:
            crash_info[key] = match.group(1)
    return crash_info

def get_crash_logs(bundle_id, output_dir):
    """
    使用idevicecrashreport获取崩溃日志，并根据包名过滤最新的.ips文件中的crash日志。
    保留原始的最新.ips文件和过滤后的崩溃日志文件，删除其他无关文件。
    增强日志分析功能，自动提取关键崩溃信息。
    """
    print("调用前请确保iOS手机开启了开发者模式")
    # 确保输出目录存在
    if not os.path.exists(output_dir):
        os.makedirs(output_dir, exist_ok=True)

    # 调用idevicecrashreport命令
    try:
        print("正在从设备获取崩溃日志...")
        subprocess.run(["idevicecrashreport", "-e", "-k", output_dir], check=True)
        print("崩溃日志已导出到临时目录。")
    except subprocess.CalledProcessError as e:
        print(f"运行idevicecrashreport时出错: {e}")
        return

    # 获取所有.ips文件
    ips_files = [f for f in os.listdir(output_dir) if f.endswith(".ips")]

    if not ips_files:
        print("未找到任何.ips文件。")
        return

    # 按文件名中的时间戳排序，找到最新的.ips文件
    def extract_timestamp(filename):
        match = re.search(r"(\d{4}-\d{2}-\d{2}-\d{6})", filename)
        if match:
            return datetime.strptime(match.group(1), "%Y-%m-%d-%H%M%S")
        return None

    ips_files_with_timestamp = [(f, extract_timestamp(f)) for f in ips_files if extract_timestamp(f)]
    ips_files_with_timestamp.sort(key=lambda x: x[1], reverse=True)

    # 遍历排序后的文件，找到第一个包含指定包名的.ips文件
    target_file = None
    for filename, timestamp in ips_files_with_timestamp:
        file_path = os.path.join(output_dir, filename)
        with open(file_path, "r", encoding="utf-8") as file:
            content = file.read()
            if re.search(rf"\b{bundle_id}\b", content):
                print(f"找到包含包名 {bundle_id} 的最新.ips文件: {filename}")
                target_file = filename
                break

    if target_file:
        original_ips_output = os.path.join(output_dir, target_file)
        filtered_ips_output = os.path.join(output_dir, f"{bundle_id}_latest_ips_file.ips")

        # 保存原始和过滤后的文件
        with open(original_ips_output, "r", encoding="utf-8") as original_file:
            log_content = original_file.read()
            with open(filtered_ips_output, "w", encoding="utf-8") as filtered_file:
                filtered_file.write(log_content)

            # 提取崩溃信息
            crash_info = parse_crash_log(log_content)
            print("崩溃信息摘要：")
            for key, value in crash_info.items():
                print(f"{key}: {value}")

        os.chmod(original_ips_output, 0o644)
        os.chmod(filtered_ips_output, 0o644)

        print(f"过滤后的崩溃日志文件已保存到: {filtered_ips_output}")

        # 删除其他所有文件和目录
        for f in os.listdir(output_dir):
            path = os.path.join(output_dir, f)
            if f not in [os.path.basename(original_ips_output), os.path.basename(filtered_ips_output)]:
                try:
                    if os.path.isfile(path):
                        os.remove(path)
                    elif os.path.isdir(path):
                        shutil.rmtree(path)
                except PermissionError as e:
                    print(f"无法删除 {path}: {e}")
                except Exception as e:
                    print(f"删除 {path} 时出错: {e}")
        print("其他无关文件已删除。")
    else:
        print(f"未找到包含包名 {bundle_id} 的.ips文件。")
        # 删除所有临时文件和目录
        for f in os.listdir(output_dir):
            path = os.path.join(output_dir, f)
            try:
                if os.path.isfile(path):
                    os.remove(path)
                elif os.path.isdir(path):
                    shutil.rmtree(path)
            except PermissionError as e:
                print(f"无法删除 {path}: {e}")
            except Exception as e:
                print(f"删除 {path} 时出错: {e}")
        print("未找到目标文件，所有临时文件已删除。")

# 固定参数
bundle_id = "com.clearify.ai.storge.cleaner.photo.compress.merge"
output_dir = "/Users/admin/TestLog"  # 修改为新的输出目录

# 调用方法
get_crash_logs(bundle_id, output_dir)
