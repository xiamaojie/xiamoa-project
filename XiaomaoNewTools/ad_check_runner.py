from __future__ import annotations

import json
import re
import select
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, TextIO, cast

# ==================================================
# 固定路径（按工程相对路径拼接）
# ==================================================
PROJECT_ROOT = Path(__file__).resolve().parents[1]
INSTALL_SCRIPT = str(PROJECT_ROOT / "XiamaoTools" / "install_aabV7.py")
XIAMAO_PYTHON = str(PROJECT_ROOT / ".venv" / "bin" / "python")

# ==================================================
# 时序参数
# ==================================================
PROMOTE_WAIT_SEC = 25  # 开启 Firebase 日志后，等待 adjust_Get_Promote 的最长秒数
AFTER_HOME_WINDOW_SEC = 60  # 捕获 promote 后回到桌面，用于监控 ad_impression 的窗口秒数
LOCK_UNLOCK_DELAY_SEC = 0.5  # 触发锁屏/解锁兜底时，两次 KEYCODE_POWER 之间的间隔
LOCK_UNLOCK_TRIGGER_SEC = 20  # 在桌面停留该秒数后若无新增曝光，则触发锁屏/解锁兜底
IMPRESSION_TARGET_COUNT = 3  # 目标广告曝光次数

AFTER_IMPRESSION_SLEEP_SEC = 5  # 每次广告曝光展示后等待多少秒再去 kill/重启应用
RESTART_APP_STABILIZE_SEC = 3  # 重启应用后等待多少秒再继续回到桌面监控

# ==================================================
# 输出文件
# ==================================================
OUT_DIR = Path(__file__).resolve().parent
APP_CTX_PATH = OUT_DIR / "app_ctx.json"
FIREBASE_LOG_PATH = OUT_DIR / "firebase.log"

# ==================================================
# install_aabV7 输出解析
# ==================================================
INSTALL_DONE_FLAG = "🎉 AAB 安装完成！"
PACKAGE_PATTERN = re.compile(r"📛 包名:\s*(\S+)")

LAUNCH_COMPONENT_PATTERN = re.compile(r"使用预解析候选启动:\s*(\S+/\S+)")
LAUNCH_COMPONENT_FALLBACK_PATTERN = re.compile(
    r"启动命令:\s*adb\s+shell\s+am\s+start\s+-n\s+(\S+/\S+)"
)

# ==================================================
# Firebase 日志匹配
# ==================================================
PROMOTE_PATTERN = re.compile(
    r"Logging event:.*name=adjust_Get_Promote,.*ad_network=([^,\]}]+)",
    re.IGNORECASE,
)

# ad_impression 日志：要求 name 精确为 ad_impression，避免匹配 ad_impression_ai 等
AD_IMPRESSION_PATTERN = re.compile(
    r"Logging event:.*name=ad_impression\b[^,}]*,.*ad_platform=(TopOn|BigoAds|Pangle|Mintegral)\b",
    re.IGNORECASE,
)

_KV_VALUE_CLASS = r"([^,\]}]+)"


def _iso_now_seconds() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _seconds_between(start: str, end: str) -> Optional[float]:
    try:
        return (datetime.fromisoformat(end) - datetime.fromisoformat(start)).total_seconds()
    except (ValueError, TypeError):
        return None


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
    return m.group(1) if m else None


def _normalize_platform(p: str) -> str:
    mapping = {
        "topon": "TopOn",
        "bigoads": "BigoAds",
        "pangle": "Pangle",
        "mintegral": "Mintegral",
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
    already_on = (
        current_app == package
        and fa_tag.strip().upper() == "VERBOSE"
        and fa_svc_tag.strip().upper() == "VERBOSE"
    )
    if already_on:
        print("✅ Firebase 日志已开启，跳过重复设置")
        return

    subprocess.run(["adb", "shell", "setprop", "debug.firebase.analytics.app", package], check=True)
    subprocess.run(["adb", "shell", "setprop", "log.tag.FA", "VERBOSE"], check=True)
    subprocess.run(["adb", "shell", "setprop", "log.tag.FA-SVC", "VERBOSE"], check=True)


def start_firebase_logcat_pipe() -> subprocess.Popen[str]:
    subprocess.run(["adb", "logcat", "-c"], check=True)
    # 清理上次运行的本地日志，避免文件无限增长占用磁盘
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


def lock_unlock() -> None:
    subprocess.run(["adb", "shell", "input", "keyevent", "KEYCODE_POWER"], check=True)
    time.sleep(LOCK_UNLOCK_DELAY_SEC)
    subprocess.run(["adb", "shell", "input", "keyevent", "KEYCODE_POWER"], check=True)


def force_stop(package: str) -> None:
    subprocess.run(["adb", "shell", "am", "force-stop", package], check=True)


def start_by_component(component: str) -> None:
    subprocess.run(["adb", "shell", "am", "start", "-n", component], check=True)


def start_by_monkey(package: str) -> None:
    subprocess.run(
        ["adb", "shell", "monkey", "-p", package, "-c", "android.intent.category.LAUNCHER", "1"],
        check=True,
    )


def restart_app(package: str, component: Optional[str], ctx: AppCtx, after_impression: int) -> None:
    """
    重启策略：
    1) 有 component -> am start -n
    2) 否则 -> monkey 兜底
    """
    if component:
        print(f"🚀 用 Component 重启应用：{component}")
        start_by_component(component)
        ctx["launch_strategy"] = "component"
        ctx["actions"].append(
            {
                "time": _iso_now_seconds(),
                "action": "restart_by_component",
                "component": component,
                "after_impression": after_impression,
            }
        )
    else:
        print(f"🚀 未解析到 Component，使用 monkey 兜底重启：{package}")
        start_by_monkey(package)
        ctx["launch_strategy"] = "monkey"
        ctx["actions"].append(
            {
                "time": _iso_now_seconds(),
                "action": "restart_by_monkey",
                "package": package,
                "after_impression": after_impression,
            }
        )
    write_app_ctx(ctx)


# ==================================================
# 事件解析（实时）
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
        platform = _normalize_platform(m2.group(1))
        ad_unit = _extract_kv(line, "ad_unit_name")
        ad_format = _extract_kv(line, "ad_format")
        ad_source = _extract_kv(line, "ad_source")
        value = _extract_kv(line, "value")
        currency = _extract_kv(line, "currency")
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

        print(
            f"🎉 ad_impression#{idx}：ad_platform={platform}, "
            f"ad_unit={ad_unit}, ad_format={ad_format}, ad_source={ad_source}, value={value}, currency={currency}, time={ts}"
        )
        write_app_ctx(ctx)


def pump_logcat_for_duration(
    proc: subprocess.Popen[str],
    duration_sec: float,
    ctx: AppCtx,
    stop_when: Optional[Callable[[AppCtx], bool]] = None,
) -> None:
    if proc.stdout is None:
        return
    stdout_io: TextIO = cast(TextIO, proc.stdout)
    fd = stdout_io.fileno()

    end_at = time.time() + duration_sec
    with FIREBASE_LOG_PATH.open("a", encoding="utf-8") as f:
        lines_since_flush = 0
        last_flush = time.time()
        while time.time() < end_at:
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

            # 批量 flush：每 200 行或 1 秒触发一次，避免逐行刷盘开销
            now = time.time()
            if lines_since_flush >= 200 or (now - last_flush) >= 1:
                f.flush()
                lines_since_flush = 0
                last_flush = now
            handle_log_line(line, ctx)

        # 窗口结束后确保剩余缓冲落盘
        f.flush()


# ==================================================
# 主流程
# ==================================================
def main() -> None:
    ctx: AppCtx = {
        "package": None,
        "launch_component": None,
        "launch_component_source": None,  # preparse / start_cmd / none
        "launch_strategy": None,          # component / monkey
        "install_done_time": None,
        "firebase_log_start_time": None,
        "promote": None,
        "ad_impressions": [],
        "actions": [],
        "result": None,
        "fail_reason": None,
    }
    write_app_ctx(ctx)

    print("🚀 Runner：安装 → 20s归因 → 曝光(3次) → 曝光后 force-stop + 重启（component优先/monkey兜底）")

    proc_install = subprocess.Popen(
        [XIAMAO_PYTHON, INSTALL_SCRIPT],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
    )

    package: Optional[str] = None
    launch_component: Optional[str] = None
    logcat_proc: Optional[subprocess.Popen[str]] = None

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
            
            # 允许 component 缺失，后续用 monkey 兜底
            if launch_component is None:
                ctx["launch_component_source"] = "none"
                write_app_ctx(ctx)
                print("⚠️ 未解析到启动 Component：后续重启将使用 monkey 兜底")

            ctx["install_done_time"] = _iso_now_seconds()
            write_app_ctx(ctx)

            print("🎯 捕获安装完成：立刻开启 Firebase Debug + 开始采集 FA/FA-SVC")
            enable_firebase_debug(package)
            ctx["firebase_log_start_time"] = _iso_now_seconds()
            write_app_ctx(ctx)
            logcat_proc = start_firebase_logcat_pipe()
            break

    if logcat_proc is None:
        ctx["result"] = "FAIL"
        ctx["fail_reason"] = "未进入 Firebase 日志采集阶段（install 未完成或异常）"
        write_app_ctx(ctx)
        print("❌ FAIL：未进入 Firebase 日志采集阶段")
        sys.exit(1)

    assert package is not None

    try:
        print(f"⏳ 等待 adjust_Get_Promote（最长 {PROMOTE_WAIT_SEC}s）")

        def promote_found(c: AppCtx) -> bool:
            return c.get("promote") is not None

        pump_logcat_for_duration(logcat_proc, PROMOTE_WAIT_SEC, ctx, stop_when=promote_found)

        if ctx.get("promote") is None:
            ctx["result"] = "FAIL"
            ctx["fail_reason"] = f"{PROMOTE_WAIT_SEC}s 内未检测到 adjust_Get_Promote"
            write_app_ctx(ctx)
            print(f"❌ FAIL：{PROMOTE_WAIT_SEC}s 内未检测到 adjust_Get_Promote")
            sys.exit(1)

        promote = cast(Dict[str, Any], ctx["promote"])
        promote_time = promote.get("time")
        firebase_start_time = ctx.get("firebase_log_start_time")
        install_done_time = ctx.get("install_done_time")
        start_time_for_duration = firebase_start_time or install_done_time
        promote_duration = (
            _seconds_between(str(start_time_for_duration), str(promote_time))
            if start_time_for_duration and promote_time
            else None
        )
        if promote_duration is not None:
            print(f"⏱ adjust_Get_Promote 耗时：{promote_duration:.1f}s（Firebase 日志开启→promote）")
        if promote_duration is not None:
            print(f"🏠 已捕获 adjust_Get_Promote：返回桌面（耗时 {promote_duration:.1f}s）")
        else:
            print("🏠 已捕获 adjust_Get_Promote：返回桌面")
        press_home()

        print(f"📡 监控 ad_impression（目标 {IMPRESSION_TARGET_COUNT} 次）")
        while True:
            impressions = cast(List[Dict[str, Any]], ctx.get("ad_impressions", []))
            count = len(impressions)
            if count >= IMPRESSION_TARGET_COUNT:
                print(f"🎯 已达成广告曝光目标：{count}/{IMPRESSION_TARGET_COUNT}")
                break

            before = count
            print(f"⏳ 桌面窗口 {AFTER_HOME_WINDOW_SEC}s（当前 {before}/{IMPRESSION_TARGET_COUNT}）")

            def new_impression_or_target(c: AppCtx) -> bool:
                imps = cast(List[Dict[str, Any]], c.get("ad_impressions", []))
                return len(imps) >= IMPRESSION_TARGET_COUNT or len(imps) > before

            # 先观察 LOCK_UNLOCK_TRIGGER_SEC，无新增则触发锁屏/解锁兜底
            lock_unlock_window = min(LOCK_UNLOCK_TRIGGER_SEC, AFTER_HOME_WINDOW_SEC)
            if lock_unlock_window > 0:
                pump_logcat_for_duration(logcat_proc, lock_unlock_window, ctx, stop_when=new_impression_or_target)
                impressions = cast(List[Dict[str, Any]], ctx.get("ad_impressions", []))
                after = len(impressions)
                if after >= IMPRESSION_TARGET_COUNT:
                    print(f"🎯 已达成广告曝光目标：{after}/{IMPRESSION_TARGET_COUNT}")
                    break
                if after == before:
                    print(f"🔒 {LOCK_UNLOCK_TRIGGER_SEC}s 内无新增 ad_impression：锁屏→0.5s→解锁（兜底触发）")
                    lock_unlock()
                before = after

            # 继续观察剩余窗口
            remaining_window = max(AFTER_HOME_WINDOW_SEC - lock_unlock_window, 0)
            if remaining_window > 0:
                pump_logcat_for_duration(logcat_proc, remaining_window, ctx, stop_when=new_impression_or_target)

            impressions = cast(List[Dict[str, Any]], ctx.get("ad_impressions", []))
            after = len(impressions)

            if after >= IMPRESSION_TARGET_COUNT:
                print(f"🎯 已达成广告曝光目标：{after}/{IMPRESSION_TARGET_COUNT}")
                break

            if after == before:
                print("🏠 HOME → force-stop 兜底重启尝试")
                press_home()
                force_stop(package)
                ctx["actions"].append(
                    {
                        "time": _iso_now_seconds(),
                        "action": "force_stop",
                        "package": package,
                        "after_impression": after,
                    }
                )
                write_app_ctx(ctx)

                restart_app(package, launch_component, ctx, after_impression=after)

                time.sleep(RESTART_APP_STABILIZE_SEC)
                print("🏠 兜底重启后回桌面继续监控")
                press_home()
                continue

            latest = impressions[-1]
            idx = int(latest.get("index", after))

            print(f"⏱ 捕获 ad_impression#{idx} 后等待 {AFTER_IMPRESSION_SLEEP_SEC}s")
            time.sleep(AFTER_IMPRESSION_SLEEP_SEC)

            print("🏠 HOME → force-stop 关闭广告")
            press_home()
            force_stop(package)
            ctx["actions"].append(
                {"time": _iso_now_seconds(), "action": "force_stop", "package": package, "after_impression": idx}
            )
            write_app_ctx(ctx)

            restart_app(package, launch_component, ctx, after_impression=idx)

            time.sleep(RESTART_APP_STABILIZE_SEC)
            print("🏠 重启后回桌面继续监控")
            press_home()

        ctx["result"] = "PASS"
        ctx["fail_reason"] = None
        write_app_ctx(ctx)

        promote = cast(Dict[str, Any], ctx["promote"])
        print("\n🎉 最终结果：广告曝光 & 买量归因均正常。")
        print(f"  - package: {ctx['package']}")
        print(f"  - launch_component: {ctx.get('launch_component')} (source={ctx.get('launch_component_source')})")
        print(f"  - launch_strategy: {ctx.get('launch_strategy')}")
        print(f"  - adjust_Get_Promote: time={promote.get('time')} ad_network={promote.get('ad_network')}")

        for imp in cast(List[Dict[str, Any]], ctx.get("ad_impressions", [])):
            print(
                f"  - ad_impression#{imp.get('index')}: time={imp.get('time')}, "
                f"ad_platform={imp.get('ad_platform')}, ad_unit={imp.get('ad_unit_name')}, "
                f"ad_format={imp.get('ad_format')}, ad_source={imp.get('ad_source')}, value={imp.get('value')}"
            )

        sys.exit(0)

    finally:
        try:
            logcat_proc.terminate()
        except ProcessLookupError:
            pass


if __name__ == "__main__":
    main()
