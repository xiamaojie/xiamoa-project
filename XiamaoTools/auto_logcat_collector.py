# 开启firebase日志收集,将日志保存到本地
import subprocess
import os
import datetime

# 配置日志目录
log_dir = "/Users/admin/TestLog/log_analysis"
os.makedirs(log_dir, exist_ok=True)

# 日志文件名
timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
log_filename = f"logcat_{timestamp}.logcat"
log_path = os.path.join(log_dir, log_filename)

# 目标包名
# package_name = "com.hotpotgames.happysave.global"
package_name = "com.wallpaper.launcher.live.pure.magic.desktop"

print(f"📁 日志文件路径：{log_path}")

# 检查设备连接状态
try:
    devices_output = subprocess.check_output(["adb", "devices"]).decode()
    if "device" not in devices_output.strip().split("\n")[-1]:
        print("❌ 没有检测到连接的设备，请先连接设备")
        exit(1)
except Exception as e:
    print(f"❌ 检查设备连接失败：{e}")
    exit(1)

# 检查是否开启了 Firebase 日志调试
def is_debug_logging_enabled():
    try:
        output = subprocess.check_output(["adb", "shell", "getprop", "debug.firebase.analytics.app"])
        return package_name in output.decode().strip()
    except subprocess.CalledProcessError:
        # 获取属性失败
        return False
    except Exception as exe:
        # 可选：记录日志或打印调试信息
        print(f"⚠️ 检查 Firebase 日志调试状态时发生未知错误：{exe}")
        return False


# 若未开启则设置为调试包名
if not is_debug_logging_enabled():
    try:
        subprocess.run(["adb", "shell", "setprop", "debug.firebase.analytics.app", package_name], check=True)
        print(f"⚙️ 已设置 Firebase 日志调试模式为：{package_name}")
    except subprocess.CalledProcessError:
        print("❌ 设置 debug.firebase.analytics.app 失败，请检查 adb")
        exit(1)
else:
    print(f"✅ 已开启 Firebase 日志调试模式（{package_name}）")

# 设置 FA tag 级别为 VERBOSE
try:
    subprocess.run(["adb", "shell", "setprop", "log.tag.FA", "VERBOSE"], check=True)
    subprocess.run(["adb", "shell", "setprop", "log.tag.FA-SVC", "VERBOSE"], check=True)
    print("✅ FA 日志 tag 设置为 VERBOSE")
except subprocess.CalledProcessError:
    print("❌ 设置 log.tag 失败，请检查 adb 是否连接")
    exit(1)

# 启动日志采集
try:
    with open(log_path, "wb") as log_file:
        print("🚀 开始采集日志，按 Ctrl+C 停止...\n")
        process = subprocess.Popen(
            ["adb", "logcat", "-v", "time", "-s", "FA", "FA-SVC"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )

        while True:
            line = process.stdout.readline()
            if not line:
                continue
            log_file.write(line)
            log_file.flush()
            print(line.decode(errors="ignore").rstrip())
except KeyboardInterrupt:
    print("\n🛑 日志采集已终止")
    print(f"📄 日志已保存至：{log_path}")
except Exception as e:
    print(f"❌ 采集日志失败：{e}")