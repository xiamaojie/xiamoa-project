import glob
import os
import re
import subprocess
import time

from androguard.core.apk import APK
from loguru import logger

logger.remove()
logger.add(lambda msg: None, level="ERROR")


def run_cmd(cmd):
    """ 执行 shell 命令并返回输出 """
    result = subprocess.run(cmd, capture_output=True, text=True)
    return result.stdout.strip()


def get_adb_devices():
    """ 获取已连接设备列表(USB & 无线) """
    # 重启 adb 服务
    os.system("adb kill-server")
    devices_output = run_cmd(["adb", "devices"]).split("\n")[1:]
    devices = [line.split()[0] for line in devices_output if line.strip() and "device" in line]

    wireless_devices = [d for d in devices if ":" in d]
    wired_devices = [d for d in devices if ":" not in d]

    return wired_devices, wireless_devices


def connect_adb_wireless(device):
    """ 连接 ADB 无线 """
    _, wireless_devices = get_adb_devices()
    if wireless_devices:
        print("首次运行需要关闭手机vpn")
        print(f"✅ 已检测到无线设备: {wireless_devices[0]}")
        return wireless_devices[0]

    print(f"🔄 设备 {device} 尝试开启 ADB tcpip 5555 ...")
    # print("如果获取到的手机ip不是以192开头的，请关闭手机上的vpn软件，重新运行脚本")
    run_cmd(["adb", "-s", device, "tcpip", "5555"])
    time.sleep(3)

    ip_address = run_cmd(["adb", "-s", device, "shell", "ip route | awk '{print $9}'"]).split("\n")[0]
    if not ip_address:
        print(f"❌ 无法获取设备 {device} 的 IP")
        return None
    # 判断手机ip是否以192开头，是192开头则代表在同一个局域网，不是192，则代表开了vpn，不在一个局域网，结束运行
    if not ip_address.startswith("192."):
        print("获取到的手机ip不是以192开头的，替换使用有线设备连接。使用无线连接请关闭手机上的vpn软件，重新尝试运行")
        return
    wireless_device = f"{ip_address}:5555"
    print(f"🔗 尝试连接无线 ADB: adb connect {wireless_device}")

    run_cmd(["adb", "connect", wireless_device])

    if wireless_device in run_cmd(["adb", "devices"]):
        print(f"✅ 成功无线连接至: {wireless_device}")
        return wireless_device
    return None


def get_devices_name():
    """ 获取 ADB 设备 """
    wired_devices, wireless_devices = get_adb_devices()

    if wireless_devices:
        return wireless_devices[0]
    elif wired_devices:
        usb_device = wired_devices[0]
        print(f"🖥️ 检测到有线设备: {usb_device}，尝试开启无线 ADB ...")
        wireless_device = connect_adb_wireless(usb_device)
        return wireless_device if wireless_device else usb_device

    print("❌ 未检测到任何 ADB 设备，请检查连接")
    return None


class AppAutoUpdate:
    def __init__(self, apk_directory, device_name):
        print("调用请输入.apk文件的所在的目录:")
        self.device_name = device_name
        self.apk_directory = apk_directory
        self.apk_path = self.get_apk_path()
        self.package_name = self.get_package_name()

    def get_apk_path(self):
        apk_files = glob.glob(os.path.join(self.apk_directory, "*.apk"))
        if not apk_files:
            print("未找到apk文件")
            return None
        latest_file_path = max(apk_files, key=os.path.getctime)
        print(f"最新安装包的文件安装路径是: {latest_file_path}")
        modification_time = time.strftime('%Y-%m-%d %H:%M:%S',
                                          time.localtime(os.stat(latest_file_path).st_mtime))
        print(f"最新安装包的文件下载时间是: {modification_time}")
        return latest_file_path

    def get_package_name(self):
        if not self.apk_path:
            return None
        package_name = APK(self.apk_path).get_package()
        print(f"安装包包名是: {package_name}")
        return package_name

    def uninstall_apk(self):
        """ 修复指定设备名 """
        if not self.package_name:
            print("未获取到包名，无法卸载")
            return
        adb_command1 = f'adb -s {self.device_name} shell pm clear "{self.package_name}"'
        print(f"正在执行命令: {adb_command1}")
        subprocess.run(adb_command1, shell=True)
        adb_command2 = f'adb -s {self.device_name} uninstall "{self.package_name}"'
        print(f"正在执行命令: {adb_command2}")
        subprocess.run(adb_command2, shell=True)

    def install_apk(self):
        """ 修复指定设备名 """
        if not self.apk_path:
            print("未找到apk文件，无法安装")
            return
        adb_command3 = f'adb -s {self.device_name} install -r "{self.apk_path}"'
        print(f"正在执行命令: {adb_command3}")
        install_result = subprocess.run(adb_command3, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if "Success" in install_result.stdout.decode():
            print("✅ 安装成功")
        else:
            print(f"❌ 安装失败: {install_result.stderr.decode()}")

    def start_app_v2(self):
        """ 修复指定设备名 """
        print("正在启动应用...")
        if not self.package_name:
            print("未获取到包名，无法启动")
            return

        dumpsys_output = subprocess.run(
            f'adb -s {self.device_name} shell dumpsys package {self.package_name}',
            shell=True, capture_output=True, text=True
        ).stdout
        splash_match = re.search(r"com\.[\w.]+/([\w.]*Splash\w*)", dumpsys_output)

        if splash_match:
            splash_activity = splash_match.group(1)
            adb_command = f'adb -s {self.device_name} shell am start -n {self.package_name}/{splash_activity}'
            print(f"正在执行命令: {adb_command}")
            subprocess.run(adb_command, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            print("未找到 SplashActivity，尝试使用 monkey 启动...")
            launch_command = f'adb -s {self.device_name} shell monkey -p "{self.package_name}" -c android.intent.category.LAUNCHER 1'
            print(f"正在执行命令: {launch_command}")
            subprocess.run(launch_command, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def open_notice_permission(self):
        """ 修复指定设备名 """
        print("正在授予通知权限...")
        permission_command = f'adb -s {self.device_name} shell pm grant "{self.package_name}" android.permission.POST_NOTIFICATIONS'
        permission_result = subprocess.run(permission_command, shell=True, stdout=subprocess.PIPE,
                                           stderr=subprocess.PIPE)

        if permission_result.returncode == 0:
            print(f"✅ 成功授予通知权限: {self.package_name}")
        else:
            print(f"❌ 授予通知权限失败，错误信息: {permission_result.stderr.decode()}")


def run():
    device_name = get_devices_name()
    if device_name:
        print(f"✅ 最终使用设备: {device_name}")
        app_directory = "/Users/admin/Downloads"
        app = AppAutoUpdate(app_directory, device_name)
        app.uninstall_apk()
        app.install_apk()
        app.start_app_v2()
        # app.open_notice_permission()


if __name__ == '__main__':
    run()
