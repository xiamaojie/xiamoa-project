import os
import glob
import time
import subprocess
from androguard.core.apk import APK
import uiautomator2 as u2
from loguru import logger

# 禁用androguard的debug日志
logger.remove()
logger.add(lambda msg: None, level="ERROR")

class AppAutoUpdate:
    def __init__(self, apk_directory):
        self.apk_directory = apk_directory
        self._get_device_serial()  # 初始化时获取设备序列号
        self.d = u2.connect(self.device_serial)  # 连接设备
        self.apk_path = self.get_apk_path()
        self.package_name = self.get_package_name()

    def _get_device_serial(self):
        """获取设备序列号并检查连接状态"""
        output = subprocess.check_output(["adb", "devices"]).decode("utf-8").strip().split("\n")
        if len(output) <= 1 or not output[1].strip():
            raise Exception("未检测到连接的设备。请检查ADB连接。")
        self.device_serial = output[1].split("\t")[0]
        print(f"设备序列号: {self.device_serial}")

    def get_apk_path(self):
        """获取最新apk文件路径"""
        apk_files = glob.glob(os.path.join(self.apk_directory, "*.apk"))
        if not apk_files:
            raise FileNotFoundError("未找到apk文件")
        latest_file = max(apk_files, key=os.path.getctime)
        print(f"最新安装包路径: {latest_file}")
        print(f"修改时间: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(os.path.getctime(latest_file)))}")
        return latest_file

    def get_app_name(self):
        """获取应用名称"""
        return APK(self.apk_path).get_app_name()

    def get_package_name(self):
        """获取包名"""
        package = APK(self.apk_path).get_package()
        print(f"安装包包名: {package}")
        return package

    def uninstall_apk(self):
        """卸载应用"""
        subprocess.run(f"adb shell pm clear {self.package_name}", shell=True)
        result = subprocess.run(f"adb uninstall {self.package_name}",
                              shell=True,
                              stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE)
        print("卸载成功" if b"Success" in result.stdout else "卸载失败")

    def install_apk(self):
        """安装应用"""
        result = subprocess.run(f"adb install -r {self.apk_path}",
                              shell=True,
                              stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE)
        print("安装成功" if b"Success" in result.stdout else f"安装失败: {result.stderr.decode()}")

    def open_notice_permission(self):
        """授予通知权限"""
        result = subprocess.run(f"adb shell pm grant {self.package_name} android.permission.POST_NOTIFICATIONS",
                              shell=True,
                              stdout=subprocess.PIPE,
                              stderr=subprocess.PIPE)
        print("权限授予成功" if result.returncode == 0 else f"权限授予失败: {result.stderr.decode()}")

    def start_app(self):
        """启动应用"""
        subprocess.run(f"adb shell monkey -p {self.package_name} -c android.intent.category.LAUNCHER 1",
                       shell=True,
                       stdout=subprocess.DEVNULL,
                       stderr=subprocess.DEVNULL)
        print(f"已启动应用: {self.get_app_name()}")

    def handle_popup(self, text="允许", timeout=10):
        """
        处理弹窗点击（仅根据文本）
        :param text: 需要点击的按钮文本
        :param timeout: 查找元素超时时间（秒）
        """
        try:
            if self.d(text=text).exists(timeout=timeout):
                self.d(text=text).click()
                print(f"成功点击 [{text}] 按钮")
            else:
                print(f"未检测到 [{text}] 按钮，无需处理")
        except Exception as e:
            print(f"弹窗处理失败: {str(e)}")


def run():
    try:
        app = AppAutoUpdate("/Users/admin/Downloads")
        app.uninstall_apk()
        app.install_apk()
        app.start_app()
        time.sleep(1)
        app.handle_popup("允许")  # 处理权限弹窗
    except Exception as e:
        print(f"程序执行出错: {str(e)}")

if __name__ == '__main__':
    run()