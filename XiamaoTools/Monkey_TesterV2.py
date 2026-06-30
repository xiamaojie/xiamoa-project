"""
Monkey_TesterV2 功能概述（稳定性与异常采集）：
- 自动检测 adb 设备并解析应用启动 Activity，无法解析时提示手动启动以保证可交互状态
- 生成并推送 monkey 白名单，仅针对目标包进行事件注入，降低误触系统/其他应用风险
- 按速度档位配置事件节流与分布比例（触摸/滑动/缩放等），支持长稳或短时强压模式
- 并行采集崩溃与 ANR：logcat 实时抓取 FATAL/SIGSEGV/Monkey 异常，ANR 支持 traces 或 logcat 兜底
- 权限不足时自动降级：ANR 读取失败触发异步 bugreport 提取最新 ANR
- 结束后清理 logcat，输出崩溃/ANR 日志路径及关键字统计，便于回归与对比
"""

import re
import subprocess
import threading
import time
import zipfile
from datetime import datetime
from pathlib import Path

from tqdm import tqdm




def print_current_time():
    # 获取当前时间
    now = datetime.now()
    # 格式化为字符串
    formatted_time = now.strftime("%Y-%m-%d %H:%M:%S")
    return formatted_time


def is_monkey_support(option: str, device: str = None):
    try:
        cmd = ["adb"]
        if device:
            cmd += ["-s", device]
        cmd += ["shell", "monkey", "--help"]
        help_output = subprocess.check_output(cmd, timeout=4, text=True, stderr=subprocess.DEVNULL)
        return option in help_output
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
        return False


def check_adb_devices():
    """检测本地连接的 Android 设备"""
    result = subprocess.run(["adb", "devices"], stdout=subprocess.PIPE, text=True)
    lines = result.stdout.strip().splitlines()
    devices = [line.split()[0] for line in lines[1:] if "device" in line.split()]
    if not devices:
        raise RuntimeError("未检测到连接的 Android 设备")
    return devices[0]


def get_launcher_activity(package, device: str = None):
    """获取应用主启动 Activity"""
    try:
        cmd = ["adb"]
        if device:
            cmd += ["-s", device]
        cmd += ["shell", "cmd", "package", "resolve-activity", "--brief", package]
        result = subprocess.run(cmd, stdout=subprocess.PIPE, text=True, check=True)
        lines = [ln.strip() for ln in result.stdout.strip().splitlines() if ln.strip()]
        for ln in lines:
            if "/" in ln:
                return ln
        return None
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
        return None


def generate_and_push_whitelist(package, device):
    """生成白名单并推送到设备"""
    content = package.strip() + "\n"
    whitelist_file = Path("monkey_whitelist.txt")
    whitelist_file.write_text(content, encoding="utf-8")
    subprocess.run(["adb", "-s", device, "push", str(whitelist_file), "/sdcard/monkey_whitelist.txt"],
                   stdout=subprocess.DEVNULL)
    print(f"✅ 已生成白名单：/sdcard/monkey_whitelist.txt，包含：{package}")


def save_logcat_crash(log_dir, package, stop_event, start_time, device: str = None):
    """实时保存崩溃日志到文件"""
    timestamp = datetime.fromtimestamp(start_time).strftime("%Y-%m-%d_%H-%M-%S")
    filepath = Path(log_dir) / f"{timestamp}_crash.txt"
    cmd = ["adb"]
    if device:
        cmd += ["-s", device]
    cmd += ["logcat", "-v", "time"]
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, encoding="utf-8", errors="ignore")

    collecting, buffer, count, has_crash = False, [], 0, False
    max_lines = 100

    with open(filepath, "w", encoding="utf-8") as f:
        for line in proc.stdout:
            if stop_event.is_set():
                break
            match = any(x in line for x in ["FATAL EXCEPTION", "SIGSEGV", "// CRASH:", "native crash"])
            if not collecting and match:
                collecting = True
                buffer = [line]
                count = 1
                continue
            if collecting:
                buffer.append(line)
                count += 1
                if count >= max_lines or line.startswith("--------- beginning"):
                    collecting = False
                    if any([package in l for l in buffer]) or "W/Monkey" in buffer[0]:
                        f.writelines(buffer)
                        has_crash = True
                    buffer.clear()

    proc.terminate()
    proc.wait()
    if not has_crash:
        filepath.unlink(missing_ok=True)
        return None
    return filepath.resolve()


def list_anr_files_with_time(device: str = None):
    """返回 {文件名: 时间字符串}（无权限返回空字典）"""
    try:
        cmd = ["adb"]
        if device:
            cmd += ["-s", device]
        cmd += ["shell", "ls", "-l", "/data/anr/"]
        result = subprocess.check_output(cmd, stderr=subprocess.STDOUT, text=True)
        if "Permission denied" in result:
            return {}
        files = {}
        for line in result.splitlines():
            parts = line.split()
            if len(parts) >= 6:
                # 格式示例: -rw------- 1 system system 1234 2025-08-13 14:21 anr_2025...
                # 时间可能分成两列（日期 + 时间）
                date_str = parts[-3]
                time_str = parts[-2]
                filename = parts[-1]
                files[filename] = f"{date_str} {time_str}"
        return files
    except subprocess.CalledProcessError:
        return {}


def fetch_latest_anr_async(log_dir, anr_file, device: str = None):
    """最新的ANR文件（异步执行）获取方法"""

    def worker():
        print("[ANR] 启动兜底线程获取最新 ANR 文件...")
        base_cmd = ["adb"]
        if device:
            base_cmd += ["-s", device]

        subprocess.run(base_cmd + ["root"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        whoami = subprocess.run(base_cmd + ["shell", "whoami"], capture_output=True, text=True).stdout.strip()

        if whoami == "root":
            latest_file = subprocess.run(
                base_cmd + ["shell", "ls", "-t", "/data/anr/"],
                capture_output=True, text=True).stdout.strip().splitlines()[0]
            if latest_file:
                result = subprocess.run(base_cmd + ["shell", "cat", f"/data/anr/{latest_file}"],
                                        capture_output=True, text=True)
                if result.stdout:
                    with open(anr_file, "w", encoding="utf-8") as f:
                        f.write(result.stdout)
                    print(f"[DONE] 异步兜底: 最新 ANR 文件已保存到 {anr_file}")
        else:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            bugreport_path = Path(log_dir) / f"bugreport_{ts}.zip"
            subprocess.run(base_cmd + ["bugreport", str(bugreport_path)])
            with zipfile.ZipFile(bugreport_path, "r") as zip_ref:
                anr_files = sorted([name for name in zip_ref.namelist()
                                    if "anr" in name.lower() and name.endswith(".txt")], reverse=True)
                if anr_files:
                    latest_anr = zip_ref.read(anr_files[0]).decode(errors="ignore")
                    with open(anr_file, "w", encoding="utf-8") as f:
                        f.write(latest_anr)
                    print(f"[DONE] 异步兜底: 从 bugreport 提取最新 ANR 到 {anr_file}")

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()


def monitor_anr(log_dir, stop_event, start_time, package, device: str = None):
    """监控 ANR traces，并保存匹配目标包名内容（兜底逻辑异步执行）"""
    # ★ 新增：启动前获取现有文件（带时间）
    start_files = list_anr_files_with_time(device=device)
    print(f"📊 监控开始前 /data/anr/ 中已有 {len(start_files)} 个文件")
    # 移除详细文件列表输出
    # for name, ts in start_files.items():
    #     print(f"   {name}  ({ts})")

    anr_file = Path(log_dir) / f"{datetime.fromtimestamp(start_time).strftime('%Y-%m-%d_%H-%M-%S')}_anr.txt"
    matched = False
    fallback_triggered = False

    # 检查 /data/anr/ 权限
    adb_prefix = ["adb"] + (["-s", device] if device else [])
    try:
        subprocess.run(
            adb_prefix + ["shell", "ls", "/data/anr"],
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=5, text=True
        )
        use_logcat = False
        print("✅ 检测到 /data/anr/ 访问权限，使用 traces 文件监控 ANR")
    except subprocess.CalledProcessError as e:
        if "Permission denied" in str(e.stderr):
            print("[ANR] 无 /data/anr/ 访问权限，切换到 logcat 方式监控 ANR")
            use_logcat = True
        else:
            print(f"[ANR] 检查 /data/anr/ 权限失败：{str(e.stderr)}，跳过 ANR 监控")
            return None

    if use_logcat:
        proc = subprocess.Popen(
            adb_prefix + ["logcat", "-v", "long"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, encoding="utf-8", errors="ignore"
        )
        buffer, collecting, count = [], False, 0
        max_lines = 10
        anr_indicators = ["ANR in", "Input dispatching timed out", "Application Not Responding"]

        with open(anr_file, "w", encoding="utf-8") as f:
            for line in proc.stdout:
                if stop_event.is_set():
                    break
                match = any(x in line for x in anr_indicators) and package in line
                if not collecting and match:
                    collecting = True
                    buffer = [line]
                    count = 1
                    matched = True
                    continue
                if collecting:
                    buffer.append(line)
                    count += 1
                    if count >= max_lines or line.startswith("--------- beginning"):
                        collecting = False
                        f.writelines(buffer)
                        f.write("\n\n")
                        buffer.clear()
                        count = 0
            proc.terminate()
            proc.wait()

    else:
        previous = ""
        while not stop_event.is_set():
            try:
                output = subprocess.check_output(
                    adb_prefix + ["shell", "cat", "/data/anr/traces.txt"],
                    text=True, timeout=5, stderr=subprocess.DEVNULL
                )
                if not output or output == previous:
                    time.sleep(5)
                    continue
                previous = output
                blocks = ["----- pid " + b.strip() for b in output.split("----- pid ") if f"Cmd line: {package}" in b]
                if blocks:
                    with open(anr_file, "a", encoding="utf-8") as f:
                        f.write("\n\n".join(blocks) + "\n\n")
                    matched = True
            except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError):
                pass
            time.sleep(5)

    if not matched and not fallback_triggered:
        fetch_latest_anr_async(log_dir, anr_file, device=device)

    # ★ 新增：结束后对比
    end_files = list_anr_files_with_time(device=device)
    new_files = {name: ts for name, ts in end_files.items() if name not in start_files}
    print(f"📊 监控结束后 /data/anr/ 中新增 {len(new_files)} 个文件")
    if new_files:
        print("🆕 新增 ANR 文件：")
        for name, ts in sorted(new_files.items()):
            print(f"   {name}  ({ts})")

    if not matched and not anr_file.exists():
        return None
    return anr_file.resolve()


def analyze_file(path: Path, keywords: list):
    if not path or not path.exists():
        return {}
    count_map = dict.fromkeys(keywords, 0)
    with open(path, encoding="utf-8", errors="ignore") as f:
        for line in f:
            for k in keywords:
                if k in line:
                    count_map[k] += 1
    return count_map


def run_monkey(duration_minutes, package, log_dir="monkey_log", speed="fast"):
    """
    :param duration_minutes: 运行时长传分钟
    :param package: 被测试应用包名
    :param log_dir: 日志存放目录，传目录路径
    :param speed:  speed =normal: 长时稳定性测试，200事件/分钟，speed =fast: 短时强压测试，600事件/分钟
    :return:
    """
    print("开始运行Monkey测试 {}".format(print_current_time()))
    device = check_adb_devices()
    print(f"\n🎯 启动 Monkey 测试")
    print(f"📦 包名：{package}\n📱 设备：{device}\n🕒 时长：{duration_minutes} 分钟，模式：{speed}")

    # 清理设备日志
    print("🧹 清理设备日志...")
    subprocess.run(["adb", "-s", device, "shell", "logcat", "-c"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print("✅ logcat 已清理")
    try:
        subprocess.run(
            ["adb", "-s", device, "shell", "rm", "-f", "/data/anr/traces.txt"],
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=5
        )
        print("✅ ANR traces 已清理")
    except subprocess.CalledProcessError as e:
        if "Permission denied" in str(e.stderr):
            print("⚠️ 无法清理 /data/anr/traces.txt，需要 root 权限")
        else:
            print("⚠️ 清理 ANR traces 失败，错误：", str(e.stderr))

    launcher = get_launcher_activity(package, device=device)
    if launcher:
        subprocess.run(["adb", "-s", device, "shell", "am", "start", "-n", launcher])
        print(f"✅ 已启动应用通过 Activity: {launcher}")
        print("⏳ 等待 3 秒以确保应用进入可交互状态...")
        time.sleep(3)
    else:
        print(f"⚠️ 无法自动识别 {package} 的 Launcher Activity，请手动启动应用！")
        print("⏳ 等待 10 秒以允许手动启动应用...")
        time.sleep(10)

    generate_and_push_whitelist(package, device)

    log_path = Path(log_dir)
    log_path.mkdir(parents=True, exist_ok=True)
    start_time = time.time()
    throttle = 50 if speed == "fast" else 500
    # 事件分布均衡的测试场景
    monkey_cmd = [
        "adb", "-s", device, "shell", "monkey",
        "-p", package,
        "--throttle", str(throttle),
        "--pkg-whitelist-file", "/sdcard/monkey_whitelist.txt",
        "--ignore-crashes", "--ignore-timeouts",
        "--ignore-security-exceptions", "--ignore-native-crashes",
        "--monitor-native-crashes", "-v", "-v", "-v", "10000000",
        "--pct-syskeys", "0",  # 系统按键事件（Home、Back、Volume 等）
        "--pct-appswitch", "0",  # 应用切换事件
        "--pct-nav", "0",
        "--pct-anyevent", "0",  # 模拟其他未明确指定的事件,如输入事件
        "--pct-motion", "30",  # 滑动事件
        "--pct-touch", "65",  # 触摸事件
        "--pct-pinchzoom", "5",  # 缩放事件
        "--pct-trackball", "0",
        "--pct-majornav", "0",
        "--pct-flip", "0",
    ]

    # TODO 只有点击和滑动事件的配置
    # monkey_cmd = [
    #     "adb", "-s", device, "shell", "monkey",
    #     "-p", package,
    #     "--throttle", str(throttle),
    #     "--pkg-whitelist-file", "/sdcard/monkey_whitelist.txt",
    #     "--ignore-crashes", "--ignore-timeouts",
    #     "--ignore-security-exceptions", "--ignore-native-crashes",
    #     "--monitor-native-crashes", "-v", "-v", "-v", "1000000",
    #     "--pct-syskeys", "0", # 系统按键事件（Home、Back、Volume 等）
    #     "--pct-appswitch", "0", # 应用切换事件
    #     "--pct-nav", "0",
    #     "--pct-anyevent", "0", # 模拟其他未明确指定的事件,如输入事件
    #     "--pct-motion", "30", # 滑动事件
    #     "--pct-touch", "70", # 触摸事件
    #     "--pct-pinchzoom", "0", # 缩放事件
    #     "--pct-trackball", "0",
    #     "--pct-majornav", "0",
    #     "--pct-flip", "0",
    # ]

    if is_monkey_support("--restrict-permissions", device=device):
        monkey_cmd.insert(monkey_cmd.index("--throttle"), "--restrict-permissions")

    stop_event = threading.Event()

    t1 = threading.Thread(target=save_logcat_crash, args=(log_path, package, stop_event, start_time, device))
    t2 = threading.Thread(target=monitor_anr, args=(log_path, stop_event, start_time, package, device))
    t1.start()
    t2.start()

    print(f"\n🐵 执行 Monkey：\n👉 {' '.join(monkey_cmd)}")

    process = None  # 初始化process变量

    try:
        process = subprocess.Popen(monkey_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        total_sec = duration_minutes * 60
        with tqdm(total=total_sec, desc="Monkey运行中", unit="s") as pbar:
            for _ in range(total_sec):
                if process.poll() is not None:
                    break
                time.sleep(1)
                pbar.update(1)

        if process.poll() is None:
            print("⏰ 时间结束，主动终止 Monkey")
            subprocess.run(["adb", "-s", device, "shell", "pkill", "monkey"])
            process.terminate()

        out, _ = process.communicate()
        match = re.search(r"Events injected:\s*(\d+)", out)
        if match:
            print(f"✅ Monkey 注入事件数：{match.group(1)}")
        else:
            print("⚠️ 未检测到事件注入日志，Monkey 可能未启动或已崩溃")

    except KeyboardInterrupt:
        print("⚠️ 用户中断 Monkey")
        subprocess.run(["adb", "-s", device, "shell", "pkill", "monkey"])
        if process and hasattr(process, 'terminate'):
            process.terminate()
    finally:
        stop_event.set()
        t1.join()
        t2.join()
        subprocess.run(["adb", "-s", device, "shell", "logcat", "-c"])
        print("🧹 logcat 已清理")

        ts = datetime.fromtimestamp(start_time).strftime("%Y-%m-%d_%H-%M-%S")
        crash_path = log_path / f"{ts}_crash.txt"
        anr_path = log_path / f"{ts}_anr.txt"
        print("结束运行Monkey测试 {}".format(print_current_time()))
        print("\n📂 日志路径：")
        if crash_path.exists():
            print(f"📄 崩溃日志：{crash_path}")
        else:
            print("✅ 未发现崩溃日志")

        if anr_path.exists():
            print(f"📄 ANR 日志：{anr_path}")
        else:
            print("✅ 未发现 ANR 日志")

        print("\n📊 异常关键字统计：")
        crash_keys = ["FATAL EXCEPTION", "SIGSEGV", "signal", "// CRASH:", "W/Monkey", "Abort message"]
        anr_keys = ["Cmd line:", "ANR in", "pid"]

        crash_stats = analyze_file(crash_path, crash_keys) if crash_path.exists() else {}
        if any(v > 0 for v in crash_stats.values()):
            print("🚨 崩溃关键字：")
            for k, v in crash_stats.items():
                print(f"   {k:<25}: {v}")
        else:
            print("✅ 崩溃日志无异常关键字")

        anr_stats = analyze_file(anr_path, anr_keys) if anr_path.exists() else {}
        if any(v > 0 for v in anr_stats.values()):
            print("🚨 ANR 关键字：")
            for k, v in anr_stats.items():
                print(f"   {k:<20}: {v}")
        else:
            print("✅ ANR 日志无异常关键字")


if __name__ == "__main__":
    run_monkey(
        duration_minutes=7,
        package="com.hotpotgames.happysave.global",
        # package="com.shimeji.party.anime.screen.pets.friends",

        # package="com.phone.finder.funny.device.launcher.locate.clap",
        log_dir="/Users/admin/TestLog/monkey_log/",
        speed="fast"
        # speed="normal"
    )
