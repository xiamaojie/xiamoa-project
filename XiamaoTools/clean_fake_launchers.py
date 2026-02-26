#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import subprocess
import sys
import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

# 可信的系统 Launcher 包名（按需扩展）
TRUSTED_PACKAGES = {
    "com.google.android.apps.nexuslauncher",  # Pixel Launcher
    "com.sec.android.app.launcher",  # Samsung One UI
    "com.miui.home",  # MIUI
    "com.htc.launcher",  # HTC
    "com.android.launcher3",  # AOSP Launcher3
    "com.android.settings",  # FallbackHome (safe)
    "com.google.android.settings",  # Google Settings (sometimes appears)
    "com.motorola.launcher3",  # Motorola Launcher (common for many Motorola devices)
}
UNINSTALL_WORKERS = 3


def run_adb_cmd(cmd):
    """执行 ADB 命令，返回 stdout 行列表"""
    try:
        result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=10)
        if result.returncode != 0:
            print(f"[!] ADB 错误: {result.stderr.strip()}")
            return []
        return result.stdout.strip().splitlines()
    except subprocess.TimeoutExpired:
        print("[!] ADB 命令超时")
        return []
    except Exception as e:
        print(f"[!] 执行 ADB 失败: {e}")
        return []


def get_home_launchers():
    """获取所有可作为主屏幕的应用包名"""
    print("[+] 正在检测可设为主屏幕的应用...")
    lines = run_adb_cmd(
        "adb shell cmd package query-activities -a android.intent.action.MAIN -c android.intent.category.HOME")

    packages = set()
    for line in lines:
        match = re.search(r'packageName=(\S+)', line)
        if match:
            pkg = match.group(1)
            packages.add(pkg)
    return packages


def is_suspicious(pkg):
    """判断是否为可疑第三方启动器"""
    if pkg in TRUSTED_PACKAGES:
        return False
    suspicious = False
    try:
        third_pkgs = subprocess.run(
            "adb shell pm list packages -3",
            shell=True, capture_output=True, text=True, timeout=5
        )
        if third_pkgs.returncode == 0 and f"package:{pkg}" in third_pkgs.stdout:
            suspicious = True
    except (subprocess.TimeoutExpired, subprocess.SubprocessError, OSError):
        pass
    # 系统应用通常位于 /system/ 或 /system_ext/
    # 第三方应用路径为 /data/app/
    try:
        path_info = subprocess.run(
            f"adb shell pm path {pkg}",
            shell=True, capture_output=True, text=True, timeout=5
        )
        if path_info.returncode == 0:
            path = path_info.stdout
            if "/data/app/" in path:
                suspicious = True
    except (subprocess.TimeoutExpired, subprocess.SubprocessError, OSError):
        pass
    return suspicious


def uninstall_packages(packages, workers):
    """批量卸载包"""
    uninstalled = []
    failed = []
    workers = max(1, int(workers))
    print_lock = threading.Lock()

    def log(msg):
        with print_lock:
            print(msg)

    def uninstall_one(pkg):
        log(f"[+] 正在卸载: {pkg}")
        result = subprocess.run(f"adb uninstall {pkg}", shell=True, capture_output=True, text=True)
        if result.returncode == 0 and "Success" in result.stdout:
            log("    ✓ 卸载成功")
            return pkg, True, ""
        stdout = result.stdout.strip()
        stderr = result.stderr.strip()
        reason = stdout or stderr or f"returncode={result.returncode}"
        log(f"    ✗ 卸载失败: {reason}")
        return pkg, False, reason

    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = [executor.submit(uninstall_one, pkg) for pkg in packages]
        for future in as_completed(futures):
            pkg, ok, failure_reason = future.result()
            if ok:
                uninstalled.append(pkg)
            else:
                failed.append((pkg, failure_reason))
    return uninstalled, failed


def main():
    print("🔍 Android 伪启动器检测与清理工具\n")

    # 检查 ADB 是否连接设备
    devices = run_adb_cmd("adb devices")
    if len(devices) < 2 or "device" not in "\n".join(devices):
        print("[!] 未检测到已连接的 Android 设备，请检查 USB 调试和连接。")
        sys.exit(1)

    home_pkgs = get_home_launchers()
    if not home_pkgs:
        print("[!] 未找到任何可设为主屏幕的应用。")
        return

    print(f"[+] 共检测到 {len(home_pkgs)} 个 HOME 应用:")
    for p in sorted(home_pkgs):
        print(f"    - {p}")

    suspicious = [p for p in home_pkgs if is_suspicious(p)]

    if not suspicious:
        print("\n✅ 未发现可疑的第三方启动器，系统干净！")
        return

    print(f"\n⚠️  发现 {len(suspicious)} 个可疑启动器:")
    for p in sorted(suspicious):
        print(f"    ❌ {p}")

    uninstalled, failed = uninstall_packages(suspicious, UNINSTALL_WORKERS)
    if uninstalled:
        print("\n✅ 清理完成！建议重启设备以确保彻底生效。")
        print("\n📦 已卸载的包:")
        for p in sorted(uninstalled):
            print(f"    - {p}")
    else:
        print("\nℹ️  未成功卸载任何包。")

    if failed:
        print("\n❌ 卸载失败的包:")
        for pkg, reason in failed:
            print(f"    - {pkg}: {reason}")


if __name__ == "__main__":
    main()
