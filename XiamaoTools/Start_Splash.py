import re
import subprocess


def get_splash_activity(package_name):
    """获取应用的 Splash 启动 Activity"""
    try:
        # 获取 package 信息
        result = subprocess.run(
            ["adb", "shell", "dumpsys", "package", package_name],
            capture_output=True, text=True
        )

        if result.returncode != 0 or not result.stdout:
            print("无法获取应用信息，请检查 ADB 连接或包名是否正确。")
            return None

        # 使用正则匹配 Splash Activity
        match = re.search(r"com\.[\w.]+/([\w.]*Splash\w*)", result.stdout)
        if match:
            splash_activity = match.group(1)
            print(f"找到 Splash 入口 Activity: {splash_activity}")
            return splash_activity
        else:
            print("未找到 Splash 入口 Activity，可能应用没有显式的 Splash 页面。")
            return None
    except Exception as e:
        print(f"发生错误: {e}")
        return None


def start_app(package_name):
    """启动应用的 Splash Activity"""
    splash_activity = get_splash_activity(package_name)
    if splash_activity:
        activity_path = f"{package_name}/{splash_activity}"
        print(f"尝试启动应用的 Splash 页面: {activity_path}")
        subprocess.run(["adb", "shell", "am", "start", "-n", activity_path])
    else:
        print("无法启动应用的 Splash 页面，请检查应用是否正确安装。")


if __name__ == "__main__":
    package_name = "com.hotpotgames.happysave.global"
    start_app(package_name)
