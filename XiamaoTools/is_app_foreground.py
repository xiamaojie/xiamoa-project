"""通过包名检查app是否在前台运行"""
import subprocess
import re
import time

def run_adb_command(cmd):
    """执行 adb 命令并返回输出"""
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    if result.returncode == 0:
        return result.stdout
    return ""


def get_foreground_package():
    """获取当前前台运行的 App 包名"""

    # 方法1: dumpsys window (最稳定, Android 12/13/14)
    cmd = "adb shell dumpsys window"
    output = run_adb_command(cmd)
    for line in output.splitlines():
        if "mCurrentFocus" in line or "mFocusedApp" in line:
            match = re.search(r' ([a-zA-Z0-9._]+)/', line)
            if match:
                return match.group(1)

    # 方法2: dumpsys activity top (部分机型)
    cmd = "adb shell dumpsys activity top"
    output = run_adb_command(cmd)
    for line in output.splitlines():
        if "ACTIVITY" in line:
            match = re.search(r' ([a-zA-Z0-9._]+)/', line)
            if match:
                return match.group(1)

    # 方法3: dumpsys activity activities (老版本 Android 9/10)
    cmd = "adb shell dumpsys activity activities"
    output = run_adb_command(cmd)
    for line in output.splitlines():
        if "mResumedActivity" in line:
            match = re.search(r' ([a-zA-Z0-9._]+)/', line)
            if match:
                return match.group(1)

    return None


def is_app_running(package_name):
    """检查 App 是否在运行"""
    cmd = "adb shell ps"
    output = run_adb_command(cmd)
    for line in output.splitlines():
        if package_name in line:
            return True
    return False


def is_app_foreground(package_name):
    """判断指定包名的 App 是否在前台"""
    if not is_app_running(package_name):
        return False

    foreground_pkg = get_foreground_package()
    if not foreground_pkg:
        print("无法获取前台应用")
        return False

    return package_name == foreground_pkg


if __name__ == "__main__":
    while True:
        print("检查中...")
        time.sleep(1)
        # package = "com.hotpotgames.happysave.global"
        package = "com.deama.gold.shortreel"
        print(f"正在检查 App: {package}")
        if is_app_foreground(package):
            print(f"✅ {package} 当前在前台运行")
        else:
            print(f"❌ {package} 不在前台")
