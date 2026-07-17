#!/usr/bin/env python3

import argparse
import re
import subprocess
import sys
import time
from pathlib import Path


DEFAULT_PACKAGE = "com.phone.clap.finder.locate.device"
REMOTE_XML = "/sdcard/window_dump.xml"
LOCAL_XML = Path("/tmp/playstore_uiauto.xml")


def run_adb(args, serial=None, check=True, capture_output=True):
    cmd = ["adb"]
    if serial:
        cmd += ["-s", serial]
    cmd += args
    return subprocess.run(
        cmd,
        check=check,
        text=True,
        capture_output=capture_output,
    )


def wait_for_device(serial=None):
    run_adb(["wait-for-device"], serial=serial, capture_output=False)
    result = run_adb(["get-state"], serial=serial)
    state = result.stdout.strip()
    if state != "device":
        raise RuntimeError(f"ADB 设备未就绪，当前状态：{state or 'unknown'}")


def is_installed(package_name, serial=None):
    result = run_adb(
        ["shell", "cmd", "package", "list", "packages", package_name],
        serial=serial,
        check=False,
    )
    return f"package:{package_name}" in (result.stdout or "")


def dump_ui(serial=None):
    run_adb(["shell", "uiautomator", "dump", REMOTE_XML], serial=serial)
    run_adb(["pull", REMOTE_XML, str(LOCAL_XML)], serial=serial)
    if not LOCAL_XML.exists():
        raise RuntimeError("拉取 UI XML 文件失败。")
    return LOCAL_XML.read_text(encoding="utf-8", errors="ignore")


def extract_center_from_line(line):
    m = re.search(r'bounds="\[(\d+),(\d+)]\[(\d+),(\d+)]"', line)
    if not m:
        return None
    x1, y1, x2, y2 = map(int, m.groups())
    return (x1 + x2) // 2, (y1 + y2) // 2


def find_install_button_center(xml_text):
    patterns = [
        r'content-desc="安装"',
        r'text="安装"',
        r'content-desc="Install"',
        r'text="Install"',
        r'content-desc="Get"',
        r'text="Get"',
    ]
    lines = xml_text.splitlines()
    if len(lines) == 1:
        lines = re.split(r'(?=<node )', xml_text)

    for pat in patterns:
        for line in lines:
            if re.search(pat, line):
                center = extract_center_from_line(line)
                if center:
                    return center, pat
    return None, None


def tap(serial, x, y):
    run_adb(["shell", "input", "tap", str(x), str(y)], serial=serial, capture_output=False)


def open_play_store(package_name, serial=None):
    run_adb(
        [
            "shell",
            "am",
            "start",
            "-a",
            "android.intent.action.VIEW",
            "-d",
            f"market://details?id={package_name}",
            "com.android.vending",
        ],
        serial=serial,
    )


def launch_app(package_name, serial=None):
    result = run_adb(
        [
            "shell",
            "monkey",
            "-p",
            package_name,
            "-c",
            "android.intent.category.LAUNCHER",
            "1",
        ],
        serial=serial,
        check=False,
    )
    output = ((result.stdout or "") + (result.stderr or "")).strip()
    ok = result.returncode == 0 and "Events injected: 1" in output
    return ok, output


def main():
    parser = argparse.ArgumentParser(
        description="通过动态识别安装按钮，从 Google Play 安装应用。"
    )
    parser.add_argument("package", nargs="?", default=DEFAULT_PACKAGE, help="要安装的包名")
    parser.add_argument("-s", "--serial", default=None, help="ADB 设备序列号")
    parser.add_argument("--max-retry", type=int, default=20, help="查找按钮和校验安装的最大重试次数")
    parser.add_argument("--sleep-sec", type=float, default=2.0, help="每次重试之间的等待秒数")
    args = parser.parse_args()

    package_name = args.package
    serial = args.serial

    try:
        print(f"目标包名：{package_name}")
        if serial:
            print(f"使用设备序列号：{serial}")

        wait_for_device(serial=serial)

        if is_installed(package_name, serial=serial):
            print(f"应用已安装：{package_name}")
            print("正在启动应用...")
            launch_ok, launch_output = launch_app(package_name, serial=serial)
            if launch_ok:
                print(f"启动成功：{package_name}")
                return 0
            print("启动失败。")
            if launch_output:
                print(launch_output)
            return 1

        print("正在打开 Play 商店详情页...")
        open_play_store(package_name, serial=serial)
        time.sleep(args.sleep_sec)

        print("正在查找并点击安装按钮...")
        clicked = False
        for _ in range(args.max_retry):
            xml_text = dump_ui(serial=serial)
            center, pat = find_install_button_center(xml_text)
            if center:
                x, y = center
                print(f"已通过以下模式找到安装按钮：{pat}")
                print(f"点击坐标：{x},{y}")
                tap(serial, x, y)
                clicked = True
                break
            time.sleep(args.sleep_sec)

        if not clicked:
            print(f"重试 {args.max_retry} 次后仍未找到安装按钮。")
            return 1

        print("正在等待安装完成...")
        for _ in range(args.max_retry):
            if is_installed(package_name, serial=serial):
                print(f"安装成功：{package_name}")
                print("正在启动应用...")
                launch_ok, launch_output = launch_app(package_name, serial=serial)
                if launch_ok:
                    print(f"启动成功：{package_name}")
                    return 0
                print("启动失败。")
                if launch_output:
                    print(launch_output)
                return 1
            time.sleep(args.sleep_sec)

        print(f"安装可能仍在进行中，暂未检测到包名：{package_name}")
        return 1

    except Exception as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
