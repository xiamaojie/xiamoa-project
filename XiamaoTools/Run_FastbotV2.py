#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
自动识别设备序列号

执行 Fastbot 测试并实时打印输出

拉取 Fastbot 测试日志 + crash-dump.log + oom-traces.log

添加 --analyze 参数，可自动分析崩溃

自动生成纯文本报告和漂亮的 HTML 报告
"""


import argparse
import subprocess
import time
import sys
import os
from datetime import datetime

def run_cmd(cmd_list, live_output=False):
    if live_output:
        try:
            process = subprocess.Popen(
                cmd_list, stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, universal_newlines=True
            )
            for line in process.stdout:
                print(line, end='')
            process.wait()
            return process.returncode
        except KeyboardInterrupt:
            process.terminate()
            print("\n❌ 中断执行")
            sys.exit(1)
    else:
        return subprocess.call(cmd_list)

def adb_shell(serial, shell_cmd):
    return subprocess.check_output(['adb', '-s', serial, 'shell', shell_cmd], universal_newlines=True)

def adb_exists():
    try:
        subprocess.check_output(['adb', 'version'], stderr=subprocess.DEVNULL)
        return True
    except FileNotFoundError:
        return False

def get_first_device():
    try:
        output = subprocess.check_output(['adb', 'devices'], universal_newlines=True)
        for line in output.strip().splitlines()[1:]:
            if line.strip() and '\tdevice' in line:
                return line.split()[0]
    except:
        pass
    return None

def check_device_online(serial):
    out = subprocess.check_output(['adb', 'devices'], universal_newlines=True)
    for line in out.strip().splitlines():
        if serial in line and 'device' in line:
            return True
    return False

def check_package_installed(serial, package_name):
    cmd = f'pm list packages {package_name}'
    out = adb_shell(serial, cmd)
    return package_name in out

def create_timestamped_dir(base_dir):
    timestamp = datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
    target_path = os.path.join(base_dir, timestamp)
    os.makedirs(target_path, exist_ok=True)
    return target_path

def pull_logs(serial, remote_dir, local_target_dir):
    print(f"\n📥 拉取日志目录：{remote_dir} ➜ {local_target_dir}")
    os.makedirs(local_target_dir, exist_ok=True)
    return run_cmd([
        'adb', '-s', serial, 'pull',
        f"{remote_dir}/.",
        local_target_dir
    ], live_output=True)

def pull_if_exists(serial, remote_path, local_target_dir):
    print(f"\n🔍 检查是否存在文件：{remote_path}")
    try:
        result = adb_shell(serial, f'ls {remote_path}')
        if 'No such file' in result or not result.strip():
            print(f"⚠️ 未找到：{remote_path}")
            return None
        print(f"📥 拉取文件：{remote_path}")
        run_cmd(['adb', '-s', serial, 'pull', remote_path, local_target_dir], live_output=True)
        return os.path.join(local_target_dir, os.path.basename(remote_path))
    except subprocess.CalledProcessError:
        print(f"⚠️ 拉取失败或文件不存在：{remote_path}")
        return None

# 提取包名辅助函数
def extract_package_name(text):
    import re
    match = re.search(r'(?:ANR|CRASH): ([\w\.]+)', text)
    return match.group(1) if match else "未知"

# 分析 crash-dump.log 并生成文本 + HTML 报告
def analyze_crash_log(filepath):
    print("\n🧠 正在分析 crash-dump.log...\n")
    if not os.path.exists(filepath):
        print("❌ 未找到 crash-dump.log")
        return

    found_crash = False
    found_anr = False
    with open(filepath, 'r', encoding='utf-8') as f:
        content = f.read()

        if 'ANR:' in content:
            found_anr = True
            print("⚠️ 发现 ANR（应用无响应）")

        if 'java.lang' in content or 'CRASH:' in content:
            found_crash = True
            print("💥 发现 Java 崩溃")

    # 文本报告
    summary_path = os.path.join(os.path.dirname(filepath), 'crash_summary.txt')
    with open(summary_path, 'w', encoding='utf-8') as out:
        out.write("📄 崩溃分析报告\n")
        out.write("=================\n")
        out.write(f"ANR 是否发生: {'是' if found_anr else '否'}\n")
        out.write(f"Java Crash 是否发生: {'是' if found_crash else '否'}\n")

    # HTML 报告
    html_path = os.path.join(os.path.dirname(filepath), 'crash_report.html')
    with open(html_path, 'w', encoding='utf-8') as html:
        html.write(f"""<!DOCTYPE html>
<html lang="zh">
<head>
    <meta charset="UTF-8">
    <title>崩溃分析报告</title>
    <style>
        body {{ font-family: Arial, sans-serif; padding: 20px; background-color: #f7f7f7; }}
        .box {{ background: white; padding: 20px; border-radius: 10px; box-shadow: 0 0 8px rgba(0,0,0,0.1); }}
        h1 {{ color: #333; }}
        .item {{ margin: 10px 0; font-size: 18px; }}
        .yes {{ color: red; font-weight: bold; }}
        .no {{ color: green; font-weight: bold; }}
    </style>
</head>
<body>
    <div class="box">
        <h1>📋 崩溃分析报告</h1>
        <div class="item">📦 包名：<strong>{extract_package_name(content)}</strong></div>
        <div class="item">🕒 分析时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</div>
        <div class="item">💥 Java Crash：<span class="{ 'yes' if found_crash else 'no' }">{'发生' if found_crash else '未发生'}</span></div>
        <div class="item">⏱️ ANR（无响应）：<span class="{ 'yes' if found_anr else 'no' }">{'发生' if found_anr else '未发生'}</span></div>
    </div>
</body>
</html>
""")
    print(f"\n✅ HTML 报告生成：{html_path}")

def main():
    parser = argparse.ArgumentParser(description="📱 Fastbot 自动化测试脚本 (含崩溃日志提取 + HTML报告)")
    parser.add_argument('--serial', help='目标设备序列号（可选，不填将自动获取）')
    parser.add_argument('--apk-package', default='com.hotpotgames.happysave.global', help='待测应用包名')
    parser.add_argument('--duration', type=int, default=1, help='测试时长（分钟，默认1）')
    parser.add_argument('--throttle', type=int, default=100, help='事件间隔（毫秒，默认100ms）')
    parser.add_argument('--output-dir', default='/sdcard/fastbot_results', help='设备端日志保存路径')
    parser.add_argument('--local-log-dir', default='/Users/admin/TestLog/fastbot_results', help='本地日志目录根路径')
    parser.add_argument('--analyze', action='store_true', help='测试完成后自动分析崩溃并生成 HTML 报告')
    args = parser.parse_args()

    if not args.serial:
        auto_serial = get_first_device()
        if not auto_serial:
            print("❌ 未找到任何 adb 设备，请检查设备连接")
            run_cmd(['adb', 'devices'])
            sys.exit(1)
        args.serial = auto_serial
        print(f"🔍 未指定设备序列号，已自动识别为：{args.serial}")

    if not adb_exists():
        print("❌ adb 命令未找到，请确保安装并添加 adb 到环境变量中")
        sys.exit(1)

    if not check_device_online(args.serial):
        print(f"❌ 设备【{args.serial}】未连接或未授权")
        run_cmd(['adb', 'devices'])
        sys.exit(1)

    if not check_package_installed(args.serial, args.apk_package):
        print(f"❌ 应用包【{args.apk_package}】未安装在设备 {args.serial} 上")
        sys.exit(1)

    timestamped_dir = create_timestamped_dir(args.local_log_dir)
    print(f"\n🗂️ 本地日志目录已准备：{timestamped_dir}")

    print(f"\n🚀 开始 Fastbot 测试，持续 {args.duration} 分钟，请保持设备连接...\n")

    cmd = [
        'adb', '-s', args.serial, 'shell',
        'CLASSPATH=/sdcard/monkeyq.jar:/sdcard/framework.jar:/sdcard/fastbot-thirdpart.jar',
        'exec', 'app_process', '/system/bin', 'com.android.commands.monkey.Monkey',
        '-p', args.apk_package,
        '--agent', 'reuseq',
        '--running-minutes', str(args.duration),
        '--throttle', str(args.throttle),
        '-v', '-v',
        '--output-directory', args.output_dir
    ]

    run_cmd(cmd, live_output=True)

    print("\n📁 Fastbot 测试结束，开始抓取日志...\n")

    pull_logs(args.serial, args.output_dir, timestamped_dir)
    crash_log_path = pull_if_exists(args.serial, '/sdcard/crash-dump.log', timestamped_dir)
    pull_if_exists(args.serial, '/sdcard/oom-traces.log', timestamped_dir)

    if args.analyze and crash_log_path:
        analyze_crash_log(crash_log_path)

    print(f"\n✅ 所有日志处理完成，保存在：{timestamped_dir}")

if __name__ == '__main__':
    main()
