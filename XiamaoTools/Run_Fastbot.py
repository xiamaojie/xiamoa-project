#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import argparse
import os
import subprocess
import sys
import time
from datetime import datetime



def run_cmd(cmd_list):
    process = None  # 提前定义 process 变量
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
        if process:  # 确保 process 已创建后再终止
            process.terminate()
        print("\n❌ 中断执行")
        sys.exit(1)


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
    except subprocess.CalledProcessError as e:
        print(f"⚠️ 获取设备列表失败：{e}")
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
        f"{remote_dir}/.",  # 拉取目录内容
        local_target_dir
    ])


def pull_if_exists(serial, remote_path, local_target_dir):
    print(f"\n🔍 检查是否存在文件：{remote_path}")
    try:
        result = adb_shell(serial, f'ls {remote_path}')
        if 'No such file' in result or not result.strip():
            print(f"⚠️ 未找到：{remote_path}")
            return
        print(f"📥 拉取文件：{remote_path}")
        run_cmd(['adb', '-s', serial, 'pull', remote_path, local_target_dir])
    except subprocess.CalledProcessError:
        print(f"⚠️ 拉取失败或文件不存在：{remote_path}")


def clear_old_logs(serial):
    print("🧹 清除设备上的旧日志文件")
    for path in ['/sdcard/crash-dump.log', '/sdcard/oom-traces.log']:
        try:
            adb_shell(serial, f'rm -f {path}')
        except subprocess.CalledProcessError:
            print(f"⚠️ 无法删除或文件不存在：{path}")


def print_device_time(serial):
    try:
        current_time = adb_shell(serial, 'date')
        print(f"\n🕒 当前设备系统时间：{current_time.strip()}")
    except subprocess.CalledProcessError:
        print("⚠️ 无法获取设备时间")


def main():
    """
    Fastbot自动化测试主函数
    该脚本用于自动化运行Fastbot测试，并处理测试结果
    """
    # 初始化命令行参数解析器
    parser = argparse.ArgumentParser(description="📱 Fastbot 自动化测试脚本 (含崩溃日志提取)")
    # 添加命令行参数
    parser.add_argument('--serial', help='目标设备序列号（可选，不填将自动获取）')
    parser.add_argument('--apk-package', default='com.hotpotgames.happysave.global', help='待测应用包名')
    parser.add_argument('--duration', type=int, default=30, help='测试时长（分钟，默认60，更改无用）')
    parser.add_argument('--throttle', type=int, default=300, help='事件间隔（毫秒，默认500ms）')
    parser.add_argument('--output-dir', default='/sdcard/fastbot_results', help='设备端日志保存路径')
    parser.add_argument('--local-log-dir', default='/Users/admin/TestLog/fastbot_results', help='本地日志目录根路径')
    # 解析命令行参数
    args = parser.parse_args()

    # 如果未指定设备序列号，尝试自动获取
    if not args.serial:
        auto_serial = get_first_device()
        if not auto_serial:
            print("❌ 未找到任何 adb 设备，请检查设备连接")
            run_cmd(['adb', 'devices'])
            sys.exit(1)
        args.serial = auto_serial
        print(f"🔍 未指定设备序列号，已自动识别为：{args.serial}")

    # 确保adb命令可用
    if not adb_exists():
        print("❌ adb 命令未找到，请确保安装并添加 adb 到环境变量中")
        sys.exit(1)

    # 确保指定序列号的设备已连接并授权
    if not check_device_online(args.serial):
        print(f"❌ 设备【{args.serial}】未连接或未授权")
        run_cmd(['adb', 'devices'])
        sys.exit(1)

    # 确保待测应用已安装在设备上
    if not check_package_installed(args.serial, args.apk_package):
        print(f"❌ 应用包【{args.apk_package}】未安装在设备 {args.serial} 上")
        sys.exit(1)

    # 打印设备当前时间并清除旧日志
    print_device_time(args.serial)
    clear_old_logs(args.serial)

    # 创建本地带时间戳的日志目录
    timestamped_dir = create_timestamped_dir(args.local_log_dir)
    print(f"\n🗂️ 本地日志目录已准备：{timestamped_dir}")

    # 显示测试开始信息
    print(f"\n🚀 开始 Fastbot 测试，持续 {args.duration} 分钟，请保持设备连接...\n")

    # 构建运行Fastbot测试的adb命令
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

    # 记录测试开始时间
    start_time = time.time()
    # 执行Fastbot测试命令
    ret_code = run_cmd(cmd)
    # 记录测试结束时间
    end_time = time.time()
    # 计算测试实际运行时间
    elapsed = end_time - start_time

    print(f"\n🔧 Fastbot 返回码：{ret_code}")

    # 打印Fastbot实际运行时长
    print(f"\n🕒 Fastbot 实际运行时长：{elapsed:.1f} 秒 ≈ {elapsed / 60:.2f} 分钟")
    # 如果实际运行时间远小于预期时间，提示可能存在的问题
    if elapsed < args.duration * 60 * 0.9:
        print("⚠️ Fastbot 提前退出，可能存在兼容性问题、系统杀进程、jar异常或权限问题。")

    # 开始从设备抓取测试日志
    print("\n📁 Fastbot 测试结束，开始抓取日志...\n")
    time.sleep(1)
    pull_logs(args.serial, args.output_dir, timestamped_dir)
    time.sleep(1)

    # 尝试检测并拉取崩溃日志
    try:
        log_check = adb_shell(args.serial, 'ls /sdcard/*.log')
        if not log_check.strip():
            print("⚠️ 未检测到任何 .log 文件，跳过拉取")
        else:
            print("🔍 检测到日志文件，开始拉取...")
            pull_if_exists(args.serial, '/sdcard/crash-dump.log', timestamped_dir)
            pull_if_exists(args.serial, '/sdcard/oom-traces.log', timestamped_dir)
    except subprocess.CalledProcessError:
        print("⚠️ 日志检测命令失败，可能没有任何崩溃日志的 .log 文件")

    # 所有日志处理完成，打印保存位置
    print(f"\n✅ 所有日志处理完成，保存在：{timestamped_dir}")


if __name__ == '__main__':
    main()
