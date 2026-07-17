#!/usr/bin/env python3
"""
Android 稳定性测试工具（极简版）

目标：
- 仅抓取当前包名相关的 Crash / ANR 日志
- 实时统计 Crash/ANR 个数
- 支持进度显示（tqdm 优先，缺失自动降级）
- 提前中断时也会落盘已抓日志，并强制结束 monkey 进程

不生成：
- runtime.log
- summary.json / summary.md
- 全量 logcat / dumpsys / screenshot / bugreport
"""


import concurrent.futures
import dataclasses
import datetime as dt
import hashlib
import queue
import random
import re
import subprocess
import threading
import time
from collections import Counter, deque
from pathlib import Path
from typing import Deque, Dict, List, Optional, Tuple

try:
    from tqdm import tqdm
except ImportError:
    tqdm = None


CRASH = "CRASH"
ANR = "ANR"

# 用于“检测”事件的关键字（尽量覆盖 Java/Native Crash 与常见 ANR 场景）
CRASH_DETECT_KEYS = [
    "FATAL EXCEPTION",
    "Fatal signal",
    "SIGSEGV",
    "SIGABRT",
    "native crash",
    "am_crash",
    "// CRASH:",
    "Abort message",
]
ANR_DETECT_KEYS = [
    "ANR in",
    "Input dispatching timed out",
    "Application Not Responding",
    "executing service",
    "Broadcast of Intent",
    "ContentProvider not responding",
    "am_anr",
]

# 用于“结束统计展示”的关键字
CRASH_STAT_KEYS = ["FATAL EXCEPTION", "Fatal signal", "SIGSEGV", "SIGABRT", "am_crash", "Process:"]
ANR_STAT_KEYS = ["ANR in", "Input dispatching timed out", "Application Not Responding", "am_anr", "Cmd line:"]


@dataclasses.dataclass
class ToolConfig:
    package: str
    monkey_packages: List[str]
    report_root: Path
    duration_sec: int
    monkey_events: int
    monkey_throttle_ms: int
    monkey_seed: Optional[int]
    monkey_pct_touch: int
    monkey_pct_motion: int
    monkey_pct_nav: int
    monkey_pct_syskeys: int
    monkey_pct_appswitch: int
    adb_path: str
    continue_on_failure: bool
    clear_logcat: bool
    devices: List[str]
    external_stop_event: Optional[threading.Event] = None


@dataclasses.dataclass
class FailureEvent:
    event_id: int
    event_type: str
    timestamp: str
    device: str
    fingerprint: str
    signature: str
    trigger_line: str
    dedup_count: int = 1


@dataclasses.dataclass
class DeviceResult:
    device: str
    ok: bool
    reason: str
    failures: List[FailureEvent]
    run_dir: Path


def now_str() -> str:
    """返回当前本地时间字符串，用于统一日志时间格式。"""
    return dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def safe_name(value: str) -> str:
    """将任意字符串转换为安全文件名片段。"""
    return re.sub(r"[^0-9A-Za-z_.-]+", "_", value)


def run_cmd(args: List[str], timeout: Optional[int] = None) -> subprocess.CompletedProcess:
    """执行命令并返回完整输出结果。"""
    return subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=timeout)


def adb_cmd(adb_path: str, device: str, *parts: str) -> List[str]:
    """拼接带设备序列号的 adb 子命令。"""
    return [adb_path, "-s", device, *parts]


def ensure_adb(adb_path: str) -> None:
    """校验 adb 可执行且可正常响应。"""
    try:
        cp = run_cmd([adb_path, "version"], timeout=5)
    except FileNotFoundError as exc:
        raise RuntimeError(f"未找到 adb：{adb_path}") from exc
    if cp.returncode != 0:
        raise RuntimeError(f"adb 不可用：{cp.stderr.strip()}")


def list_online_devices(adb_path: str) -> List[str]:
    """返回当前在线（device 状态）的设备序列号列表。"""
    cp = run_cmd([adb_path, "devices"], timeout=8)
    if cp.returncode != 0:
        raise RuntimeError(f"adb devices 失败：{cp.stderr.strip()}")
    devices = []
    for line in cp.stdout.splitlines()[1:]:
        parts = line.strip().split()
        if len(parts) >= 2 and parts[1] == "device":
            devices.append(parts[0])
    return devices


def resolve_devices(adb_path: str, explicit: List[str], all_devices: bool) -> List[str]:
    """按入参策略解析最终测试设备列表。"""
    online = list_online_devices(adb_path)
    if not online:
        raise RuntimeError("未检测到在线设备")
    if explicit:
        missing = [d for d in explicit if d not in online]
        if missing:
            raise RuntimeError(f"以下设备不在线：{missing}；在线设备：{online}")
        return explicit
    if all_devices:
        return online
    return [online[0]]


def check_package_installed(adb_path: str, device: str, package: str) -> bool:
    """检查目标包是否已安装在指定设备。"""
    cp = run_cmd(adb_cmd(adb_path, device, "shell", "pm", "path", package), timeout=10)
    return cp.returncode == 0 and "package:" in cp.stdout


def clear_logcat(adb_path: str, device: str) -> None:
    """清空指定设备的 logcat 缓冲区。"""
    run_cmd(adb_cmd(adb_path, device, "logcat", "-c"), timeout=10)


def analyze_file(path: Path, keywords: List[str]) -> Dict[str, int]:
    """统计文件中各关键字出现次数。"""
    if not path.exists():
        return {}
    counter = {k: 0 for k in keywords}
    with path.open("r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            for k in keywords:
                if k in line:
                    counter[k] += 1
    return counter


def extract_signature(lines: List[str]) -> str:
    """从日志摘录中提取可用于去重与聚合的签名。"""
    sig = []
    for line in lines:
        l = line.strip()
        if not l:
            continue
        if any(x in l for x in ["FATAL EXCEPTION", "ANR in", "Process:", "Cmd line:", "Reason:", "Caused by:"]):
            sig.append(l)
        elif " at " in l or l.startswith("at "):
            sig.append(l)
        if len(sig) >= 8:
            break
    if not sig:
        sig = [x.strip() for x in lines[:6] if x.strip()]
    return " | ".join(sig)[:800]


def make_fingerprint(event_type: str, signature: str) -> str:
    """根据事件类型与签名生成短指纹。"""
    return hashlib.sha1(f"{event_type}::{signature}".encode("utf-8", errors="ignore")).hexdigest()[:16]


def detect_candidate_type(line: str) -> Optional[str]:
    """根据单行日志关键字判断候选事件类型。"""
    ll = line.lower()
    if any(k.lower() in ll for k in CRASH_DETECT_KEYS):
        return CRASH
    if any(k.lower() in ll for k in ANR_DETECT_KEYS):
        return ANR
    return None


def _pkg_match(target_pkg: str, proc_name: str) -> bool:
    """判断进程名是否属于目标包（允许 :remote 进程后缀）。"""
    p = proc_name.strip().lower()
    t = target_pkg.strip().lower()
    return p == t or p.startswith(t + ":")


def is_target_package_event(excerpt: List[str], package: str, event_type: str) -> bool:
    """判断事件摘录是否明确归属于目标包。"""
    pkg = package.lower()
    joined = "\n".join(excerpt)
    joined_lower = joined.lower()

    # ANR 通常自带明确字段
    if f"anr in {pkg}" in joined_lower:
        return True
    if f"cmd line: {pkg}" in joined_lower:
        return True

    # Crash/ANR 通用：优先从“进程归属字段”判定
    process_patterns = [
        r"Process:\s*([A-Za-z0-9._:]+)",          # Java crash: Process: com.xxx
        r"Cmd line:\s*([A-Za-z0-9._:]+)",         # Tombstone/ANR: Cmd line:
        r"Process\s+([A-Za-z0-9._:]+)\s+\(pid",   # ActivityManager: Process xxx (pid)
        r">>>\s*([A-Za-z0-9._:]+)\s*<<<",         # Native tombstone: >>> com.xxx <<<
    ]
    for pat in process_patterns:
        for m in re.finditer(pat, joined, flags=re.IGNORECASE):
            if _pkg_match(pkg, m.group(1)):
                return True

    # am_crash 场景：允许按行包含目标包名匹配
    for line in excerpt:
        ll = line.lower()
        if "am_crash" in ll and pkg in ll:
            return True

    # 仅对 ANR 保留兜底（部分机型字段不标准）。
    # Crash 必须能从明确的归属字段判定到目标包，避免把同一时间窗口内其它进程的异常混入。
    if event_type == ANR and pkg in joined_lower:
        return True
    return False


class DeviceRunner:
    def __init__(self, cfg: ToolConfig, device: str):
        """初始化单设备运行上下文与输出目录。"""
        self.cfg = cfg
        self.device = device
        ts = dt.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        self.run_dir = cfg.report_root / safe_name(device) / ts
        self.run_dir.mkdir(parents=True, exist_ok=True)

        self.crash_log_file = self.run_dir / f"{ts}_crash.txt"
        self.anr_log_file = self.run_dir / f"{ts}_anr.txt"

        self.stop_event = threading.Event()
        self.fail_queue: "queue.Queue[Tuple[str, str, List[str]]]" = queue.Queue()
        self.recent_lines: Deque[str] = deque(maxlen=200)

        self.failures: List[FailureEvent] = []
        self.fingerprint_hits: Counter = Counter()
        self.last_emit_by_fp: Dict[str, float] = {}

        self.monkey_proc: Optional[subprocess.Popen] = None
        self.logcat_proc: Optional[subprocess.Popen] = None

        self.start_ts = time.time()
        self.event_index = 0
        self.progress_bar = None
        self.last_progress_print_ts = 0.0

    def log(self, msg: str) -> None:
        """统一设备维度日志输出。"""
        line = f"[{now_str()}][{self.device}] {msg}"
        if tqdm is not None:
            tqdm.write(line)
        else:
            print(line)

    def setup(self) -> Tuple[bool, str]:
        """执行运行前检查与可选的 logcat 清理。"""
        if not check_package_installed(self.cfg.adb_path, self.device, self.cfg.package):
            return False, f"设备 {self.device} 未安装包 {self.cfg.package}"

        run_cmd(adb_cmd(self.cfg.adb_path, self.device, "wait-for-device"), timeout=20)
        if self.cfg.clear_logcat:
            self.log("🧹 清理设备 logcat...")
            clear_logcat(self.cfg.adb_path, self.device)
            self.log("✅ logcat 已清理")
        return True, "ok"

    def start_logcat(self) -> None:
        """启动 logcat 流式采集进程。"""
        self.logcat_proc = subprocess.Popen(
            adb_cmd(
                self.cfg.adb_path,
                self.device,
                "logcat",
                "-b",
                "all",
                "-v",
                "time",
            ),
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            errors="ignore",
            bufsize=1,
        )

    def start_monkey(self) -> None:
        """启动 monkey 进程（按配置的分布、节流与事件总数）。"""
        seed = self.cfg.monkey_seed if self.cfg.monkey_seed is not None else random.randint(1, 2**31 - 1)
        cmd = adb_cmd(self.cfg.adb_path, self.device, "shell", "monkey")
        for pkg in self.cfg.monkey_packages:
            cmd.extend(["-p", pkg])
        cmd.extend(
            [
                "--throttle",
                str(self.cfg.monkey_throttle_ms),
                "--pct-touch",
                str(self.cfg.monkey_pct_touch),
                "--pct-motion",
                str(self.cfg.monkey_pct_motion),
                "--pct-nav",
                str(self.cfg.monkey_pct_nav),
                "--pct-syskeys",
                str(self.cfg.monkey_pct_syskeys),
                "--pct-appswitch",
                str(self.cfg.monkey_pct_appswitch),
                "--ignore-crashes",
                "--ignore-timeouts",
                "--ignore-security-exceptions",
                "-s",
                str(seed),
                str(self.cfg.monkey_events),
            ]
        )
        # 不保存 monkey 输出，降低 IO/内存占用
        self.monkey_proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def append_compact_failure_log(self, event: FailureEvent, excerpt: List[str]) -> None:
        """将单次故障事件以紧凑格式追加到对应日志文件。"""
        target = self.crash_log_file if event.event_type == CRASH else self.anr_log_file
        with target.open("a", encoding="utf-8", errors="ignore") as f:
            f.write("".join(excerpt))
            f.write("\n")

    def handle_failure(self, event_type: str, trigger_line: str, excerpt: List[str]) -> None:
        """处理候选故障事件：归属判断、去重、落盘与计数。"""
        if not is_target_package_event(excerpt, self.cfg.package, event_type):
            if event_type == CRASH:
                self.log(f"跳过非目标包 Crash 候选：{trigger_line.strip()[:160]}")
            return

        signature = extract_signature(excerpt)
        fp = make_fingerprint(event_type, signature)
        now_ts = time.time()

        self.fingerprint_hits[fp] += 1
        dedup_count = self.fingerprint_hits[fp]

        # 同一指纹短时间重复不重复落盘，避免噪声
        if now_ts - self.last_emit_by_fp.get(fp, 0.0) < 20:
            return
        self.last_emit_by_fp[fp] = now_ts

        self.event_index += 1
        event = FailureEvent(
            event_id=self.event_index,
            event_type=event_type,
            timestamp=now_str(),
            device=self.device,
            fingerprint=fp,
            signature=signature,
            trigger_line=trigger_line.strip(),
            dedup_count=dedup_count,
        )
        self.failures.append(event)
        self.append_compact_failure_log(event, excerpt)

        crash_count = sum(1 for x in self.failures if x.event_type == CRASH)
        anr_count = sum(1 for x in self.failures if x.event_type == ANR)
        self.log(f"检测到 {event_type}，fingerprint={fp}")
        self.log(f"📊 实时统计 -> crash={crash_count}, anr={anr_count}, total={len(self.failures)}")

        if not self.cfg.continue_on_failure:
            self.log("根据配置发现故障后立即停止")
            self.stop_event.set()

    def parse_logcat_loop(self) -> None:
        """持续解析 logcat，并将候选故障事件放入队列。"""
        if self.logcat_proc is None or self.logcat_proc.stdout is None:
            self.stop_event.set()
            return

        for line in self.logcat_proc.stdout:
            if self.stop_event.is_set():
                break

            self.recent_lines.append(line)
            candidate = detect_candidate_type(line)
            if candidate is None:
                continue

            excerpt = [line]
            # 参考 Monkey_TesterV2：命中后抓一段连续原始日志，便于开发直接定位
            for _ in range(100):
                if self.logcat_proc.stdout is None:
                    break
                nxt = self.logcat_proc.stdout.readline()
                if not nxt:
                    break
                excerpt.append(nxt)
                self.recent_lines.append(nxt)
                if "--------- beginning" in nxt:
                    break

            self.fail_queue.put((candidate, line, excerpt))

    def open_progress_bar(self) -> None:
        """初始化 tqdm 进度条（按时长秒数计）。"""
        if tqdm is None:
            return
        try:
            pos = self.cfg.devices.index(self.device) if self.device in self.cfg.devices else 0
            self.progress_bar = tqdm(total=self.cfg.duration_sec, desc=f"{self.device}", unit="s", position=pos, leave=True)
        except (ValueError, TypeError):
            self.progress_bar = None

    def close_progress_bar(self) -> None:
        """关闭进度条；若提前结束则补齐显示到总时长。"""
        if self.progress_bar is None:
            return
        try:
            total = max(1, self.cfg.duration_sec)
            cur = int(self.progress_bar.n)
            if cur < total:
                self.progress_bar.update(total - cur)
            self.progress_bar.close()
        except (TypeError, ValueError, AttributeError):
            pass
        finally:
            self.progress_bar = None

    def print_progress(self) -> None:
        """刷新进度显示；tqdm 不可用时降级为周期文本日志。"""
        now = time.time()
        elapsed = int(now - self.start_ts)
        total = max(1, self.cfg.duration_sec)

        if self.progress_bar is not None:
            cur = int(self.progress_bar.n)
            if elapsed > cur:
                self.progress_bar.update(min(elapsed - cur, total - cur))
            return

        if now - self.last_progress_print_ts < 10:
            return
        self.last_progress_print_ts = now

        remain = max(0, total - elapsed)
        percent = min(100.0, (elapsed / total) * 100.0)
        crash_count = sum(1 for x in self.failures if x.event_type == CRASH)
        anr_count = sum(1 for x in self.failures if x.event_type == ANR)
        self.log(
            f"⏱ 进度: {elapsed // 60:02d}:{elapsed % 60:02d}/{total // 60:02d}:{total % 60:02d} "
            f"({percent:.1f}%), 剩余 {remain // 60:02d}:{remain % 60:02d}, crash={crash_count}, anr={anr_count}"
        )

    def drain_fail_queue(self) -> None:
        """在收尾阶段处理队列中残留故障事件，避免丢失。"""
        while True:
            try:
                et, trigger, excerpt = self.fail_queue.get_nowait()
            except queue.Empty:
                break
            self.handle_failure(et, trigger, excerpt)

    def shutdown(self) -> None:
        """停止本地与设备端相关进程，做统一收尾。"""
        self.stop_event.set()

        # 强制结束设备端 monkey，避免本地 terminate 后设备端残留
        run_cmd(adb_cmd(self.cfg.adb_path, self.device, "shell", "pkill", "-f", "monkey"), timeout=5)
        run_cmd(adb_cmd(self.cfg.adb_path, self.device, "shell", "pkill", "monkey"), timeout=5)

        for proc in [self.monkey_proc, self.logcat_proc]:
            if proc is None:
                continue
            if proc.poll() is None:
                try:
                    proc.terminate()
                    proc.wait(timeout=6)
                except (subprocess.TimeoutExpired, ProcessLookupError, OSError):
                    proc.kill()

    def print_end_summary(self) -> None:
        """输出本设备运行结果、日志路径与关键字统计。"""
        crash_count = sum(1 for x in self.failures if x.event_type == CRASH)
        anr_count = sum(1 for x in self.failures if x.event_type == ANR)
        total_count = crash_count + anr_count

        self.log("结束运行 Monkey 稳定性测试")
        self.log(f"📈 事件统计：crash={crash_count}, anr={anr_count}, total={total_count}")
        self.log("📂 日志路径：")
        if self.crash_log_file.exists():
            self.log(f"📄 崩溃日志：{self.crash_log_file}")
        else:
            self.log("✅ 未发现崩溃日志")

        if self.anr_log_file.exists():
            self.log(f"📄 ANR 日志：{self.anr_log_file}")
        else:
            self.log("✅ 未发现 ANR 日志")

        crash_stats = analyze_file(self.crash_log_file, CRASH_STAT_KEYS) if self.crash_log_file.exists() else {}
        anr_stats = analyze_file(self.anr_log_file, ANR_STAT_KEYS) if self.anr_log_file.exists() else {}

        self.log("📊 异常关键字统计：")
        if any(v > 0 for v in crash_stats.values()):
            self.log("🚨 崩溃关键字：")
            for k, v in crash_stats.items():
                self.log(f"   {k:<30}: {v}")
        else:
            self.log("✅ 崩溃日志无异常关键字")

        if any(v > 0 for v in anr_stats.values()):
            self.log("🚨 ANR 关键字：")
            for k, v in anr_stats.items():
                self.log(f"   {k:<30}: {v}")
        else:
            self.log("✅ ANR 日志无异常关键字")

    def run(self) -> DeviceResult:
        """执行单设备完整测试流程并返回结构化结果。"""
        ok, reason = self.setup()
        if not ok:
            return DeviceResult(self.device, False, reason, [], self.run_dir)

        self.log("🎯 启动 Monkey 稳定性测试")
        self.log("🧩 日志策略：仅保存当前包名的 Crash/ANR 相关日志")
        self.log(f"📦 包名：{self.cfg.package}")
        self.log(f"📱 设备：{self.device}")
        self.log(f"🕒 时长：{self.cfg.duration_sec // 60} 分钟")
        self.log(f"📁 日志目录：{self.run_dir}")
        self.log(f"📄 Crash 日志：{self.crash_log_file}")
        self.log(f"📄 ANR 日志：{self.anr_log_file}")

        self.start_logcat()
        self.start_monkey()

        t_log = threading.Thread(target=self.parse_logcat_loop, daemon=True)
        t_log.start()

        deadline = self.start_ts + self.cfg.duration_sec
        self.open_progress_bar()

        try:
            while not self.stop_event.is_set():
                if self.cfg.external_stop_event is not None and self.cfg.external_stop_event.is_set():
                    self.log("收到全局中断信号，准备停止")
                    self.stop_event.set()
                    break

                self.print_progress()

                if time.time() >= deadline:
                    self.log("⏰ 达到设定时长，停止测试")
                    self.stop_event.set()
                    break

                monkey_proc = self.monkey_proc
                if monkey_proc is not None and monkey_proc.poll() is not None:
                    self.log(f"Monkey 已退出，returncode={monkey_proc.returncode}")
                    self.monkey_proc = None
                    self.stop_event.set()
                    break

                try:
                    et, trigger, excerpt = self.fail_queue.get(timeout=1)
                    self.handle_failure(et, trigger, excerpt)
                except queue.Empty:
                    pass

        except KeyboardInterrupt:
            self.log("⚠️ 用户中断，正在停止并保存已抓取日志")
            self.stop_event.set()
        finally:
            # 先处理已入队事件，再关闭进程，避免最后一批丢失
            self.drain_fail_queue()
            self.shutdown()
            if self.cfg.clear_logcat:
                clear_logcat(self.cfg.adb_path, self.device)
                self.log("🧹 结束后已清理 logcat")
            self.close_progress_bar()
            self.print_end_summary()

        return DeviceResult(self.device, True, "ok", self.failures, self.run_dir)


def validate_monkey_percent(cfg: ToolConfig) -> None:
    """校验 monkey 事件分布百分比配置合法。"""
    total = cfg.monkey_pct_touch + cfg.monkey_pct_motion + cfg.monkey_pct_nav + cfg.monkey_pct_syskeys + cfg.monkey_pct_appswitch
    if total > 100:
        raise ValueError(f"monkey 事件分布总和不能大于 100，当前={total}")


def run_one_device(cfg: ToolConfig, device: str) -> DeviceResult:
    """单设备执行入口（供线程池调用）。"""
    return DeviceRunner(cfg, device).run()


def run_monkey(
    duration_minutes: int,
    package: str,
    log_dir: str,
    speed: str = "fast",
    monkey_whitelist_packages: Optional[List[str]] = None,
    device: Optional[str] = None,
    all_devices: bool = False,
    adb_path: str = "adb",
    continue_on_failure: bool = True,
    clear_logcat_on_start: bool = True,
    monkey_seed: Optional[int] = None,
    monkey_events: Optional[int] = None,
) -> Dict[str, object]:
    """按指定时长对目标包执行 monkey 稳定性测试。

    speed 模式差异：
    - normal: throttle=300ms, events_per_min=300（压力较低）
    - fast: throttle=120ms, events_per_min=700（默认，中高压）
    - stress: throttle=60ms, events_per_min=1200（高压）

    说明：
    - 若显式传入 monkey_events，则直接使用该值。
    - 否则按 max(1000, events_per_min * duration_minutes) 估算默认事件数。
    - monkey_whitelist_packages 可指定 monkey 允许交互的包白名单；若为空则仅使用 package。
    """
    speed_profiles = {
        "normal": {"throttle": 300, "events_per_min": 300},
        "fast": {"throttle": 120, "events_per_min": 700},
        "stress": {"throttle": 60, "events_per_min": 1200},
    }
    if speed not in speed_profiles:
        raise ValueError(f"speed 仅支持 {list(speed_profiles)}，当前={speed}")

    ensure_adb(adb_path)
    devices = resolve_devices(adb_path, [device] if device else [], all_devices)
    missing_pkg_devices = [dev for dev in devices if not check_package_installed(adb_path, dev, package)]
    if missing_pkg_devices:
        raise RuntimeError(
            f"请检查包名应用是否安装：{package}；未安装到手机设备：{missing_pkg_devices}"
        )

    profile = speed_profiles[speed]
    duration_sec = duration_minutes * 60
    final_events = monkey_events if monkey_events is not None else max(1000, profile["events_per_min"] * max(1, duration_minutes))
    whitelist = monkey_whitelist_packages or [package]
    if package not in whitelist:
        whitelist = [package, *whitelist]
    # 去重并保留顺序
    whitelist = list(dict.fromkeys(whitelist))

    report_root = Path(log_dir).expanduser().resolve() / dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    report_root.mkdir(parents=True, exist_ok=True)

    global_stop_event = threading.Event()
    cfg = ToolConfig(
        package=package,
        monkey_packages=whitelist,
        report_root=report_root,
        duration_sec=duration_sec,
        monkey_events=final_events,
        monkey_throttle_ms=profile["throttle"],
        monkey_seed=monkey_seed,
        monkey_pct_touch=45,
        monkey_pct_motion=25,
        monkey_pct_nav=10,
        monkey_pct_syskeys=10,
        monkey_pct_appswitch=10,
        adb_path=adb_path,
        continue_on_failure=continue_on_failure,
        clear_logcat=clear_logcat_on_start,
        devices=devices,
        external_stop_event=global_stop_event,
    )
    validate_monkey_percent(cfg)

    print(f"[{now_str()}] 启动测试 package={package}, devices={devices}, speed={speed}")
    print(f"[{now_str()}] 关键字(Crash检测): {CRASH_DETECT_KEYS}")
    print(f"[{now_str()}] 关键字(ANR检测): {ANR_DETECT_KEYS}")

    results: List[DeviceResult] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, len(devices))) as pool:
        future_map = {pool.submit(run_one_device, cfg, dev): dev for dev in devices}
        try:
            for fu in concurrent.futures.as_completed(future_map):
                dev = future_map[fu]
                try:
                    r = fu.result()
                    results.append(r)
                    print(f"[{now_str()}] 设备完成：{dev}, failures={len(r.failures)}, log_dir={r.run_dir}")
                except Exception as exc:
                    print(f"[{now_str()}] 设备执行异常：{dev}, err={exc}")
                    results.append(DeviceResult(dev, False, str(exc), [], report_root / safe_name(dev)))
        except KeyboardInterrupt:
            print(f"[{now_str()}] ⚠️ 收到 Ctrl+C，通知所有设备停止...")
            global_stop_event.set()

    crash_count = sum(1 for r in results for e in r.failures if e.event_type == CRASH)
    anr_count = sum(1 for r in results for e in r.failures if e.event_type == ANR)
    total = crash_count + anr_count

    summary = {
        "package": package,
        "devices": devices,
        "log_root": str(report_root),
        "total_failures": total,
        "crash_count": crash_count,
        "anr_count": anr_count,
        "ok": total == 0,
    }
    print(f"[{now_str()}] 最终统计：{summary}")
    return summary


if __name__ == "__main__":

    run_monkey(
        duration_minutes=10,
        # package="com.hotpotgames.happysave.global",
        package="com.dramawin.lucky.shorts",
        log_dir="/Users/admin/TestLog/monkey_log/",
        speed="fast",
        # speed="normal",
    )

    # 下面是加白名单，只在指定包名运行
    # run_monkey(
    #     duration_minutes=10,
    #     package="com.hoshi.ai.companion.personal.app",
    #     log_dir="/Users/admin/TestLog/monkey_log/",
    #     speed="fast",
    #     monkey_whitelist_packages=[
    #         "com.hoshi.ai.companion.personal.app",
    #     ],
    # )
