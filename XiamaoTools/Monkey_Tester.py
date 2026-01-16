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


def is_monkey_support(option: str):
    try:
        help_output = subprocess.check_output(
            ["adb", "shell", "monkey", "--help"],
            timeout=4,
            text=True,
            stderr=subprocess.DEVNULL  # ✅ 屏蔽 monkey usage、error 输出
        )
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


def get_launcher_activity(package):
    """获取应用主启动 Activity"""
    try:
        result = subprocess.run(
            ["adb", "shell", "cmd", "package", "resolve-activity", "--brief", package],
            stdout=subprocess.PIPE, text=True, check=True
        )
        lines = result.stdout.strip().splitlines()
        # 更稳健的解析：寻找包含 '/' 的行
        for ln in lines:
            ln = ln.strip()
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


def save_logcat_crash(log_dir, package, stop_event, start_time):
    """实时保存崩溃日志到文件"""
    timestamp = datetime.fromtimestamp(start_time).strftime("%Y-%m-%d_%H-%M-%S")
    filepath = Path(log_dir) / f"{timestamp}_crash.txt"
    proc = subprocess.Popen(
        ["adb", "logcat", "-v", "time"],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        text=True, encoding="utf-8", errors="ignore"
    )

    collecting, buffer, count, has_crash = False, [], 0, False
    max_lines = 100

    try:
        with open(filepath, "w", encoding="utf-8") as f:
            while not stop_event.is_set():
                # 非阻塞式读取：若没有新行则短暂 sleep，避免线程长时间阻塞
                line = proc.stdout.readline()
                if not line:
                    time.sleep(0.1)
                    continue
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
                        # 只保存匹配包或 monkey 触发的崩溃
                        if any([package in l for l in buffer]) or "W/Monkey" in buffer[0]:
                            f.writelines(buffer)
                            has_crash = True
                        buffer.clear()
    finally:
        # 确保子进程被终止，解除阻塞
        try:
            proc.terminate()
            proc.wait(timeout=2)
        except (OSError, subprocess.SubprocessError):
            # 终止失败则尝试 kill，捕获与子进程/系统调用相关的异常
            try:
                proc.kill()
            except (OSError, subprocess.SubprocessError):
                pass

    if not has_crash:
        filepath.unlink(missing_ok=True)
        return None
    return filepath.resolve()


def list_anr_files_with_time():
    """返回 {文件名: 时间字符串}（无权限返回空字典）"""
    try:
        result = subprocess.check_output(
            ["adb", "shell", "ls", "-l", "/data/anr/"],
            stderr=subprocess.STDOUT, text=True
        )
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


def fetch_latest_anr_async(log_dir, anr_file):
    """最新的ANR文件（异步执行）获取方法"""

    def worker():
        print("[ANR] 启动兜底线程获取最新 ANR 文件...")
        subprocess.run(["adb", "root"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        whoami = subprocess.run(["adb", "shell", "whoami"], capture_output=True, text=True).stdout.strip()

        if whoami == "root":
            # 使用 ls -t 获取按时间排序的文件列表，先检查是否有输出以避免索引错误
            output = subprocess.run(
                ["adb", "shell", "ls", "-t", "/data/anr/"],
                capture_output=True, text=True
            ).stdout.strip().splitlines()
            if not output:
                return
            latest_file = output[0]
            if latest_file:
                result = subprocess.run(["adb", "shell", "cat", f"/data/anr/{latest_file}"],
                                        capture_output=True, text=True)
                if result.stdout:
                    with open(anr_file, "w", encoding="utf-8") as f:
                        f.write(result.stdout)
                    print(f"[DONE] 异步兜底: 最新 ANR 文件已保存到 {anr_file}")
        else:
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            bugreport_path = Path(log_dir) / f"bugreport_{ts}.zip"
            subprocess.run(["adb", "bugreport", str(bugreport_path)])
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


def monitor_anr(log_dir, stop_event, start_time, package):
    """监控 ANR traces，并保存匹配目标包名内容（兜底逻辑异步执行）"""
    # ★ 新增：启动前获取现有文件（带时间）
    start_files = list_anr_files_with_time()
    print(f" 监控开始前 /data/anr/ 中已有 {len(start_files)} 个文件")
    # 移除详细文件列表输出
    # for name, ts in start_files.items():
    #     print(f"   {name}  ({ts})")

    anr_file = Path(log_dir) / f"{datetime.fromtimestamp(start_time).strftime('%Y-%m-%d_%H-%M-%S')}_anr.txt"
    matched = False
    fallback_triggered = False

    # 检查 /data/anr/ 权限
    try:
        subprocess.run(
            ["adb", "shell", "ls", "/data/anr"],
            stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=5, text=True, check=True
        )
        use_logcat = False
        print("✅ 检测到 /data/anr/ 访问权限，使用 traces 文件监控 ANR")
    except subprocess.CalledProcessError as e:
        stderr = e.stderr if isinstance(e.stderr, str) else str(e.stderr)
        if "Permission denied" in stderr:
            print("[ANR] 无 /data/anr/ 访问权限，切换到 logcat 方式监控 ANR")
            use_logcat = True
        else:
            print(f"[ANR] 检查 /data/anr/ 权限失败：{stderr}，跳过 ANR 监控")
            return None

    if use_logcat:
        proc = subprocess.Popen(
            ["adb", "logcat", "-v", "long"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            text=True, encoding="utf-8", errors="ignore"
        )
        buffer, collecting, count = [], False, 0
        max_lines = 10
        anr_indicators = ["ANR in", "Input dispatching timed out", "Application Not Responding"]

        try:
            with open(anr_file, "w", encoding="utf-8") as f:
                while not stop_event.is_set():
                    line = proc.stdout.readline()
                    if not line:
                        time.sleep(0.1)
                        continue
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
        finally:
            try:
                proc.terminate()
                proc.wait(timeout=2)
            except (OSError, subprocess.SubprocessError):
                try:
                    proc.kill()
                except (OSError, subprocess.SubprocessError):
                    pass

    else:
        previous = ""
        while not stop_event.is_set():
            try:
                output = subprocess.check_output(
                    ["adb", "shell", "cat", "/data/anr/traces.txt"],
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
        fetch_latest_anr_async(log_dir, anr_file)

    # ★ 新增：结束后对比
    end_files = list_anr_files_with_time()
    new_files = {name: ts for name, ts in end_files.items() if name not in start_files}
    print(f" 监控结束后 /data/anr/ 中新增 {len(new_files)} 个文件")
    if new_files:
        print(" 新增 ANR 文件：")
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
    :param speed: 测试强度档位（默认为 "fast"）
        - "normal" : 轻量冒烟测试（推荐约 200 events/min，约 3.3 evt/s），适合功能验证与低频长期运行。
        - "fast"   : 常规稳定性测试（推荐约 600 events/min，约 10 evt/s），适合常规回归与中等负载测试。
        - "stress" : 压力测试（推荐约 1500 events/min，约 25 evt/s 或更高），适合高强度压力探测崩溃/稳定性问题。
      说明：
        - speed 只是便捷档位映射；实际压测强度受设备性能、事件分布（--pct-* 参数）、以及 throttle 决定。
        - throttle（事件间隔，ms）越小，注入事件越频繁；你可以通过调整 throttle 或直接计算 total_events 来精确控制速率。
        - 脚本主要以 duration_minutes 为主控（脚本会按时间停止 monkey），如果需要严格按事件数结束，可改为动态计算 total_events 并传入 monkey 命令。
    :return:
    """
    print("开始运行Monkey测试 {}".format(print_current_time()))
    device = check_adb_devices()
    print(f"\n 启动 Monkey 测试")
    print(f" 包名：{package}\n 设备：{device}\n 时长：{duration_minutes} 分钟，模式：{speed}")

    # 清理设备日志
    print(" 清理设备日志...")
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

    launcher = get_launcher_activity(package)
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
    # 根据 speed 简单映射 throttle（事件间隔 ms）
    # 说明：这里保持原有逻辑的小改动，只加注释：
    #  - 当 speed == "fast" 时，throttle = 50 ms（插入事件更密集，适合较强测试）
    #  - 否则 throttle = 500 ms（相对保守，适合冒烟或低频检查）
    # 你可根据注释调整为 "stress" 时更小的 throttle（例如 20-40 ms）以进一步加压。
    throttle = 50 if speed == "fast" else 500
    # 事件分布均衡的测试场景
    # 事件总数仍以用户指定的时长为主，通过监控时间并在到期时主动停止 monkey（下面的循环会做到）
    monkey_cmd = [
        "adb", "-s", device, "shell", "monkey",
        "-p", package,
        "--throttle", str(throttle),
        "--pkg-whitelist-file", "/sdcard/monkey_whitelist.txt",
        "--ignore-crashes", "--ignore-timeouts",
        "--ignore-security-exceptions", "--ignore-native-crashes",
        "--monitor-native-crashes", "-v", "-v", "-v", "1000000",
        # 说明：上面使用的 1000000 是一个很大的固定事件数，目的是让 monkey 长时间运行。
        # 推荐策略：以 duration_minutes 为主控（脚本会到时停止 monkey），或采用动态计算 total_events（例如 events_per_sec = 1000/throttle_ms）
        # 如果需要我可以把 total_events 动态计算并替换此处的固定值，以便更精确地控制压力测试强度。
        "--pct-syskeys", "0",  # 系统按键事件（Home、Back、Volume 等）
        "--pct-appswitch", "3",  # 应用切换事件
        "--pct-nav", "0",
        "--pct-anyevent", "10",  # 模拟其他未明确指定的事件,如输入事件
        "--pct-motion", "30",  # 滑动事件
        "--pct-touch", "55",  # 触摸事件
        "--pct-pinchzoom", "2",  # 缩放事件
        "--pct-trackball", "0",
        "--pct-majornav", "0",
        "--pct-flip", "0",
    ]

    if is_monkey_support("--restrict-permissions"):
        # 如果设备支持 --restrict-permissions，可以插入以限制权限相关事件（提高稳定性或适配某些场景）
        monkey_cmd.insert(monkey_cmd.index("--throttle"), "--restrict-permissions")

    stop_event = threading.Event()

    # 启动用于保存崩溃日志的后台线程（save_logcat_crash）
    t1 = threading.Thread(target=save_logcat_crash, args=(log_path, package, stop_event, start_time))
    # 启动用于监控 ANR 的后台线程（monitor_anr）
    t2 = threading.Thread(target=monitor_anr, args=(log_path, stop_event, start_time, package))
    t1.start()
    t2.start()

    print(f"\n 执行 Monkey：\n {' '.join(monkey_cmd)}")

    process = None  # 初始化process变量

    try:
        # 将 stdout/stderr 都捕获并在循环里通过 poll 检测结束，防止子进程写满导致阻塞
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
            # 尝试终止本地进程
            try:
                process.terminate()
            except (OSError, subprocess.SubprocessError):
                try:
                    process.kill()
                except (OSError, subprocess.SubprocessError):
                    pass

        # 读取输出（若有）
        try:
            out, _ = process.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            try:
                process.kill()
            except (OSError, subprocess.SubprocessError):
                pass
            out = ""

        match = re.search(r"Events injected:\s*(\d+)", out)
        if match:
            print(f"✅ Monkey 注入事件数：{match.group(1)}")
        else:
            print("⚠️ 未检测到事件注入日志，Monkey 可能未启动或已崩溃")

    except KeyboardInterrupt:
        print("⚠️ 用户中断 Monkey")
        subprocess.run(["adb", "-s", device, "shell", "pkill", "monkey"])
        if process and hasattr(process, 'terminate'):
            try:
                process.terminate()
            except (OSError, subprocess.SubprocessError):
                try:
                    process.kill()
                except (OSError, subprocess.SubprocessError):
                    pass
    finally:
        stop_event.set()
        t1.join()
        t2.join()
        subprocess.run(["adb", "-s", device, "shell", "logcat", "-c"])
        print(" logcat 已清理")

        ts = datetime.fromtimestamp(start_time).strftime("%Y-%m-%d_%H-%M-%S")
        crash_path = log_path / f"{ts}_crash.txt"
        anr_path = log_path / f"{ts}_anr.txt"
        print("结束运行Monkey测试 {}".format(print_current_time()))
        print("\n 日志路径：")
        if crash_path.exists():
            print(f" 崩溃日志：{crash_path}")
        else:
            print("✅ 未发现崩溃日志")

        if anr_path.exists():
            print(f" ANR 日志：{anr_path}")
        else:
            print("✅ 未发现 ANR 日志")

        print("\n 异常关键字统计：")
        crash_keys = ["FATAL EXCEPTION", "SIGSEGV", "signal", "// CRASH:", "W/Monkey", "Abort message"]
        anr_keys = ["Cmd line:", "ANR in", "pid"]

        crash_stats = analyze_file(crash_path, crash_keys) if crash_path.exists() else {}
        if any(v > 0 for v in crash_stats.values()):
            print(" 崩溃关键字：")
            for k, v in crash_stats.items():
                print(f"   {k:<25}: {v}")
        else:
            print("✅ 崩溃日志无异常关键字")

        anr_stats = analyze_file(anr_path, anr_keys) if anr_path.exists() else {}
        if any(v > 0 for v in anr_stats.values()):
            print(" ANR 关键字：")
            for k, v in anr_stats.items():
                print(f"   {k:<20}: {v}")
        else:
            print("✅ ANR 日志无异常关键字")


if __name__ == "__main__":
    run_monkey(
        duration_minutes=10,
        # package="com.hotpotgames.happysave.global",
        package="com.wallpaper.launcher.live.pure.magic.desktop",
        # package="com.phone.finder.funny.device.launcher.locate.clap",
        log_dir="/Users/admin/TestLog/monkey_log/",
        speed="stress"
    )
