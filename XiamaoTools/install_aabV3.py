"""
安装 AAB 第 3 版本脚本，支持获取应用名称，版本号等功能。
"""
import os
import re
import subprocess
import tempfile
import time
import zipfile
from datetime import datetime

from androguard.core.apk import APK
from loguru import logger

logger.remove()
logger.add(lambda msg: None, level="ERROR")

#  配置 bundletool 的 JAR 文件路径
BUNDLETOOL_JAR = "/Users/admin/bundletool.jar"


def check_dependencies():
    try:
        subprocess.run(["adb", "version"], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        print("✅ ADB 已安装")
    except (subprocess.CalledProcessError, FileNotFoundError):
        raise EnvironmentError("❌ 未找到 adb，请确保已安装并配置到 PATH")

    try:
        subprocess.run(["java", "-version"], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        print("✅ Java 已安装")
    except (subprocess.CalledProcessError, FileNotFoundError):
        raise EnvironmentError("❌ 未找到 Java，请确保已安装并配置到 PATH")

    if not os.path.isfile(BUNDLETOOL_JAR):
        raise FileNotFoundError(f"❌ bundletool jar 文件不存在: {BUNDLETOOL_JAR}")

    try:
        result = subprocess.run(
            ["java", "-jar", BUNDLETOOL_JAR, "version"],
            check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
        )
        print(f"✅ bundletool 可用，版本: {result.stdout.strip()}")
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(f"❌ bundletool 运行失败: {exc.stderr.strip()}")


def get_connected_devices():
    try:
        result = subprocess.run(["adb", "devices"], capture_output=True, text=True, check=True)
    except subprocess.CalledProcessError as exe:
        raise RuntimeError("ADB 命令执行失败，请检查 ADB 是否安装并正常运行") from exe

    devices = []
    for line in result.stdout.splitlines():
        stripped_line = line.strip()
        if stripped_line == "List of devices attached":
            continue
        if stripped_line.endswith("device"):
            parts = stripped_line.split()
            if len(parts) >= 1:
                devices.append(parts[0])

    if not devices:
        raise RuntimeError("未检测到连接的 Android 设备，请检查设备是否连接")
    return devices


def run_command(cmd, desc=""):
    print(f"🔧 正在执行：{desc or ' '.join(cmd)}")
    try:
        subprocess.run(cmd, check=True)
        print(f"✅ 成功：{desc or ' '.join(cmd)}")
    except subprocess.CalledProcessError as exe:
        raise RuntimeError(f"❌ 执行失败：{' '.join(cmd)}\n错误信息：{exe.stderr}")


def generate_apks(aab_path, output_apks_path, bundletool_jar, keystore_path=None, ks_key_alias=None, ks_pass=None,
                  key_pass=None):
    print("📦 正在生成 APKS 文件...")
    cmd = [
        "java", "-jar", bundletool_jar,
        "build-apks",
        f"--bundle={aab_path}",
        f"--output={output_apks_path}",
        "--overwrite",
        "--mode=universal"
    ]
    if all([keystore_path, ks_key_alias, ks_pass, key_pass]):
        cmd += [
            f"--ks={keystore_path}",
            f"--ks-key-alias={ks_key_alias}",
            f"--ks-pass=pass:{ks_pass}",
            f"--key-pass=pass:{key_pass}"
        ]
    run_command(cmd, "生成 APKS")


def install_apks(apks_path, device_id, bundletool_jar):
    print(f"📲 正在安装到设备：{device_id}")
    cmd = [
        "java", "-jar", bundletool_jar,
        "install-apks",
        f"--apks={apks_path}",
        f"--device-id={device_id}"
    ]
    run_command(cmd, f"安装到设备 {device_id}")


def extract_apk_info_from_apks(apks_path):
    """
    从 APKS 文件中提取第一个 APK 的信息：包名、应用名、版本号，target_sdk版本号。
    """
    if not zipfile.is_zipfile(apks_path):
        raise ValueError(f"❌ 文件不是有效的 ZIP/APKS: {apks_path}")
    with zipfile.ZipFile(apks_path, 'r') as z:
        apk_files = [f for f in z.namelist() if f.endswith('.apk')]
        if not apk_files:
            raise RuntimeError("❌ APKS 中未找到任何 APK 文件")
        with tempfile.NamedTemporaryFile(suffix=".apk", delete=False) as tmp_apk:
            tmp_apk.write(z.read(apk_files[0]))
            tmp_apk_path = tmp_apk.name

    apk = APK(tmp_apk_path)
    package_name = apk.package
    app_name = apk.get_app_name()
    version_name = apk.get_androidversion_name()
    version_code = apk.get_androidversion_code()
    target_sdk_version = apk.get_target_sdk_version()
    print(f"📛 包名: {package_name}")
    print(f"📌 应用名称: {app_name}")
    print(f"📌 版本号: {version_name}")
    print(f"📌 GooglePlay内部版本号，versionCode是: {version_code}")
    if eval(target_sdk_version) >= 35:
        print(f"📌 targetSdkVersion版本是: {target_sdk_version}")
    else:
        print(f"⚠️ targetSdkVersion小于35，当前版本是:{target_sdk_version}")
    return {
        "package_name": package_name,
        "app_name": app_name,
        "version_name": version_name,
        "target_sdk_version": target_sdk_version,
        "version_code": version_code
    }


def uninstall_apk(package_name):
    uninstall_command = ["adb", "uninstall", package_name]
    print(f"正在执行卸载命令: adb uninstall {package_name}")
    result = subprocess.run(uninstall_command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    time.sleep(0.5)
    print("✅ 卸载成功" if b"Success" in result.stdout else f"⚠️ 卸载失败或未安装：{result.stdout.decode().strip()}")


def get_launcher_activity(package_name):
    """获取应用主启动 Activity"""
    try:
        result = subprocess.run(
            ["adb", "shell", "cmd", "package", "resolve-activity", "--brief", package_name],
            stdout=subprocess.PIPE, text=True, check=True
        )
        lines = result.stdout.strip().splitlines()
        return lines[1] if len(lines) >= 2 else None
    except subprocess.CalledProcessError:
        return None


def start_app(package_name):
    print("🚀 尝试启动应用...")

    # 优先尝试主启动 Activity
    launcher = get_launcher_activity(package_name)
    if launcher:
        adb_command = f"adb shell am start -n {launcher}"
        print(f"正在执行命令:{adb_command}")
        result = subprocess.run(adb_command, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print("采用第1种获取主Activity方式启动")
        if result.returncode == 0:
            return

    dumpsys_output = subprocess.run(
        ["adb", "shell", "dumpsys", "package", package_name],
        capture_output=True, text=True
    ).stdout
    splash_match = re.search(rf"{re.escape(package_name)}/([\w.]*Splash[\w.]*)", dumpsys_output)
    if splash_match:
        splash_activity = splash_match.group(1)
        activity_path = f"{package_name}/{splash_activity}"
        adb_command = ["adb", "shell", "am", "start", "-n", activity_path]
        print(f"✨ 启动命令: {' '.join(adb_command)}")
        subprocess.run(adb_command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print("采用第2种splash方式启动")
    else:
        print("⚠️ 未找到 SplashActivity，尝试使用 monkey 启动应用...")
        monkey_cmd = ["adb", "shell", "monkey", "-p", package_name, "-c", "android.intent.category.LAUNCHER", "1"]
        print(f"✨ 启动命令: {' '.join(monkey_cmd)}")
        subprocess.run(monkey_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print("采用第3种monkey方式启动")


def find_latest_aab(directory):
    directory = os.path.normpath(directory)
    if not os.path.isdir(directory):
        raise FileNotFoundError(f"❌ 指定目录不存在: {directory}")
    aab_files = [
        os.path.join(directory, f)
        for f in os.listdir(directory)
        if f.endswith(".aab") and os.path.isfile(os.path.join(directory, f))
    ]
    if not aab_files:
        raise FileNotFoundError(f"❌ 未找到任何 AAB 文件于目录: {directory}")
    latest_file = max(aab_files, key=os.path.getmtime)
    latest_time = datetime.fromtimestamp(os.path.getmtime(latest_file))
    print(f"📦 找到最新 AAB：{latest_file}（更新时间: {latest_time}）")
    return latest_file


def install_aab(aab_path=None, directory="/Users/admin/Downloads", keystore_path=None, ks_key_alias=None, ks_pass=None,
                key_pass=None):
    print("🚀 启动安装流程")
    aab_path = aab_path or find_latest_aab(directory)
    if not os.path.isfile(aab_path):
        raise FileNotFoundError(f"❌ 找不到 AAB 文件: {aab_path}")

    check_dependencies()
    devices = get_connected_devices()
    print(f"📱 已连接设备: {devices}")

    with tempfile.TemporaryDirectory() as tmp_dir:
        apks_path = os.path.join(tmp_dir, "output.apks")
        generate_apks(
            aab_path,
            apks_path,
            bundletool_jar=BUNDLETOOL_JAR,
            keystore_path=keystore_path,
            ks_key_alias=ks_key_alias,
            ks_pass=ks_pass,
            key_pass=key_pass
        )

        try:
            apk_info = extract_apk_info_from_apks(apks_path)
            package_name = apk_info["package_name"]
            uninstall_apk(package_name)
        except Exception as exe:
            print(f"⚠️ 获取包名或卸载失败：{exe}")
            package_name = None

        for device in devices:
            install_apks(apks_path, device, bundletool_jar=BUNDLETOOL_JAR)

        if package_name:
            start_app(package_name)

        print(f"🧹 清理临时目录: {tmp_dir}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="📦 使用 bundletool 安装 AAB 到 Android 设备")
    parser.add_argument("--aab", help="AAB 文件路径（可选）", default=None)
    parser.add_argument("--directory", help="搜索 AAB 的目录（默认: /Users/admin/Downloads）",
                        default="/Users/admin/Downloads")

    # TODO 默认签名文件
    parser.add_argument("--keystore", help="签名 keystore 文件（可选）", default=None)
    parser.add_argument("--ks-key-alias", help="keystore 别名（可选）", default=None)
    parser.add_argument("--ks-pass", help="keystore 密码（可选）", default=None)
    parser.add_argument("--key-pass", help="key 密码（可选）", default=None)

    # # launchar项目签名文件
    # parser.add_argument("--keystore", help="签名 keystore 文件（可选）",
    #                     default=r"/Users/admin/Downloads/AppFlowWallsLauncherDebug.appflowwallslauncherdebug.jks")
    # parser.add_argument("--ks-key-alias", help="keystore 别名（可选）", default="AppFlowWallsLauncherDebug")
    # parser.add_argument("--ks-pass", help="keystore 密码（可选）", default="AppFlowWallsLauncherDebug")
    # parser.add_argument("--key-pass", help="key 密码（可选）", default="AppFlowWallsLauncherDebug")

    args = parser.parse_args()
    try:
        install_aab(
            aab_path=args.aab,
            directory=args.directory,
            keystore_path=args.keystore,
            ks_key_alias=args.ks_key_alias,
            ks_pass=args.ks_pass,
            key_pass=args.key_pass
        )
        print("🎉 AAB 安装完成！")
    except Exception as e:
        print(f"💥 出错了: {e}")
