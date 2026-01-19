from __future__ import annotations

import json
import re
import select
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, TextIO, cast

import uiautomator2 as u2

# ==================================================
# 固定路径（按你提供的绝对路径）
# ==================================================
PROJECT_ROOT = Path(__file__).resolve().parents[1]
INSTALL_SCRIPT = str(PROJECT_ROOT / "XiamaoTools" / "install_aabV7.py")
XIAMAO_PYTHON = str(PROJECT_ROOT / ".venv" / "bin" / "python")

# ==================================================
# 输出文件 / 路径
# ==================================================
OUT_DIR = Path(__file__).resolve().parent
APP_CTX_PATH = OUT_DIR / "auto_launcher_ctx.json"
FIREBASE_LOG_PATH = OUT_DIR / "auto_launcher_firebase.log"

# ==================================================
# 时序 / 配置
# ==================================================
PROMOTE_WAIT_SEC = 100  # 保留但跳过必达
FIREBASE_PARAM_DELAY_SEC = 10  # 安装启动后主线程延迟时间（等待应用稳定）
IMPRESSION_TARGET = 6  # 监听广告曝光次数目标
LAUNCH_WAIT = 0  # 启动后额外等待（默认 0，直接等待按钮出现）
# monkey 参数：以分钟和每分钟事件数控制
MONKEY_DURATION_MIN = 10  # monkey 运行时长（分钟）
MONKEY_EVENTS_PER_MIN = 200  # 每分钟事件数（更温和，偏监控曝光）
MONKEY_THROTTLE_MS = 400  # 事件节流
MONKEY_OBSERVE_SEC = MONKEY_DURATION_MIN * 60 + 30  # 观察窗口 = 时长 + buffer

# monkey 命令基础参数列表（除包名、事件数外）
MONKEY_CMD_BASE = [
    "--throttle", str(MONKEY_THROTTLE_MS),
    "--pct-touch", "55",
    "--pct-motion", "10",
    "--pct-nav", "20",
    "--pct-appswitch", "3",
    "--pct-anyevent", "10",
    "--pct-syskeys", "2",
]
MONKEY_BLACKLIST_FILE = OUT_DIR / "monkey_blacklist_pixel.txt"
MONKEY_BLACKLIST_PACKAGES = [
    "com.android.settings",
    "com.github.metacubex.clash.meta",
]

# ==================================================
# install_aabV7 输出解析
# ==================================================
INSTALL_DONE_FLAG = "🎉 AAB 安装完成！"
PACKAGE_PATTERN = re.compile(r"📛 包名:\s*(\S+)")
APP_NAME_PATTERN = re.compile(r"应用名称[:：]\s*(.+)")
LAUNCH_COMPONENT_PATTERN = re.compile(r"使用预解析候选启动:\s*(\S+/\S+)")
LAUNCH_COMPONENT_FALLBACK_PATTERN = re.compile(
    r"启动命令:\s*adb\s+shell\s+am\s+start\s+-n\s+(\S+/\S+)"
)

# ==================================================
# Firebase 日志匹配
# ==================================================
PROMOTE_PATTERN = re.compile(
    r"Logging event:.*name=adjust_Get_Promote,.*ad_network=([^,\]}]+)", re.IGNORECASE
)
AD_IMPRESSION_PATTERN = re.compile(
    r"Logging event:.*[, ]name=ad_impression[, ]",
    re.IGNORECASE,
)
_KV_VALUE_CLASS = r"([^,\]}]+)"


def _iso_now_seconds() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _parse_logcat_time_prefix(line: str) -> Optional[str]:
    m = re.match(r"(\d{2})-(\d{2})\s+(\d{2}:\d{2}:\d{2}\.\d{3})", line)
    if not m:
        return None
    year = datetime.now().year
    month, day, hms = m.group(1), m.group(2), m.group(3)
    try:
        dt = datetime.strptime(f"{year}-{month}-{day} {hms}", "%Y-%m-%d %H:%M:%S.%f")
        return dt.isoformat(timespec="milliseconds")
    except ValueError:
        return None


def _extract_kv(raw: str, key: str) -> Optional[str]:
    pattern = re.compile(re.escape(key) + "=" + _KV_VALUE_CLASS, re.IGNORECASE)
    m = pattern.search(raw)
    if m:
        return m.group(1)
    # 兜底：简单切片到下一个逗号/右括号
    idx = raw.lower().find(key.lower() + "=")
    if idx != -1:
        tail = raw[idx + len(key) + 1 :]
        for sep in [",", "}", "]"]:
            cut = tail.split(sep)[0]
            if cut:
                return cut.strip()
    return None


def _extract_bundle_fields(raw: str) -> Dict[str, str]:
    """
    粗略解析 params=Bundle[...] 内的 key=value 列表，适配部分值缺少逗号/大写等情况。
    """
    fields: Dict[str, str] = {}
    m = re.search(r"params=Bundle\\[(.*)\\]", raw)
    if not m:
        return fields
    content = m.group(1)
    for k, v in re.findall(r"([A-Za-z0-9_]+)=([^,\\]}]+)", content):
        fields[k.lower()] = v
    return fields


def _normalize_platform(p: str) -> str:
    mapping = {
        "topon": "TopOn",
        "bigoads": "BigoAds",
        "pangle": "Pangle",
        "mintegral": "Mintegral",
        "admob": "Admob",
    }
    return mapping.get(p.strip().lower(), p)


@dataclass
class PromoteInfo:
    time: str
    ad_network: str
    raw_log: str


@dataclass
class ImpressionInfo:
    index: int
    time: str
    ad_platform: str
    ad_unit_name: Optional[str]
    ad_format: Optional[str]
    ad_source: Optional[str]
    value: Optional[str]
    raw_log: str


AppCtx = Dict[str, Any]


def write_app_ctx(ctx: AppCtx) -> None:
    APP_CTX_PATH.write_text(json.dumps(ctx, indent=2, ensure_ascii=False))


def terminate_proc(proc: Optional[subprocess.Popen[str]]) -> None:
    if proc is None:
        return
    try:
        proc.terminate()
    except ProcessLookupError:
        pass


def kill_monkey_process() -> None:
    try:
        ps_out = subprocess.run(
            ["adb", "shell", "ps", "|", "grep", "monkey"],
            capture_output=True,
            text=True,
            timeout=5,
        ).stdout
        pids = []
        for line in ps_out.splitlines():
            if "com.android.commands.monkey" in line:
                parts = line.split()
                if len(parts) >= 2 and parts[1].isdigit():
                    pids.append(parts[1])
        if not pids:
            print("🧹 未发现 monkey 进程")
            return
        for pid in pids:
            subprocess.run(["adb", "shell", "kill", "-9", pid], check=False)
        print(f"🧹 已结束 monkey 进程: {', '.join(pids)}")
    except Exception as e:
        print(f"⚠️ 清理 monkey 进程失败: {e}")


def monkey_supports(option: str) -> bool:
    try:
        out = subprocess.run(
            ["adb", "shell", "monkey", "--help"],
            capture_output=True,
            text=True,
            timeout=4,
        )
        return option in out.stdout
    except Exception as e:
        print(f"⚠️ 检测 monkey 选项失败({option}): {e}")
        return False


def _adb(*args: str, capture: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run([
        "adb",
        *args,
    ], check=True, capture_output=capture, text=True)


def wifi_status() -> str:
    try:
        res = _adb("shell", "dumpsys", "wifi", "|", "grep", "Wi-Fi is", capture=True)
        return res.stdout.strip()
    except Exception as e:
        return f"wifi status unknown ({e})"


def wifi_disable() -> None:
    try:
        _adb("shell", "svc", "wifi", "disable", capture=False)
        status = wifi_status()
        print(f"📴 Wi-Fi 已关闭，状态: {status}")
    except Exception as e:
        print(f"⚠️ 关闭 Wi-Fi 失败: {e}")


def wifi_enable() -> None:
    try:
        _adb("shell", "svc", "wifi", "enable", capture=False)
        status = wifi_status()
        print(f"📶 Wi-Fi 已开启，状态: {status}")
    except Exception as e:
        print(f"⚠️ 开启 Wi-Fi 失败: {e}")


def generate_and_push_blacklist() -> None:
    content = "\n".join(MONKEY_BLACKLIST_PACKAGES) + "\n"
    MONKEY_BLACKLIST_FILE.write_text(content, encoding="utf-8")
    subprocess.run(
        ["adb", "push", str(MONKEY_BLACKLIST_FILE), "/sdcard/monkey_blacklist_pixel.txt"],
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    print(f"✅ 已推送 monkey 黑名单到 /sdcard/monkey_blacklist_pixel.txt（{len(MONKEY_BLACKLIST_PACKAGES)} 个包名）")


def _force_stop_and_restart_later(package: str, component: Optional[str], delay: float, ctx: AppCtx, after_impression: int) -> None:
    def _worker():
        time.sleep(delay)
        try:
            force_stop(package)
            ctx["actions"].append(
                {
                    "time": _iso_now_seconds(),
                    "action": "force_stop_after_impression",
                    "package": package,
                    "after_impression": after_impression,
                    "delay_sec": delay,
                }
            )
            write_app_ctx(ctx)
            print(f"🔪 ad_impression#{after_impression} 后 {delay}s: force-stop {package}")
        except Exception as e:
            print(f"⚠️ force-stop 失败: {e}")

        try:
            if component:
                print(f"🚀 ad_impression#{after_impression} 后重启（component）：{component}")
                start_by_component(component)
                ctx["launch_strategy"] = "component"
                ctx["actions"].append(
                    {
                        "time": _iso_now_seconds(),
                        "action": "restart_by_component",
                        "component": component,
                        "after_impression": after_impression,
                        "delay_sec": delay,
                    }
                )
            else:
                print(f"🚀 ad_impression#{after_impression} 后重启（monkey）：{package}")
                start_by_monkey(package)
                ctx["launch_strategy"] = "monkey"
                ctx["actions"].append(
                    {
                        "time": _iso_now_seconds(),
                        "action": "restart_by_monkey",
                        "package": package,
                        "after_impression": after_impression,
                        "delay_sec": delay,
                    }
                )
            write_app_ctx(ctx)
        except Exception as e:
            print(f"⚠️ 重启失败: {e}")

    t = threading.Thread(target=_worker, daemon=True)
    t.start()


# ==================================================
# ADB / Firebase debug
# ==================================================
def _get_prop(prop: str) -> str:
    out = subprocess.run(["adb", "shell", "getprop", prop], check=True, capture_output=True, text=True)
    return out.stdout.strip()


def enable_firebase_debug(package: str) -> None:
    current_app = _get_prop("debug.firebase.analytics.app")
    fa_tag = _get_prop("log.tag.FA")
    fa_svc_tag = _get_prop("log.tag.FA-SVC")
    already_on = current_app == package and fa_tag.strip().upper() == "VERBOSE" and fa_svc_tag.strip().upper() == "VERBOSE"
    if already_on:
        print("✅ Firebase 日志已开启，跳过重复设置")
        return

    subprocess.run(["adb", "shell", "setprop", "debug.firebase.analytics.app", package], check=True)
    subprocess.run(["adb", "shell", "setprop", "log.tag.FA", "VERBOSE"], check=True)
    subprocess.run(["adb", "shell", "setprop", "log.tag.FA-SVC", "VERBOSE"], check=True)


def start_firebase_logcat_pipe() -> subprocess.Popen[str]:
    subprocess.run(["adb", "logcat", "-c"], check=True)
    FIREBASE_LOG_PATH.write_text("")
    return subprocess.Popen(
        ["adb", "logcat", "-v", "time", "-s", "FA", "FA-SVC"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )


def press_home() -> None:
    subprocess.run(["adb", "shell", "input", "keyevent", "KEYCODE_HOME"], check=True)


def force_stop(package: str) -> None:
    subprocess.run(["adb", "shell", "am", "force-stop", package], check=True)


def start_by_component(component: str) -> None:
    subprocess.run(["adb", "shell", "am", "start", "-n", component], check=True)


def start_by_monkey(package: str) -> None:
    subprocess.run(
        ["adb", "shell", "monkey", "-p", package, "-c", "android.intent.category.LAUNCHER", "1"], check=True
    )


# ==================================================
# 日志解析
# ==================================================
def handle_log_line(line: str, ctx: AppCtx) -> None:
    if ctx.get("promote") is None:
        m = PROMOTE_PATTERN.search(line)
        if m:
            ad_network = m.group(1).strip()
            ts = _parse_logcat_time_prefix(line) or _iso_now_seconds()
            ctx["promote"] = PromoteInfo(time=ts, ad_network=ad_network, raw_log=line.strip()).__dict__
            print(f"✅ PROMOTE_OK：ad_network={ad_network} time={ts}")
            write_app_ctx(ctx)
            return

    m2 = AD_IMPRESSION_PATTERN.search(line)
    if m2:
        fields = _extract_bundle_fields(line)
        platform = _normalize_platform(
            fields.get("ad_platform") or _extract_kv(line, "ad_platform") or "unknown"
        )
        ad_unit = fields.get("ad_unit_name") or _extract_kv(line, "ad_unit_name")
        ad_format = fields.get("ad_format") or _extract_kv(line, "ad_format")
        ad_source = fields.get("ad_source") or _extract_kv(line, "ad_source")
        value = fields.get("value") or _extract_kv(line, "value")
        ts = _parse_logcat_time_prefix(line) or _iso_now_seconds()

        impressions: List[Dict[str, Any]] = ctx.setdefault("ad_impressions", [])
        idx = len(impressions) + 1

        item = ImpressionInfo(
            index=idx,
            time=ts,
            ad_platform=platform,
            ad_unit_name=ad_unit,
            ad_format=ad_format,
            ad_source=ad_source,
            value=value,
            raw_log=line.strip(),
        )
        impressions.append(item.__dict__)

        # 统计广告平台/类型次数
        fmt = (ad_format or "unknown").strip()
        plat = (platform or "unknown").strip()
        fmt_counts = ctx.setdefault("ad_format_counts", {})
        plat_counts = ctx.setdefault("ad_platform_counts", {})
        fmt_counts[fmt] = fmt_counts.get(fmt, 0) + 1
        plat_counts[plat] = plat_counts.get(plat, 0) + 1

        progress = f"{idx}/{IMPRESSION_TARGET}" if IMPRESSION_TARGET else f"{idx}"
        print(
            f"🎉 ad_impression#{idx}（{progress}）：ad_platform={platform}, "
            f"ad_unit={ad_unit}, ad_format={ad_format}, ad_source={ad_source}, value={value}, time={ts}"
        )
        print(f"    raw: {line.strip()}")
        write_app_ctx(ctx)

        pkg = ctx.get("package")
        comp = ctx.get("launch_component")
        if isinstance(pkg, str) and pkg:
            _force_stop_and_restart_later(pkg, comp if isinstance(comp, str) else None, 10, ctx, after_impression=idx)


def pump_logcat_for_duration(
    proc: subprocess.Popen[str],
    duration_sec: Optional[float],
    ctx: AppCtx,
    stop_when: Optional[Callable[[AppCtx], bool]] = None,
    stop_event: Optional[threading.Event] = None,
) -> float:
    if proc.stdout is None:
        return 0.0
    stdout_io: TextIO = cast(TextIO, proc.stdout)
    fd = stdout_io.fileno()

    start = time.time()
    end_at = start + duration_sec if duration_sec is not None else None
    with FIREBASE_LOG_PATH.open("a", encoding="utf-8") as f:
        lines_since_flush = 0
        last_flush = time.time()
        while True:
            if end_at is not None and time.time() >= end_at:
                break
            if stop_event is not None and stop_event.is_set():
                break
            if stop_when is not None and stop_when(ctx):
                break

            r, _, _ = select.select([fd], [], [], 0.2)
            if not r:
                continue

            line = stdout_io.readline()
            if not line:
                continue

            f.write(line)
            lines_since_flush += 1

            now = time.time()
            if lines_since_flush >= 200 or (now - last_flush) >= 1:
                f.flush()
                lines_since_flush = 0
                last_flush = now
            handle_log_line(line, ctx)

        f.flush()
    return time.time() - start


# ==================================================
# UI 相关
# ==================================================
AD_CLOSE_KEYWORDS = ["关闭", "跳过", "Skip", "Close", "×", "X", "我知道了", "稍后再说"]


def close_ad_if_exists(d, quick: bool = False) -> bool:
    keywords = AD_CLOSE_KEYWORDS[:3] if quick else AD_CLOSE_KEYWORDS
    for keyword in keywords:
        elem = d(textContains=keyword)
        if elem.exists(timeout=0.3):
            try:
                elem.click()
                print(f"📢 关闭广告: {keyword}")
                time.sleep(0.3)
                return True
            except Exception as e:
                print(f"⚠️ 点击广告关闭按钮失败({keyword}): {e}")
    ad_close_texts = ["关闭广告并继续打开", "关闭广告并继续", "关闭广告"]
    for txt in ad_close_texts:
        elem = d(textContains=txt)
        if elem.exists(timeout=0.3):
            try:
                elem.click()
                print(f"📢 关闭开屏广告: {txt}")
                time.sleep(0.3)
                return True
            except Exception as e:
                print(f"⚠️ 点击开屏广告关闭失败({txt}): {e}")
    return False


def wait_until_exists(selector_list, timeout=5, interval=0.5):
    end = time.time() + timeout
    while time.time() < end:
        for sel in selector_list:
            if sel.exists(timeout=0.01):
                return sel
        time.sleep(interval)
    return None


def click_by_percent(d, x_percent, y_percent):
    info = d.info
    width = info.get("displayWidth", 0)
    height = info.get("displayHeight", 0)
    x = int(width * x_percent / 100)
    y = int(height * y_percent / 100)
    d.click(x, y)
    return True


def set_default_launcher(package: str, app_name: str) -> None:
    d = u2.connect()
    d.implicitly_wait(10)

    print("📴 先关闭 Wi-Fi（避免开屏广告）")
    wifi_disable()

    print(f"停止应用: {package}")
    try:
        d.app_stop(package)
    except Exception as e:
        print(f"停止应用异常（可忽略）: {e}")

    print(f"启动应用: {package}")
    d.app_start(package)
    if LAUNCH_WAIT > 0:
        print(f"启动后等待 {LAUNCH_WAIT}s...")
        time.sleep(LAUNCH_WAIT)

    close_ad_if_exists(d)

    # 等待并点击“Continue/继续”按钮，文本包含匹配，超时 25s 未出现则终止
    print("等待 Continue/继续 按钮（最多 25s）")
    continue_selectors = [
        d(text="Continue"),
        d(text="continue"),
        d(text="CONTINUE"),
        d(text="继续"),
        d(textContains="继续"),
        d(textContains="Continue"),
    ]
    cont_btn = wait_until_exists(continue_selectors, timeout=25, interval=0.5)
    if not cont_btn:
        raise AssertionError("未找到 Continue/继续 按钮，终止流程")
    print('点击 "Continue/继续" 按钮')
    cont_btn.click()
    # 等页面跳转稳定
    time.sleep(6)

    print("📶 启用 Wi-Fi（继续后恢复网络）")
    wifi_enable()

    print(f"选择默认桌面项（包含文本）：{app_name}")
    launcher_candidates = [
        d(textContains=app_name),
        d(descriptionContains=app_name),
        d(text=app_name),
        d(description=app_name),
    ]
    before_dump = d.dump_hierarchy()
    launcher_item = wait_until_exists(launcher_candidates, timeout=8, interval=0.5)
    if launcher_item:
        launcher_item.click()
    else:
        raise AssertionError(f"未找到包含应用名称的选项: {app_name}")

    time.sleep(2)
    after_dump = d.dump_hierarchy()
    if before_dump == after_dump:
        raise AssertionError("点击默认桌面选项后界面未变化，可能未成功跳转到桌面")

    print("✅ 默认桌面设置完成（检测到界面已变化）")


# ==================================================
# monkey
# ==================================================
def run_monkey(package: str) -> subprocess.Popen[str]:
    events = MONKEY_DURATION_MIN * MONKEY_EVENTS_PER_MIN
    use_blacklist = monkey_supports("--pkg-blacklist-file")
    if use_blacklist:
        generate_and_push_blacklist()
    else:
        print("⚠️ 设备 monkey 不支持 --pkg-blacklist-file，跳过黑名单")
    cmd = ["adb", "shell", "monkey", "-p", package]
    if use_blacklist:
        cmd += ["--pkg-blacklist-file", "/sdcard/monkey_blacklist_pixel.txt"]
    cmd += MONKEY_CMD_BASE + ["-v", str(events)]
    print(f"启动 monkey：{' '.join(cmd)}（{MONKEY_DURATION_MIN} 分钟，约 {events} 事件）")
    return subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)


# ==================================================
# 线程：Firebase 日志监听
# ==================================================
def firebase_listener(
    package: str,
    ctx: AppCtx,
    _promote_event: threading.Event,  # 占位，当前跳过 promote 必达
    stop_event: threading.Event,
    _promote_fail_event: threading.Event,  # 占位
):
    print("🎯 开启 Firebase Debug + 日志监听")
    enable_firebase_debug(package)
    ctx["firebase_log_start_time"] = _iso_now_seconds()
    write_app_ctx(ctx)
    proc = start_firebase_logcat_pipe()
    try:
        # 直接监听广告曝光，达到目标或 stop_event 触发
        print(f"📡 监听 ad_impression，目标 {IMPRESSION_TARGET} 次（跳过 promote 必达）")

        def impression_target(c: AppCtx) -> bool:
            imps = cast(List[Dict[str, Any]], c.get("ad_impressions", []))
            return len(imps) >= IMPRESSION_TARGET

        pump_logcat_for_duration(proc, None, ctx, stop_when=impression_target, stop_event=stop_event)

    finally:
        terminate_proc(proc)


# ==================================================
# 主流程
# ==================================================
def main() -> None:
    ctx: AppCtx = {
        "package": None,
        "app_name": None,
        "launch_component": None,
        "launch_component_source": None,
        "launch_strategy": None,
        "install_done_time": None,
        "firebase_log_start_time": None,
        "promote": None,
        "ad_impressions": [],
        "actions": [],
        "result": None,
        "fail_reason": None,
        "ad_format_counts": {},
        "ad_platform_counts": {},
    }
    write_app_ctx(ctx)

    print("🚀 AutoLauncherTest：安装 → 立即监听 Firebase → 缓冲10s → 设置默认桌面 → monkey 监听广告")

    proc_install = subprocess.Popen(
        [XIAMAO_PYTHON, INSTALL_SCRIPT],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )

    package: Optional[str] = None
    app_name: Optional[str] = None
    launch_component: Optional[str] = None

    if proc_install.stdout is None:
        ctx["result"] = "FAIL"
        ctx["fail_reason"] = "install 脚本无 stdout"
        write_app_ctx(ctx)
        print("❌ FAIL：install 脚本无 stdout")
        sys.exit(1)

    for line in proc_install.stdout:
        print(line, end="")

        if package is None:
            mp = PACKAGE_PATTERN.search(line)
            if mp:
                package = mp.group(1).strip()
                ctx["package"] = package
                print(f"📦 捕获包名: {package}")
                write_app_ctx(ctx)

        if app_name is None:
            ma = APP_NAME_PATTERN.search(line)
            if ma:
                app_name = ma.group(1).strip()
                ctx["app_name"] = app_name
                print(f"🧭 捕获应用名称: {app_name}")
                write_app_ctx(ctx)

        if launch_component is None:
            m1 = LAUNCH_COMPONENT_PATTERN.search(line)
            if m1:
                launch_component = m1.group(1).strip()
                ctx["launch_component"] = launch_component
                ctx["launch_component_source"] = "preparse"
                print(f"🚀 捕获启动 Component(预解析): {launch_component}")
                write_app_ctx(ctx)

        if launch_component is None:
            m2 = LAUNCH_COMPONENT_FALLBACK_PATTERN.search(line)
            if m2:
                launch_component = m2.group(1).strip()
                ctx["launch_component"] = launch_component
                ctx["launch_component_source"] = "start_cmd"
                print(f"🚀 捕获启动 Component(启动命令 fallback): {launch_component}")
                write_app_ctx(ctx)

        if INSTALL_DONE_FLAG in line:
            if package is None:
                ctx["result"] = "FAIL"
                ctx["fail_reason"] = "安装完成但未解析到包名"
                write_app_ctx(ctx)
                print("❌ FAIL：安装完成但未解析到包名")
                sys.exit(1)
            if launch_component is None:
                ctx["launch_component_source"] = "none"
                write_app_ctx(ctx)
                print("⚠️ 未解析到启动 Component：后续重启将使用 monkey 兜底")

            ctx["install_done_time"] = _iso_now_seconds()
            write_app_ctx(ctx)
            break

    if package is None:
        ctx["result"] = "FAIL"
        ctx["fail_reason"] = "install 阶段未捕获包名"
        write_app_ctx(ctx)
        print("❌ FAIL：install 阶段未捕获包名")
        sys.exit(1)

    promote_event = threading.Event()
    stop_event = threading.Event()
    promote_fail_event = threading.Event()

    listener_thread = threading.Thread(
        target=firebase_listener,
        args=(package, ctx, promote_event, stop_event, promote_fail_event),
        daemon=True,
    )
    listener_thread.start()

    print(f"⏳ 主线程缓冲 {FIREBASE_PARAM_DELAY_SEC}s")
    time.sleep(FIREBASE_PARAM_DELAY_SEC)

    if promote_fail_event.is_set():
        print("监听线程判定失败，主流程退出")
        sys.exit(1)

    print("🔪 force-stop 应用，准备设置默认桌面")
    force_stop(package)
    ctx["actions"].append({"time": _iso_now_seconds(), "action": "force_stop_before_launcher", "package": package})
    write_app_ctx(ctx)

    try:
        set_default_launcher(package, app_name or package)
    except Exception as e:
        ctx["result"] = "FAIL"
        ctx["fail_reason"] = f"设置默认桌面失败: {e}"
        write_app_ctx(ctx)
        print(f"❌ FAIL：设置默认桌面失败: {e}")
        stop_event.set()
        sys.exit(1)
    if promote_fail_event.is_set():
        print("监听线程判定失败，主流程退出")
        stop_event.set()
        sys.exit(1)

    time.sleep(2)

    monkey_proc = run_monkey(package)
    impressions_reached = False
    try:
        start_poll = time.time()
        while True:
            imps = cast(List[Dict[str, Any]], ctx.get("ad_impressions", []))
            if len(imps) >= IMPRESSION_TARGET:
                impressions_reached = True
                print(f"🎯 达到曝光目标：{len(imps)}/{IMPRESSION_TARGET}")
                break
            if time.time() - start_poll >= MONKEY_OBSERVE_SEC:
                print(f"⏱ monkey 观察窗口 {MONKEY_OBSERVE_SEC}s 结束，未达曝光目标")
                break
            time.sleep(2)
    finally:
        terminate_proc(monkey_proc)
        kill_monkey_process()
        stop_event.set()

    if not impressions_reached:
        ctx["result"] = "FAIL"
        ctx["fail_reason"] = f"未达到广告曝光目标（{IMPRESSION_TARGET} 次）"
        write_app_ctx(ctx)
        print(f"❌ FAIL：未达到广告曝光目标（{IMPRESSION_TARGET} 次）")
        sys.exit(1)

    ctx["result"] = "PASS"
    ctx["fail_reason"] = None
    write_app_ctx(ctx)

    promote = cast(Dict[str, Any], ctx.get("promote", {}))
    print("\n🎉 最终结果：默认桌面设置完成，广告曝光目标达成。")
    print(f"  - package: {ctx.get('package')}")
    print(f"  - app_name: {ctx.get('app_name')}")
    print(f"  - launch_component: {ctx.get('launch_component')} (source={ctx.get('launch_component_source')})")
    if promote:
        print(f"  - adjust_Get_Promote: time={promote.get('time')} ad_network={promote.get('ad_network')}")
    for imp in cast(List[Dict[str, Any]], ctx.get("ad_impressions", [])):
        print(
            f"  - ad_impression#{imp.get('index')}: time={imp.get('time')}, "
            f"ad_platform={imp.get('ad_platform')}, ad_unit={imp.get('ad_unit_name')}, "
            f"ad_format={imp.get('ad_format')}, ad_source={imp.get('ad_source')}, value={imp.get('value')}"
        )
    fmt_counts = ctx.get("ad_format_counts") or {}
    plat_counts = ctx.get("ad_platform_counts") or {}
    if fmt_counts:
        print("  - ad_format_counts:", fmt_counts)
    if plat_counts:
        print("  - ad_platform_counts:", plat_counts)

    sys.exit(0)


if __name__ == "__main__":
    main()
