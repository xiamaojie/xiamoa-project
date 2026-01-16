import os
import subprocess
import tempfile
from datetime import datetime
# 后续可以优化为获取到apks后，通过androguard解析出包名信息
# ✨ 定义 bundletool 的路径，确保版本一致
BUNDLETOOL_JAR = "/Users/admin/bundletool.jar"


def check_dependencies():
    """
    检查运行脚本所需依赖是否齐全：
    - ADB 是否安装并配置在环境变量中
    - Java 是否安装
    - bundletool jar 文件是否存在
    - bundletool 是否能正常执行
    """
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
    """
    获取当前连接的 Android 设备列表（通过 adb devices）
    返回设备序列号列表
    """
    result = subprocess.run(["adb", "devices"], capture_output=True, text=True, check=True)
    devices = [line.split()[0] for line in result.stdout.splitlines() if line.strip().endswith("device")]
    if not devices:
        raise RuntimeError("❌ 未检测到连接的 Android 设备")
    return devices


def run_command(cmd, desc=""):
    """
    封装 subprocess.run 调用，用于统一处理命令执行和错误输出
    :param cmd: 命令数组
    :param desc: 执行描述（用于日志）
    """
    print(f"🔧 正在执行：{desc or ' '.join(cmd)}")
    try:
        subprocess.run(cmd, check=True)
        print(f"✅ 成功：{desc or ' '.join(cmd)}")

    except subprocess.CalledProcessError as exe:
        raise RuntimeError(f"❌ 执行失败：{' '.join(cmd)}\n错误信息：{exe.stderr}")


def generate_apks(aab_path, output_apks_path, bundletool_jar, keystore_path=None, ks_key_alias=None, ks_pass=None,
                  key_pass=None):
    """
    使用 bundletool 生成 APKS 文件
    :param aab_path: AAB 文件路径
    :param output_apks_path: 输出 APKS 路径
    :param bundletool_jar: bundletool jar 文件路径
    :param keystore_path: 签名证书路径
    :param ks_key_alias: 密钥别名
    :param ks_pass: keystore 密码
    :param key_pass: 密钥密码
    """
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
    """
    安装 APKS 到指定设备
    :param apks_path: APKS 文件路径
    :param device_id: 设备 ID
    :param bundletool_jar: bundletool jar 路径
    """
    print(f"📲 正在安装到设备：{device_id}")
    cmd = [
        "java", "-jar", bundletool_jar,
        "install-apks",
        f"--apks={apks_path}",
        f"--device-id={device_id}"
    ]
    run_command(cmd, f"安装到设备 {device_id}")


def find_latest_aab(directory):
    """
    在指定目录中查找最新的 .aab 文件（按修改时间排序）
    :param directory: 查找目录
    :return: 最新 AAB 文件路径
    """
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
    """
    主流程：安装 AAB 到设备
    :param aab_path: AAB 文件路径（可选）
    :param directory: 默认搜索 AAB 的目录
    :param keystore_path: 签名证书路径
    :param ks_key_alias: 密钥别名
    :param ks_pass: keystore 密码
    :param key_pass: 密钥密码
    """
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

        for device in devices:
            install_apks(apks_path, device, bundletool_jar=BUNDLETOOL_JAR)

        print(f"🧹 清理临时目录: {tmp_dir}")


def uninstall_apk():
    """卸载应用"""
    uninstall__command = "adb uninstall com.hotpotgames.happysave.global"
    result = subprocess.run(uninstall__command,
                            shell=True,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE)
    print(f"正在执行命令: {uninstall__command}")
    print("卸载成功" if b"Success" in result.stdout else "卸载失败")


if __name__ == "__main__":
    import argparse

    uninstall_apk()
    parser = argparse.ArgumentParser(description="📦 使用 bundletool 安装 AAB 到 Android 设备")
    parser.add_argument("--aab", help="AAB 文件路径（可选）", default=None)
    parser.add_argument("--directory", help="搜索 AAB 的目录（默认: /Users/admin/Downloads）",
                        default="/Users/admin/Downloads")
    parser.add_argument("--keystore", help="签名 keystore 文件（可选）", default=None)
    parser.add_argument("--ks-key-alias", help="keystore 别名（可选）", default=None)
    parser.add_argument("--ks-pass", help="keystore 密码（可选）", default=None)
    parser.add_argument("--key-pass", help="key 密码（可选）", default=None)
    # parser.add_argument("--keystore", help="签名 keystore 文件（可选）", default=r"/Users/admin/Downloads/browserhdoaiwai.jks")
    # parser.add_argument("--ks-key-alias", help="keystore 别名（可选）", default="browserhdoaiwai")
    # parser.add_argument("--ks-pass", help="keystore 密码（可选）", default="browserhdoaiwai")
    # parser.add_argument("--key-pass", help="key 密码（可选）", default="browserhdoaiwai")

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
