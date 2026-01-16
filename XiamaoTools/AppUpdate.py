

import glob
import os
import re
import subprocess
import time

from androguard.core.apk import APK
from loguru import logger

# 禁用androguard的debug日志
logger.remove()
logger.add(lambda msg: None, level="ERROR")

def get_devices_name():
    # 断掉无线连接
    os.system("adb disconnect")
    devices = subprocess.check_output(["adb", "devices"]).decode("utf-8").strip().split("\n")
    if len(devices) <= 1 or not devices[1].strip():
        print("未检测到连接的设备。请检查ADB连接。")
        return False
    else:
        device_name = devices[1].strip().split()[0]  # 取第一个元素（设备名）
        print("获取到的设备名是:{}".format(device_name))
        # 设置自动锁屏时间为 30 分钟
        os.system("adb shell settings put system screen_off_timeout 1800000")
        return True

def turn_up_the_volume(times: int = 15, delay: float = 0.1):
    """
    调高手机音量,兼容测试音频广告，忘记测试机开启音量，导致一致不弹音频广告的场景

    :param times: 按音量加的次数（默认15次）
    :param delay: 每次按之间的延时秒数（默认0.1秒）
    """
    for i in range(times):
        subprocess.run(["adb", "shell", "input", "keyevent", "KEYCODE_VOLUME_UP"])
        time.sleep(delay)
    print(f"手机音量已调高至：{times}，具备音频广告播放条件")

class AppAutoUpdate:
    def __init__(self, apk_directory):
        print("调用请输入.apk文件的所在的目录:")
        self.apk_directory = apk_directory
        self.apk_path = self.get_apk_path()  # 在初始化时获取apk路径
        self.package_name = self.get_package_name()  # 在初始化时获取包名


    def get_apk_path(self):
        """获取apk文件路径"""
        apk_files = glob.glob(os.path.join(self.apk_directory, "*.apk"))
        if not apk_files:
            print("未找到apk文件")
            return None
        latest_file_path = max(apk_files, key=os.path.getctime)
        print("最新安装包的文件安装路径是:{}".format(latest_file_path))
        modification_time = time.strftime(
            '%Y-%m-%d %H:%M:%S', time.localtime(os.stat(latest_file_path).st_mtime)
        ) if os.path.exists(latest_file_path) else "文件未找到"
        print(f"最新安装包的文件下载时间是: {modification_time}")
        return latest_file_path

    def get_app_name(self):
        """获取应用名称"""
        if not self.apk_path:
            return None
        apk = APK(self.apk_path)
        app_name = apk.get_app_name()
        return app_name

    def get_package_name(self):
        """获取包名"""
        if not self.apk_path:
            return None
        apk = APK(self.apk_path)
        package_name = apk.get_package()
        print("安装包包名是:{}".format(package_name))
        return package_name

    def get_app_version(self):
        """获取应用版本号"""
        if not self.apk_path:
            return None
        apk = APK(self.apk_path)
        version = apk.get_androidversion_name()
        return version

    def uninstall_apk(self):
        """通过包名卸载APP"""
        if not self.package_name:
            print("未获取到包名，无法卸载")
            return
        # 先清除数据再卸载，怕有缓存保险些
        adb_command1 = f'adb shell pm clear "{self.package_name}"'
        print("正在执行命令:{}".format(adb_command1))
        subprocess.run(adb_command1, shell=True)
        adb_command2 = f'adb uninstall "{self.package_name}"'
        print("正在执行命令:{}".format(adb_command2))
        subprocess.run(adb_command2, shell=True)

    def install_apk(self):
        """安装apk"""
        if not self.apk_path:
            print("未找到apk文件，无法安装")
            return
        adb_command3 = f'adb install -r "{self.apk_path}"'
        print("正在执行命令:{}".format(adb_command3))
        install_result = subprocess.run(adb_command3, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if "Success" in install_result.stdout.decode('utf-8'):
            print("安装成功")
        else:
            print("安装失败，错误信息：", install_result.stderr.decode('utf-8'))

    def open_notice_permission(self):
        """打开通知权限，该方法自己根据业务需要决定是否开启，测试的时候尽量安装成功后启动APP前调用给予通知权限"""
        print("正在授予通知权限...")
        permission_command = f'adb shell pm grant "{self.package_name}" android.permission.POST_NOTIFICATIONS'
        permission_result = subprocess.run(permission_command, shell=True, stdout=subprocess.PIPE,
                                           stderr=subprocess.PIPE)

        if permission_result.returncode == 0:
            print(f"成功授予通知权限: {self.package_name}")
        else:
            print(f"授予通知权限失败，请检查包名是否正确。错误信息：{permission_result.stderr.decode('utf-8')}")

    def start_app(self):
        """启动应用，该方法只能启动正常有icon的APP"""
        print("正在启动应用...")
        if not self.package_name:
            print("未获取到包名，无法启动")
            return
        launch_command = f'adb shell monkey -p "{self.package_name}" -c android.intent.category.LAUNCHER 1'
        result = subprocess.run(launch_command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if result.returncode == 0:
            print(f"成功启动应用: {self.get_app_name()}")
            print(f"应用版本号是: {self.get_app_version()}")
        else:
            print(f"启动失败，请检查包名是否正确。错误信息：{result.stderr.decode('utf-8')}")

    def get_launcher_activity(self):
        """获取应用主启动 Activity"""
        try:
            result = subprocess.run(
                ["adb", "shell", "cmd", "package", "resolve-activity", "--brief", self.package_name],
                stdout=subprocess.PIPE, text=True, check=True
            )
            lines = result.stdout.strip().splitlines()
            return lines[1] if len(lines) >= 2 else None
        except subprocess.CalledProcessError:
            return None

    def start_app_v2(self):
        """启动应用第2版，优先级：主启动 Activity > SplashActivity > Monkey"""
        print("正在启动应用...")
        if not self.package_name:
            print("未获取到包名，无法启动")
            return

        # 优先尝试主启动 Activity
        launcher = self.get_launcher_activity()
        if launcher:
            adb_command = f"adb shell am start -n {launcher}"
            print(f"正在执行命令:{adb_command}")
            result = subprocess.run(adb_command, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if result.returncode == 0:
                print(f"成功启动应用: {self.get_app_name()}")
                print(f"APK应用版本号是: {self.get_app_version()}")
                return

        # 如果主启动 Activity 失败，尝试 SplashActivity
        dumpsys_output = subprocess.run(
            ["adb", "shell", "dumpsys", "package", self.package_name],
            capture_output=True, text=True
        ).stdout

        splash_match = re.search(r"com\.[\w.]+/([\w.]*Splash\w*)", dumpsys_output)
        if splash_match:
            splash_activity = splash_match.group(1)
            activity_path = f"{self.package_name}/{splash_activity}"
            adb_command = f"adb shell am start -n {activity_path}"
            print(f"正在执行命令:{adb_command}")
            result = subprocess.run(adb_command, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if result.returncode == 0:
                print(f"成功启动应用: {self.get_app_name()}")
                print(f"APK应用版本号是: {self.get_app_version()}")
                return

        # 如果 SplashActivity 也失败，尝试 Monkey 启动
        print("未找到主启动 Activity 或 SplashActivity，尝试使用 Monkey 启动应用...")
        launch_command = f'adb shell monkey -p "{self.package_name}" -c android.intent.category.LAUNCHER 1'
        print(f"正在执行命令:{launch_command}")
        result = subprocess.run(launch_command, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        if result.returncode != 0:
            print(f"启动失败，请检查包名是否正确。错误信息：{result.stderr.decode('utf-8')}")
            return
        else:
            print(f"成功启动应用: {self.get_app_name()}")
            print(f"APK应用版本号是: {self.get_app_version()}")

    def force_stop_app(self):
        """停止APP，解决首次启动Shot_Screen录屏参数的不生效的需要停止后重启的问题"""
        time.sleep(3)
        force_command = f"adb shell am force-stop {self.package_name}"
        subprocess.run(force_command, shell=True, stdout=subprocess.PIPE,
                       stderr=subprocess.PIPE)

def run():
    is_connect = get_devices_name()
    if is_connect:
        app_directory = "/Users/admin/Downloads"
        app = AppAutoUpdate(app_directory)
        app.uninstall_apk()
        app.install_apk()
        app.start_app_v2()
        # 自动开启声音
        # turn_up_the_volume()
        # 停止后重新启动，解决录屏参数需要停止后重启才生效的问题
        # app.force_stop_app()
        # app.start_app_v2()

if __name__ == '__main__':
    run()
