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

    # 检查 /data/anr/ 权限（注意：ls 可能返回 0，但 stderr 有 Permission denied）
    adb_prefix = ["adb"] + (["-s", device] if device else [])
    result = subprocess.run(
        adb_prefix + ["shell", "ls", "/data/anr"],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=5, text=True
    )
    err_text = (result.stderr or "") + (result.stdout or "")
    if result.returncode == 0 and "Permission denied" not in err_text:
        use_logcat = False
        print("✅ 检测到 /data/anr/ 访问权限，使用 traces 文件监控 ANR")
    elif "Permission denied" in err_text:
        print("[ANR] 无 /data/anr/ 访问权限，切换到 logcat 方式监控 ANR")
        use_logcat = True
    else:
        print(f"[ANR] 检查 /data/anr/ 权限失败：{result.stderr.strip()}，跳过 ANR 监控")
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


def run_monkey(duration_minutes, package, log_dir="monkey_log", speed="fast", ignore_timeouts=False):
    """
    :param duration_minutes: 运行时长传分钟
    :param package: 被测试应用包名
    :param log_dir: 日志存放目录，传目录路径
    :param speed:  speed=normal: 长时稳定性测试，200事件/分钟；speed=fast: 短时强压测试，600事件/分钟
    :param ignore_timeouts: 定位建议False；压测可True（会导致“卡住还继续注入”的现象更常见）
    """
    print("开始运行Monkey测试 {}".format(print_current_time()))
    device = check_adb_devices()
    print(f"\n🎯 启动 Monkey 测试")
    print(f"📦 包名：{package}\n📱 设备：{device}\n🕒 时长：{duration_minutes} 分钟，模式：{speed} | ignore_timeouts={ignore_timeouts}")

    # 清理设备日志
    print("🧹 清理设备日志...")
    subprocess.run(["adb", "-s", device, "shell", "logcat", "-c"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print("✅ logcat 已清理")

    # 清理 ANR traces（注意：不要假成功）
    try:
        res = subprocess.run(
            ["adb", "-s", device, "shell", "rm", "-f", "/data/anr/traces.txt"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=5, text=True
        )
        if res.returncode == 0:
            print("✅ ANR traces 已清理")
        else:
            # 很多机器是 Permission denied
            msg = (res.stderr or "").strip()
            if "Permission denied" in msg:
                print("⚠️ 无法清理 /data/anr/traces.txt，需要 root 权限")
            else:
                print(f"⚠️ 清理 ANR traces 失败：{msg}")
    except subprocess.TimeoutExpired:
        print("⚠️ 清理 ANR traces 超时")

    def _get_current_focus_line():
        window_res = subprocess.run(
            ["adb", "-s", device, "shell", "dumpsys", "window"],
            capture_output=True, text=True
        )
        if window_res.returncode != 0:
            return ""
        for line in window_res.stdout.splitlines():
            if "mCurrentFocus" in line or "mFocusedApp" in line:
                return line.strip()
        return ""

    def _wait_for_focus(timeout_sec=30, stable_sec=3, activity_keyword="LauncherHomeActivity"):
        start = time.time()
        stable_start = None
        while time.time() - start < timeout_sec:
            focus_line_wait = _get_current_focus_line()
            if not focus_line_wait or "null" in focus_line_wait:
                stable_start = None
                time.sleep(1)
                continue
            if package in focus_line_wait and activity_keyword in focus_line_wait:
                if stable_start is None:
                    stable_start = time.time()
                if time.time() - stable_start >= stable_sec:
                    return True
            else:
                stable_start = None
            time.sleep(1)
        return False

    launcher = get_launcher_activity(package, device=device)
    if launcher:
        subprocess.run(["adb", "-s", device, "shell", "am", "start", "-n", launcher], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print(f"✅ 已启动应用通过 Activity: {launcher}")
        print("⏳ 等待前台焦点切到 LauncherHomeActivity 并稳定...")
        if _wait_for_focus(timeout_sec=30, stable_sec=3):
            print("✅ 前台焦点已确认在 LauncherHomeActivity")
        else:
            current_focus_line = _get_current_focus_line()
            print(f"⚠️ 超时未检测到前台焦点在目标包，当前焦点：{current_focus_line}")
    else:
        print(f"⚠️ 无法自动识别 {package} 的 Launcher Activity，请手动启动应用！")
        print("⏳ 等待 10 秒以允许手动启动应用...")
        time.sleep(10)

    generate_and_push_whitelist(package, device)

    log_path = Path(log_dir)
    log_path.mkdir(parents=True, exist_ok=True)
    start_time = time.time()

    throttle = 50 if speed == "fast" else 500

    # 事件分布（你已经改得很稳了：无 anyevent / 无 appswitch）
    monkey_cmd = [
        "adb", "-s", device, "shell", "monkey",
        "-p", package,
        "--throttle", str(throttle),
        "--pkg-whitelist-file", "/sdcard/monkey_whitelist.txt",
        "--ignore-crashes",
        "--ignore-security-exceptions", "--ignore-native-crashes",
        "--monitor-native-crashes",
        "-v", "-v", "-v",
        "--pct-syskeys", "0",
        "--pct-appswitch", "0",
        "--pct-nav", "0",
        "--pct-anyevent", "0",
        "--pct-motion", "30",
        "--pct-touch", "70",
        "--pct-pinchzoom", "0",
        "--pct-trackball", "0",
        "--pct-majornav", "0",
        "--pct-flip", "0",
    ]

    # 可选：压测才忽略 timeout（定位阶段建议False）
    if ignore_timeouts:
        insert_pos = monkey_cmd.index("--ignore-crashes") + 1
        monkey_cmd.insert(insert_pos, "--ignore-timeouts")

    # 可选：如果支持 restrict-permissions 就插入
    if is_monkey_support("--restrict-permissions", device=device):
        monkey_cmd.insert(monkey_cmd.index("--throttle"), "--restrict-permissions")
    # 事件总数必须放在最后，否则部分参数可能被忽略
    monkey_cmd.append("10000000")

    stop_event = threading.Event()
    freeze_event = threading.Event()

    t1 = threading.Thread(target=save_logcat_crash, args=(log_path, package, stop_event, start_time, device))
    t2 = threading.Thread(target=monitor_anr, args=(log_path, stop_event, start_time, package, device))
    t1.start()
    t2.start()

    print(f"\n🐵 执行 Monkey：\n👉 {' '.join(monkey_cmd)}")

    process = None
    total_sec = int(duration_minutes * 60)

    ts = datetime.fromtimestamp(start_time).strftime("%Y-%m-%d_%H-%M-%S")
    monkey_out_path = log_path / f"{ts}_monkey_out.txt"

    def _get_monkey_pid():
        result = subprocess.run(
            ["adb", "-s", device, "shell", "pidof", "com.android.commands.monkey"],
            capture_output=True, text=True
        )
        if result.returncode == 0:
            monkey_pid = result.stdout.strip()
            if monkey_pid:
                return monkey_pid
        ps_result = subprocess.run(
            ["adb", "-s", device, "shell", "ps", "-A"],
            capture_output=True, text=True
        )
        if ps_result.returncode != 0:
            return None
        for line in ps_result.stdout.splitlines():
            if "com.android.commands.monkey" in line:
                parts = line.split()
                for token in parts:
                    if token.isdigit():
                        return token
        return None

    def _get_current_focus():
        # 只抓关键行，减少输出量
        window_res = subprocess.run(
            ["adb", "-s", device, "shell", "dumpsys", "window"],
            capture_output=True, text=True
        )
        txt = window_res.stdout or ""
        # 上面只拿到字段名不带整行，所以改成找整行更稳
        lines = []
        for line in txt.splitlines():
            if "mCurrentFocus" in line or "mFocusedApp" in line:
                lines.append(line.strip())
        return " | ".join(lines[-2:]) if lines else ""

    def _get_device_state():
        device_state: dict[str, object] = {
            "interactive": None,
            "wakefulness": None,
            "locked": False,
            "focus": "",
        }
        power = subprocess.run(
            ["adb", "-s", device, "shell", "dumpsys", "power"],
            capture_output=True, text=True
        )
        if power.returncode == 0:
            for line in power.stdout.splitlines():
                line = line.strip()
                if line.startswith("mInteractive="):
                    device_state["interactive"] = line.split("=", 1)[1]
                elif line.startswith("mWakefulness="):
                    device_state["wakefulness"] = line.split("=", 1)[1]
        device_state["focus"] = _get_current_focus()
        focus_lower = str(device_state["focus"]).lower()
        if "keyguard" in focus_lower or "statusbar" in focus_lower or "dream" in focus_lower:
            device_state["locked"] = True
        elif device_state["focus"]:
            device_state["locked"] = False
        return device_state

    def _bring_to_front(last_ts: float) -> float:
        now_ts_bring = time.time()
        if now_ts_bring - last_ts < 30:
            return last_ts
        if launcher:
            subprocess.run(
                ["adb", "-s", device, "shell", "am", "start", "-n", launcher],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
            print(f"🔄 已尝试拉起前台 Activity: {launcher}")
        else:
            subprocess.run(
                ["adb", "-s", device, "shell", "monkey", "-p", package, "-c", "android.intent.category.LAUNCHER", "1"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
            )
            print("🔄 已尝试通过 monkey 拉起前台应用")
        return now_ts_bring

    try:
        # 关键：实时把 monkey stdout/stderr 写入文件，避免等 communicate() 才拿输出
        process = subprocess.Popen(monkey_cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)

        output_stats: dict[str, object] = {
            "sending_count": 0,
            "events_injected": None,
            "last_output_ts": None,
            "last_sending_ts": None,
        }
        focus_stats: dict[str, object] = {
            "last_focus": "",
            "last_change_ts": time.time(),
        }
        with open(monkey_out_path, "w", encoding="utf-8", errors="ignore") as out_file:
            # 后台线程：持续读取 monkey 输出写文件
            def _pump_output():
                try:
                    for line in process.stdout:
                        out_file.write(line)
                        out_file.flush()
                        output_stats["last_output_ts"] = time.time()
                        if "Sending" in line:
                            output_stats["sending_count"] += 1
                            output_stats["last_sending_ts"] = time.time()
                        m_injected = re.search(r"Events injected:\s*(\d+)", line)
                        if m_injected:
                            output_stats["events_injected"] = m_injected.group(1)
                        if stop_event.is_set():
                            break
                except (OSError, ValueError):
                    pass

            pump_thread = threading.Thread(target=_pump_output, daemon=True)
            pump_thread.start()

            def _detect_freeze():
                freeze_window_sec = 25
                check_interval = 5
                while not stop_event.is_set():
                    time.sleep(check_interval)
                    if stop_event.is_set():
                        break
                    now_ts_check = time.time()
                    focus_line_current = _get_current_focus_line()
                    if focus_line_current and focus_line_current != focus_stats["last_focus"]:
                        focus_stats["last_focus"] = focus_line_current
                        focus_stats["last_change_ts"] = now_ts_check
                    last_change = focus_stats["last_change_ts"]
                    if not isinstance(last_change, (int, float)):
                        last_change = now_ts_check

                    last_sending_ts = output_stats.get("last_sending_ts")
                    if not isinstance(last_sending_ts, (int, float)):
                        continue

                    focus_same_too_long = (now_ts_check - float(last_change)) > freeze_window_sec
                    injected_active = (now_ts_check - float(last_sending_ts)) < 10
                    anr_hint = False

                    try:
                        log_tail = subprocess.run(
                            ["adb", "-s", device, "logcat", "-d", "-v", "time", "-t", "50"],
                            capture_output=True, text=True, timeout=4
                        ).stdout
                        if log_tail:
                            for key in ("ANR in", "Input dispatching timed out", "Application Not Responding"):
                                if key in log_tail:
                                    anr_hint = True
                                    break
                    except (subprocess.SubprocessError, subprocess.TimeoutExpired, OSError):
                        pass

                    if focus_same_too_long and injected_active:
                        target_scope = "应用"
                        focus_lower = focus_line_current.lower()
                        if "systemui" in focus_lower or "keyguard" in focus_lower:
                            target_scope = "系统"
                        hint_text = "ANR 关键词检测到" if anr_hint else "焦点长期不变+持续注入"
                        print(f"🚨 疑似{target_scope}卡死（{hint_text}）：{focus_line_current}")
                        freeze_event.set()
                        stop_event.set()
                        break

            freeze_thread = threading.Thread(target=_detect_freeze, daemon=True)
            freeze_thread.start()

            with tqdm(total=total_sec, desc="Monkey运行中", unit="s") as pbar:
                warned_no_pid = False
                warned_no_inject = False
                warned_locked = False
                last_bring_ts = 0.0
                process_exited_early = False
                for sec in range(total_sec):
                    if freeze_event.is_set():
                        break
                    if process.poll() is not None:
                        process_exited_early = True
                        break

                    # 每 5 秒做一次“实锤检查”
                    if sec % 5 == 0 and sec >= 10:
                        pid = _get_monkey_pid()
                        if not pid and not warned_no_pid:
                            print("⚠️ 未能获取 monkey 进程 PID（可能是设备不支持 pidof/ps），跳过进程检测")
                            warned_no_pid = True

                        state = _get_device_state()
                        focus = state.get("focus", "")
                        if focus and package not in focus:
                            print(f"⚠️ 前台焦点不在目标包，可能被系统弹窗/其他界面抢走：{focus}")
                            if not state.get("locked") and state.get("interactive") != "false":
                                last_bring_ts = _bring_to_front(last_bring_ts)
                        if state.get("locked") and not warned_locked:
                            print("⚠️ 设备可能处于锁屏/遮挡界面，monkey 注入可能被系统拦截")
                            warned_locked = True
                        if state.get("interactive") == "false" or state.get("wakefulness") == "Asleep":
                            if not warned_locked:
                                print("⚠️ 设备可能处于息屏/不交互状态，monkey 注入可能无效")
                                warned_locked = True

                        # 10s 内没有任何注入输出，提示但不中断
                        last_sending = output_stats.get("last_sending_ts")
                        last_output = output_stats.get("last_output_ts")
                        now_ts_loop = time.time()
                        if not warned_no_inject and isinstance(last_output, (int, float)) and not isinstance(last_sending, (int, float)):
                            if (now_ts_loop - last_output) > 10:
                                print("⚠️ monkey 输出无注入记录（可能未在注入/被系统拦截）")
                                warned_no_inject = True

                    time.sleep(1)
                    pbar.update(1)

            # 时间到仍在跑 -> 主动终止
            killed_by_timeout = False
            if process.poll() is None:
                if freeze_event.is_set():
                    print("⛔ 疑似卡死，主动终止 Monkey")
                else:
                    print("⏰ 时间结束，主动终止 Monkey")
                    killed_by_timeout = True
                subprocess.run(["adb", "-s", device, "shell", "pkill", "monkey"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                try:
                    process.terminate()
                except OSError:
                    pass

            stop_event.set()
            pump_thread.join(timeout=2)
            freeze_thread.join(timeout=2)

        # 解析注入事件数（从输出文件里找，避免 out 丢失）
        injected = output_stats.get("events_injected")
        try:
            out_text = monkey_out_path.read_text(encoding="utf-8", errors="ignore")
            if not injected:
                m = re.search(r"Events injected:\s*(\d+)", out_text)
                if m:
                    injected = m.group(1)
        except (OSError, UnicodeDecodeError):
            pass

        if injected:
            print(f"✅ Monkey 注入事件数：{injected}")
        else:
            reasons = []
            if killed_by_timeout:
                reasons.append("运行到时长被脚本主动终止，输出可能未完整落盘")
            if process_exited_early:
                reasons.append("monkey 进程提前退出/崩溃")
            try:
                if monkey_out_path.stat().st_size == 0:
                    reasons.append("输出文件为空/未写入")
            except OSError:
                reasons.append("输出文件不可读")
            reason_text = "；".join(reasons) if reasons else "输出中未包含 Events injected"
            print(f"⚠️ 未检测到 Events injected（{reason_text}）。输出文件：{monkey_out_path}")

    except KeyboardInterrupt:
        print("⚠️ 用户中断 Monkey")
        subprocess.run(["adb", "-s", device, "shell", "pkill", "monkey"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if process and hasattr(process, "terminate"):
            try:
                process.terminate()
            except OSError:
                pass
    finally:
        stop_event.set()
        t1.join()
        t2.join()

        # 清理 logcat
        subprocess.run(["adb", "-s", device, "shell", "logcat", "-c"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print("🧹 logcat 已清理")

        ts = datetime.fromtimestamp(start_time).strftime("%Y-%m-%d_%H-%M-%S")
        crash_path = log_path / f"{ts}_crash.txt"
        anr_path = log_path / f"{ts}_anr.txt"

        print("结束运行Monkey测试 {}".format(print_current_time()))
        print("\n📂 日志路径：")
        print(f"📄 Monkey输出：{monkey_out_path}")
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
        if crash_stats and any(v > 0 for v in crash_stats.values()):
            print("🚨 崩溃关键字：")
            for k, v in crash_stats.items():
                print(f"   {k:<25}: {v}")
        else:
            print("✅ 崩溃日志无异常关键字")

        anr_stats = analyze_file(anr_path, anr_keys) if anr_path.exists() else {}
        if anr_stats and any(v > 0 for v in anr_stats.values()):
            print("🚨 ANR 关键字：")
            for k, v in anr_stats.items():
                print(f"   {k:<20}: {v}")
        else:
            print("✅ ANR 日志无异常关键字")



if __name__ == "__main__":
    run_monkey(
        duration_minutes=10,
        package="com.hotpotgames.happysave.global",
        # package="com.bright.flashlight.torch.light.your.road",

        # package="com.phone.finder.funny.device.launcher.locate.clap",
        log_dir="/Users/admin/TestLog/monkey_log/",
        speed="fast",
        ignore_timeouts=False
    )
