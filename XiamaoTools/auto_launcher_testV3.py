"""
AutoLauncherTest V3（单文件版）

目标：
- 保持与 V2 相同的测试结果与主流程
- 去掉对外部安装/清理脚本的进程级依赖
- 保留 APK/AAB 安装、默认桌面设置、Firebase 监听、monkey 观察等核心能力
"""

import json
import os
import re
import select
import subprocess
import sys
import tempfile
import threading
import time
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Sequence, TextIO, cast
from androguard.core.apk import APK
from androguard.core.axml import ResParserError
import uiautomator2 as u2

from loguru import logger
logger.remove()
logger.add(lambda msg: None, level="ERROR")
# ==================================================
# 固定路径 / 配置
# ==================================================
PROJECT_ROOT = Path(__file__).resolve().parents[1]
BUNDLETOOL_JAR = "/Users/admin/bundletool.jar"
DEFAULT_PACKAGE_DIR = Path("/Users/admin/Downloads")
# 支持指定包路径；为空时默认从 DEFAULT_PACKAGE_DIR 取最新 APK/AAB
PACKAGE_PATH = ""
# 广告后重启完成后的右滑开关；不影响“设置默认桌面完成”后的固定右滑
RIGHT_SWIPE_SWITCH = False

# ==================================================
# 输出文件 / 路径
# ==================================================
OUT_DIR = Path(__file__).resolve().parent
APP_CTX_PATH = OUT_DIR / "auto_launcher_ctx.json"
FIREBASE_LOG_PATH = OUT_DIR / "auto_launcher_firebase.log"
MONKEY_BLACKLIST_FILE = OUT_DIR / "monkey_blacklist_pixel.txt"

# ==================================================
# 时序 / 配置
# ==================================================
PROMOTE_WAIT_SEC = 100  # 历史遗留参数：原本用于等待 promote买量 事件；当前流程已不再强依赖，仅保留兼容
FIREBASE_PARAM_DELAY_SEC = 10  # 安装完成并启动监听后，主线程额外等待的秒数，用于给应用和埋点初始化留缓冲
IMPRESSION_TARGET = 10  # 目标广告曝光次数；达到该次数后可判定曝光目标达成
LAUNCH_WAIT = 0  # 应用启动后的额外等待秒数；默认不额外等待，直接进入后续 UI 查找
MONKEY_DURATION_MIN = 15  # monkey 计划运行时长（分钟）
MONKEY_EVENTS_PER_MIN = 200  # monkey 每分钟注入的事件数；值越大，页面切换和扰动越频繁
MONKEY_THROTTLE_MS = 400  # monkey 相邻事件之间的间隔毫秒数；值越大，事件节奏越慢
MONKEY_OBSERVE_SEC = MONKEY_DURATION_MIN * 60 + 30  # monkey 运行时长（含 30 秒缓冲）

MONKEY_CMD_BASE = [
    "--throttle", str(MONKEY_THROTTLE_MS),
    "--pct-touch", "55",
    "--pct-motion", "10",
    "--pct-nav", "20",
    "--pct-appswitch", "3",
    "--pct-anyevent", "10",
    "--pct-syskeys", "2",
]
MONKEY_BLACKLIST_PACKAGES = [
    "com.android.settings",
    "com.github.metacubex.clash.meta",
]

TRUSTED_LAUNCHER_PACKAGES = {
    "com.google.android.apps.nexuslauncher",
    "com.sec.android.app.launcher",
    "com.miui.home",
    "com.htc.launcher",
    "com.android.launcher3",
    "com.android.settings",
    "com.google.android.settings",
    "com.motorola.launcher3",
}

LAUNCH_ACTIVITY_KEYWORDS = [
    "Splash", "SplashActivity", "SplashScreen", "SplashScreenActivity",
    "Launch", "LauncherActivity", "LaunchActivity", "AppLaunch", "AppStart",
    "StartActivity", "StartUpActivity", "StartScreen",
    "WelcomeActivity", "WelcomeScreen", "IntroActivity", "Onboarding",
    "GuideActivity", "Boot", "LoadingActivity",
    "MainActivity", "MainPage", "HomeActivity", "IndexActivity", "EntryPoint",
    "StartupActivity", "EntryActivity",
]

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
    params_count: int
    raw_log: str


@dataclass
class ParsedPackageInfo:
    package_name: str
    app_name: str
    launcher_candidates: List[str] = field(default_factory=list)
    splash_candidates: List[str] = field(default_factory=list)


@dataclass
class InstallResult:
    package: str
    app_name: str
    launch_component: Optional[str]
    launch_component_source: str
    package_file: str
    package_type: str


AppCtx = Dict[str, Any]


def _iso_now_seconds() -> str:
    return datetime.now().isoformat(timespec="seconds")


def write_app_ctx(ctx: AppCtx) -> None:
    APP_CTX_PATH.write_text(json.dumps(ctx, indent=2, ensure_ascii=False))


def terminate_proc(proc: Optional[subprocess.Popen[str]]) -> None:
    if proc is None:
        return
    try:
        proc.terminate()
    except ProcessLookupError:
        pass


def run_command(cmd: Sequence[str], desc: str = "", timeout: int = 180) -> subprocess.CompletedProcess[str]:
    text = desc or " ".join(cmd)
    print(f"🔧 正在执行：{text}")
    try:
        result = subprocess.run(
            list(cmd),
            check=True,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"命令超时: {text}") from exc
    except subprocess.CalledProcessError as exc:
        detail = exc.stderr or exc.stdout or ""
        raise RuntimeError(f"命令失败: {text}\n{detail.strip()}") from exc

    if result.stdout.strip():
        print(result.stdout.strip())
    return result


def find_latest_package_file(directory: Path) -> Path:
    if not directory.is_dir():
        raise FileNotFoundError(f"❌ 指定目录不存在: {directory}")
    candidates = []
    for ext in (".aab", ".apk"):
        candidates.extend([p for p in directory.glob(f"*{ext}") if p.is_file()])
    if not candidates:
        raise FileNotFoundError(f"❌ 未找到任何 AAB/APK 文件于目录: {directory}")
    return max(candidates, key=lambda p: p.stat().st_mtime)


def ensure_adb() -> None:
    run_command(["adb", "start-server"], "启动 adb server", timeout=15)
    run_command(["adb", "version"], "检查 adb", timeout=15)


def ensure_aab_dependencies() -> None:
    ensure_adb()
    run_command(["java", "-version"], "检查 Java", timeout=15)
    if not os.path.isfile(BUNDLETOOL_JAR):
        raise FileNotFoundError(f"❌ bundletool jar 文件不存在: {BUNDLETOOL_JAR}")


def get_connected_devices() -> List[str]:
    result = run_command(["adb", "devices"], "获取设备列表", timeout=15)
    devices = [
        line.split()[0]
        for line in result.stdout.splitlines()
        if line.strip() and not line.startswith("List of devices") and line.strip().endswith("device")
    ]
    if not devices:
        raise RuntimeError("未检测到连接的 Android 设备，请检查设备连接")
    print(f"📱 已连接设备: {devices}")
    return devices


def _read_apk_bytes_to_temp(apk_bytes: bytes) -> str:
    with tempfile.NamedTemporaryFile(suffix=".apk", delete=False) as tmp_apk:
        tmp_apk.write(apk_bytes)
        return tmp_apk.name


def _build_activity_regex(package_name: str) -> re.Pattern[str]:
    keywords = "|".join(re.escape(k) for k in LAUNCH_ACTIVITY_KEYWORDS)
    pattern = rf"{re.escape(package_name)}/([\w\.]*({keywords})[\w\.]*)"
    return re.compile(pattern, re.IGNORECASE)


def _normalize_component(package_name: str, activity_name: str) -> str:
    if activity_name.startswith("."):
        return f"{package_name}/{activity_name}"
    if "/" in activity_name:
        return activity_name
    return f"{package_name}/{activity_name}"


def _get_app_name_via_aapt2(apk_path: str) -> Optional[str]:
    try:
        result = subprocess.run(
            ["aapt2", "dump", "badging", apk_path],
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return None

    for line in result.stdout.splitlines():
        match = re.search(r"application-label:'([^']*)'", line)
        if match:
            return match.group(1)
    return None


def parse_apk_info(apk_path: str) -> ParsedPackageInfo:
    if not os.path.isfile(apk_path):
        raise FileNotFoundError(f"❌ APK 文件不存在: {apk_path}")

    apk = APK(apk_path)
    package_name = apk.get_package()
    try:
        app_name = apk.get_app_name()
    except ResParserError:
        app_name = _get_app_name_via_aapt2(apk_path) or package_name

    launcher_candidates: List[str] = []
    splash_candidates: List[str] = []
    try:
        manifest = apk.get_android_manifest_xml()
        for app in manifest.findall("application"):
            for activity in app.findall("activity"):
                name = activity.get("{http://schemas.android.com/apk/res/android}name") or ""
                component = _normalize_component(package_name, name)
                for intent_filter in activity.findall("intent-filter"):
                    actions = [
                        a.get("{http://schemas.android.com/apk/res/android}name")
                        for a in intent_filter.findall("action")
                    ]
                    categories = [
                        c.get("{http://schemas.android.com/apk/res/android}name")
                        for c in intent_filter.findall("category")
                    ]
                    if "android.intent.action.MAIN" in actions and "android.intent.category.LAUNCHER" in categories:
                        launcher_candidates.append(component)
                if any(k.lower() in name.lower() for k in LAUNCH_ACTIVITY_KEYWORDS):
                    splash_candidates.append(component)
    except Exception as exc:
        print(f"⚠️ 解析 Manifest 启动信息失败：{exc}")

    print(f"📛 包名: {package_name}")
    print(f"📌 应用名称: {app_name}")
    return ParsedPackageInfo(
        package_name=package_name,
        app_name=app_name or package_name,
        launcher_candidates=launcher_candidates,
        splash_candidates=splash_candidates,
    )


def parse_apks_info(apks_path: str) -> ParsedPackageInfo:
    if not zipfile.is_zipfile(apks_path):
        raise ValueError(f"❌ 文件不是有效的 ZIP/APKS: {apks_path}")
    with zipfile.ZipFile(apks_path, "r") as zf:
        apk_files = [name for name in zf.namelist() if name.endswith(".apk")]
        if not apk_files:
            raise RuntimeError("❌ APKS 中未找到任何 APK 文件")
        tmp_apk_path = _read_apk_bytes_to_temp(zf.read(apk_files[0]))
    try:
        return parse_apk_info(tmp_apk_path)
    finally:
        os.remove(tmp_apk_path)


def try_get_package_name_from_apk(apk_path: str) -> Optional[str]:
    try:
        return APK(apk_path).get_package()
    except Exception as exc:
        print(f"⚠️ 快速解析包名失败：{exc}")
        return None


def try_get_package_name_from_apks(apks_path: str) -> Optional[str]:
    if not zipfile.is_zipfile(apks_path):
        return None
    with zipfile.ZipFile(apks_path, "r") as zf:
        apk_files = [name for name in zf.namelist() if name.endswith(".apk")]
        if not apk_files:
            return None
        tmp_apk_path = _read_apk_bytes_to_temp(zf.read(apk_files[0]))
    try:
        return try_get_package_name_from_apk(tmp_apk_path)
    finally:
        os.remove(tmp_apk_path)


def uninstall_package(package_name: str) -> None:
    if not package_name:
        return
    subprocess.run(["adb", "shell", "pm", "clear", package_name], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    result = subprocess.run(["adb", "uninstall", package_name], capture_output=True, text=True)
    if "Success" in result.stdout:
        print(f"✅ 已卸载旧包: {package_name}")
    else:
        detail = result.stdout.strip() or result.stderr.strip()
        print(f"⚠️ 卸载旧包结果: {detail or '未安装或卸载失败'}")


def install_apk_to_device(apk_path: str, device_id: str) -> None:
    print(f"📲 正在安装到设备：{device_id}")
    result = subprocess.run(
        ["adb", "-s", device_id, "install", "-r", apk_path],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0 or ("Success" not in result.stdout and result.stderr.strip()):
        raise RuntimeError(
            f"设备 {device_id} 安装 APK 失败: "
            f"{result.stderr.strip() or result.stdout.strip() or result.returncode}"
        )
    print(f"✅ 设备 {device_id} 安装成功")


def generate_apks(aab_path: str, output_apks_path: str) -> None:
    run_command(
        [
            "java", "-jar", BUNDLETOOL_JAR,
            "build-apks",
            f"--bundle={aab_path}",
            f"--output={output_apks_path}",
            "--overwrite",
            "--mode=universal",
        ],
        "生成 APKS",
        timeout=300,
    )


def install_apks_to_device(apks_path: str, device_id: str) -> None:
    run_command(
        [
            "java", "-jar", BUNDLETOOL_JAR,
            "install-apks",
            f"--apks={apks_path}",
            f"--device-id={device_id}",
        ],
        f"安装到设备 {device_id}",
        timeout=300,
    )


def get_launcher_activity(package_name: str) -> Optional[str]:
    try:
        result = subprocess.run(
            ["adb", "shell", "cmd", "package", "resolve-activity", "--brief", package_name],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError:
        return None
    lines = [line.strip() for line in result.stdout.splitlines() if "/" in line]
    return lines[0] if lines else None


def try_start_component(component: str) -> bool:
    result = subprocess.run(
        ["adb", "shell", "am", "start", "-n", component],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return result.returncode == 0


def start_app_with_strategy(package_name: str, candidates: Sequence[str]) -> tuple[Optional[str], str]:
    print("🚀 尝试启动应用...")

    for cand in candidates:
        print(f"🔍 使用预解析候选启动: {cand}")
        print(f"👉 启动命令: adb shell am start -n {cand}")
        subprocess.run(["adb", "shell", "am", "start", "-n", cand], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return cand, "preparse"

    launcher = get_launcher_activity(package_name)
    if launcher:
        print(f"🔍 检测到 Launcher Activity: {launcher}")
        if try_start_component(launcher):
            print(f"👉 启动命令: adb shell am start -n {launcher}")
            print("采用第1种 LauncherActivity 启动方式")
            return launcher, "start_cmd"
        print("⚠️ LauncherActivity 启动失败，切换下一方案...")

    print("🔍 使用扩展 Splash / Main Activity 匹配策略...")
    dumpsys_output = subprocess.run(
        ["adb", "shell", "dumpsys", "package", package_name],
        capture_output=True,
        text=True,
    ).stdout
    splash_match = _build_activity_regex(package_name).search(dumpsys_output)
    if splash_match:
        activity_path = _normalize_component(package_name, splash_match.group(1))
        print(f"✨ 命中扩展 Activity：{splash_match.group(1)}")
        print(f"👉 启动命令: adb shell am start -n {activity_path}")
        subprocess.run(["adb", "shell", "am", "start", "-n", activity_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print("采用第2种扩展 Splash/MainActivity 启动方式")
        return activity_path, "start_cmd"

    print("⚠️ 扩展 Activity 未匹配，继续使用 monkey ...")
    monkey_cmd = ["adb", "shell", "monkey", "-p", package_name, "-c", "android.intent.category.LAUNCHER", "1"]
    print(f"✨ 启动命令: {' '.join(monkey_cmd)}")
    print("采用第3种 monkey 启动方式")
    subprocess.run(monkey_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    return None, "monkey"


def install_apk_and_collect_info(apk_path: Path) -> InstallResult:
    ensure_adb()
    devices = get_connected_devices()
    package_name = try_get_package_name_from_apk(str(apk_path))
    if package_name:
        print(f"准备安装：包名={package_name}")
        uninstall_package(package_name)
    else:
        print("⚠️ 未能解析到包名，后续卸载/启动可能受影响")
    for device in devices:
        install_apk_to_device(str(apk_path), device)

    parsed: Optional[ParsedPackageInfo] = None
    if package_name:
        try:
            parsed = parse_apk_info(str(apk_path))
        except Exception as exc:
            print(f"⚠️ APK 信息解析失败：{exc}")

    candidates = parsed.launcher_candidates + parsed.splash_candidates if parsed else []
    resolved_package = parsed.package_name if parsed else package_name
    if not resolved_package:
        raise RuntimeError("安装阶段未获取到包名")
    launch_component, source = start_app_with_strategy(resolved_package, candidates)
    print("🎉 APK 安装流程完成！")
    return InstallResult(
        package=resolved_package,
        app_name=parsed.app_name if parsed else resolved_package,
        launch_component=launch_component,
        launch_component_source=source,
        package_file=str(apk_path),
        package_type="apk",
    )


def install_aab_and_collect_info(aab_path: Path) -> InstallResult:
    ensure_aab_dependencies()
    devices = get_connected_devices()
    with tempfile.TemporaryDirectory() as tmp_dir:
        apks_path = str(Path(tmp_dir) / "output.apks")
        generate_apks(str(aab_path), apks_path)
        package_name = try_get_package_name_from_apks(apks_path)
        if package_name:
            uninstall_package(package_name)
        else:
            print("⚠️ 未能解析包名，跳过卸载步骤")
        for device in devices:
            install_apks_to_device(apks_path, device)
        parsed: Optional[ParsedPackageInfo] = None
        if package_name:
            try:
                parsed = parse_apks_info(apks_path)
            except Exception as exc:
                print(f"⚠️ APK 信息解析失败：{exc}，使用兜底启动")

        candidates = parsed.launcher_candidates + parsed.splash_candidates if parsed else []
        resolved_package = parsed.package_name if parsed else package_name
        if not resolved_package:
            raise RuntimeError("安装阶段未获取到包名")
        launch_component, source = start_app_with_strategy(resolved_package, candidates)
    print("🎉 AAB 安装完成！")
    return InstallResult(
        package=resolved_package,
        app_name=parsed.app_name if parsed else resolved_package,
        launch_component=launch_component,
        launch_component_source=source,
        package_file=str(aab_path),
        package_type="aab",
    )


def install_target_package(package_path: Path) -> InstallResult:
    suffix = package_path.suffix.lower()
    if suffix == ".apk":
        return install_apk_and_collect_info(package_path)
    if suffix == ".aab":
        return install_aab_and_collect_info(package_path)
    raise ValueError(f"不支持的安装包后缀: {suffix}")


def adb_lines(args: Sequence[str]) -> List[str]:
    try:
        result = subprocess.run(
            list(args),
            capture_output=True,
            text=True,
            timeout=15,
        )
    except subprocess.TimeoutExpired:
        return []
    if result.returncode != 0:
        return []
    return result.stdout.strip().splitlines()


def get_home_launchers() -> List[str]:
    print("[+] 正在检测可设为主屏幕的应用...")
    lines = adb_lines(
        ["adb", "shell", "cmd", "package", "query-activities", "-a", "android.intent.action.MAIN", "-c", "android.intent.category.HOME"]
    )
    packages = set()
    for line in lines:
        match = re.search(r"packageName=(\S+)", line)
        if match:
            packages.add(match.group(1))
    return sorted(packages)


def is_suspicious_launcher(package_name: str) -> bool:
    if package_name in TRUSTED_LAUNCHER_PACKAGES:
        return False

    try:
        third_pkgs = subprocess.run(
            ["adb", "shell", "pm", "list", "packages", "-3"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if third_pkgs.returncode == 0 and f"package:{package_name}" in third_pkgs.stdout:
            return True
    except (subprocess.TimeoutExpired, OSError, subprocess.SubprocessError):
        pass

    try:
        path_info = subprocess.run(
            ["adb", "shell", "pm", "path", package_name],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if path_info.returncode == 0 and "/data/app/" in path_info.stdout:
            return True
    except (subprocess.TimeoutExpired, OSError, subprocess.SubprocessError):
        pass

    return False


def clean_fake_launchers() -> subprocess.CompletedProcess[str]:
    print("🧹 预清理：检测并卸载可疑启动器")
    logs: List[str] = ["🔍 Android 伪启动器检测与清理工具", ""]

    devices = adb_lines(["adb", "devices"])
    if len(devices) < 2 or "device" not in "\n".join(devices):
        raise RuntimeError("未检测到已连接的 Android 设备，请检查 USB 调试和连接。")

    home_pkgs = get_home_launchers()
    if not home_pkgs:
        logs.append("[!] 未找到任何可设为主屏幕的应用。")
        return subprocess.CompletedProcess(args=["internal_clean"], returncode=0, stdout="\n".join(logs), stderr="")

    logs.append(f"[+] 共检测到 {len(home_pkgs)} 个 HOME 应用:")
    for pkg in home_pkgs:
        logs.append(f"    - {pkg}")

    suspicious = [pkg for pkg in home_pkgs if is_suspicious_launcher(pkg)]
    if not suspicious:
        logs.append("")
        logs.append("✅ 未发现可疑的第三方启动器，系统干净！")
        return subprocess.CompletedProcess(args=["internal_clean"], returncode=0, stdout="\n".join(logs), stderr="")

    logs.append("")
    logs.append(f"⚠️  发现 {len(suspicious)} 个可疑启动器:")
    for pkg in suspicious:
        logs.append(f"    ❌ {pkg}")

    failed: List[str] = []
    for pkg in suspicious:
        logs.append(f"[+] 正在卸载: {pkg}")
        result = subprocess.run(["adb", "uninstall", pkg], capture_output=True, text=True)
        if result.returncode == 0 and "Success" in result.stdout:
            logs.append("    ✓ 卸载成功")
        else:
            detail = result.stdout.strip() or result.stderr.strip() or f"returncode={result.returncode}"
            logs.append(f"    ✗ 卸载失败: {detail}")
            failed.append(f"{pkg}: {detail}")

    if failed:
        logs.append("")
        logs.append("❌ 卸载失败的包:")
        for item in failed:
            logs.append(f"    - {item}")
    else:
        logs.append("")
        logs.append("✅ 清理完成！建议重启设备以确保彻底生效。")

    return subprocess.CompletedProcess(args=["internal_clean"], returncode=0, stdout="\n".join(logs), stderr="")


def kill_monkey_process() -> None:
    try:
        ps_out = subprocess.run(
            ["adb", "shell", "ps"],
            capture_output=True,
            text=True,
            timeout=5,
        ).stdout
        pids = []
        for line in ps_out.splitlines():
            if "com.android.commands.monkey" in line:
                parts = line.split()
                for part in parts:
                    if part.isdigit():
                        pids.append(part)
                        break
        if not pids:
            print("🧹 未发现 monkey 进程")
            return
        for pid in pids:
            subprocess.run(["adb", "shell", "kill", "-9", pid], check=False)
        print(f"🧹 已结束 monkey 进程: {', '.join(pids)}")
    except Exception as exc:
        print(f"⚠️ 清理 monkey 进程失败: {exc}")


def monkey_supports(option: str) -> bool:
    try:
        out = subprocess.run(
            ["adb", "shell", "monkey", "--help"],
            capture_output=True,
            text=True,
            timeout=4,
        )
        return option in out.stdout
    except Exception as exc:
        print(f"⚠️ 检测 monkey 选项失败({option}): {exc}")
        return False


def _adb(*args: str, capture: bool = True, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["adb", *args],
        check=check,
        capture_output=capture,
        text=True,
    )


def wifi_status() -> str:
    try:
        res = subprocess.run(
            ["adb", "shell", "dumpsys", "wifi"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        for line in res.stdout.splitlines():
            if "Wi-Fi is" in line:
                return line.strip()
        return res.stdout.strip()[:120] or "unknown"
    except Exception as exc:
        return f"wifi status unknown ({exc})"


def get_connectivity_status() -> str:
    try:
        res = subprocess.run(
            ["adb", "shell", "dumpsys", "connectivity"],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except Exception as exc:
        return f"connectivity unknown ({exc})"

    output = res.stdout or ""
    active_match = re.search(r"Active default network:\s*(\S+)", output)
    if not active_match or active_match.group(1) == "none":
        return "NO_NETWORK"

    has_vpn_connected = "VPN CONNECTED" in output
    has_is_vpn = "IS_VPN" in output
    has_validated = "IS_VALIDATED" in output

    if has_vpn_connected and has_is_vpn:
        if "IS_VPN&EVER_VALIDATED&IS_VALIDATED" in output or ("IS_VPN" in output and "IS_VALIDATED" in output):
            return "VPN_ON_AND_VALIDATED"
        return "VPN_ON_NOT_VALIDATED"

    if has_validated:
        return "NETWORK_OK_NO_VPN"

    return "NO_NETWORK"


def wait_for_network_recovery(timeout_sec: float = 4.0, interval_sec: float = 1.0) -> Dict[str, Any]:
    start = time.time()
    last_status = "UNKNOWN"
    while time.time() - start < timeout_sec:
        last_status = get_connectivity_status()
        if last_status in {"NETWORK_OK_NO_VPN", "VPN_ON_AND_VALIDATED"}:
            return {
                "ok": True,
                "status": last_status,
                "waited_sec": round(time.time() - start, 2),
            }
        time.sleep(interval_sec)
    return {
        "ok": False,
        "status": last_status,
        "waited_sec": round(time.time() - start, 2),
    }


def wifi_disable() -> None:
    try:
        _adb("shell", "svc", "wifi", "disable", capture=False)
        print(f"📴 Wi-Fi 已关闭，状态: {wifi_status()}")
    except Exception as exc:
        print(f"⚠️ 关闭 Wi-Fi 失败: {exc}")


def wifi_enable() -> Dict[str, Any]:
    try:
        _adb("shell", "svc", "wifi", "enable", capture=False)
        print(f"📶 Wi-Fi 已开启，状态: {wifi_status()}")
        network_check = wait_for_network_recovery(timeout_sec=4.0, interval_sec=1.0)
        if network_check["ok"]:
            print(
                f"🌐 网络恢复确认成功：status={network_check['status']} "
                f"waited={network_check['waited_sec']}s"
            )
        else:
            print(
                f"⚠️ 网络恢复确认未通过，但继续执行：status={network_check['status']} "
                f"waited={network_check['waited_sec']}s"
            )
        return network_check
    except Exception as exc:
        print(f"⚠️ 开启 Wi-Fi 失败: {exc}")
        return {"ok": False, "status": f"wifi_enable_error ({exc})", "waited_sec": 0.0}


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
    def _worker() -> None:
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
        except Exception as exc:
            print(f"⚠️ force-stop 失败: {exc}")

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
            if RIGHT_SWIPE_SWITCH:
                time.sleep(1)
                swipe_right_once()
                ctx["actions"].append(
                    {
                        "time": _iso_now_seconds(),
                        "action": "swipe_right_after_restart",
                        "after_impression": after_impression,
                        "delay_after_restart_sec": 1,
                    }
                )
            write_app_ctx(ctx)
        except Exception as exc:
            print(f"⚠️ 重启失败: {exc}")

    threading.Thread(target=_worker, daemon=True).start()


def _get_prop(prop: str) -> str:
    out = subprocess.run(["adb", "shell", "getprop", prop], check=True, capture_output=True, text=True)
    return out.stdout.strip()


def enable_firebase_debug(package: str) -> None:
    current_app = _get_prop("debug.firebase.analytics.app")
    fa_tag = _get_prop("log.tag.FA")
    fa_svc_tag = _get_prop("log.tag.FA-SVC")
    if current_app == package and fa_tag.upper() == "VERBOSE" and fa_svc_tag.upper() == "VERBOSE":
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


def force_stop(package: str) -> None:
    subprocess.run(["adb", "shell", "am", "force-stop", package], check=True)


def start_by_component(component: str) -> None:
    subprocess.run(["adb", "shell", "am", "start", "-n", component], check=True)


def start_by_monkey(package: str) -> None:
    subprocess.run(
        ["adb", "shell", "monkey", "-p", package, "-c", "android.intent.category.LAUNCHER", "1"],
        check=True,
    )


def _parse_logcat_time_prefix(line: str) -> Optional[str]:
    match = re.match(r"(\d{2})-(\d{2})\s+(\d{2}:\d{2}:\d{2}\.\d{3})", line)
    if not match:
        return None
    year = datetime.now().year
    month, day, hms = match.group(1), match.group(2), match.group(3)
    try:
        dt = datetime.strptime(f"{year}-{month}-{day} {hms}", "%Y-%m-%d %H:%M:%S.%f")
        return dt.isoformat(timespec="milliseconds")
    except ValueError:
        return None


def _extract_kv(raw: str, key: str) -> Optional[str]:
    pattern = re.compile(re.escape(key) + "=" + _KV_VALUE_CLASS, re.IGNORECASE)
    match = pattern.search(raw)
    if match:
        return match.group(1)
    idx = raw.lower().find(key.lower() + "=")
    if idx != -1:
        tail = raw[idx + len(key) + 1:]
        for sep in [",", "}", "]"]:
            cut = tail.split(sep)[0]
            if cut:
                return cut.strip()
    return None


def _extract_bundle_fields(raw: str) -> Dict[str, str]:
    fields: Dict[str, str] = {}
    match = re.search(r"params=Bundle\[(.*)]", raw)
    if not match:
        return fields
    content = match.group(1)
    for key, value in re.findall(r"([A-Za-z0-9_]+)=([^,\]}]+)", content):
        fields[key.lower()] = value
    return fields


def _normalize_platform(value: str) -> str:
    mapping = {
        "topon": "TopOn",
        "bigoads": "BigoAds",
        "pangle": "Pangle",
        "mintegral": "Mintegral",
        "admob": "Admob",
    }
    return mapping.get(value.strip().lower(), value)


def _count_bundle_params(raw: str) -> int:
    marker = "params=Bundle["
    start = raw.find(marker)
    if start == -1:
        return 0
    tail = raw[start + len(marker):].strip()
    if not tail:
        return 0
    content = ""
    if tail.startswith("{"):
        depth = 0
        for ch in tail:
            if ch == "{":
                depth += 1
                if depth == 1:
                    continue
            if ch == "}":
                depth -= 1
                if depth == 0:
                    break
            if depth >= 1:
                content += ch
    else:
        end = tail.find("]")
        content = tail[:end] if end != -1 else tail

    parts = []
    buf = ""
    depth = 0
    for ch in content:
        if ch == "{":
            depth += 1
        elif ch == "}" and depth > 0:
            depth -= 1
        if ch == "," and depth == 0:
            if buf.strip():
                parts.append(buf.strip())
            buf = ""
        else:
            buf += ch
    if buf.strip():
        parts.append(buf.strip())
    return len(parts)


def handle_log_line(line: str, ctx: AppCtx) -> None:
    if ctx.get("promote") is None:
        match = PROMOTE_PATTERN.search(line)
        if match:
            ad_network = match.group(1).strip()
            ts = _parse_logcat_time_prefix(line) or _iso_now_seconds()
            ctx["promote"] = PromoteInfo(time=ts, ad_network=ad_network, raw_log=line.strip()).__dict__
            print(f"✅ PROMOTE_OK：ad_network={ad_network} time={ts}")
            write_app_ctx(ctx)
            return

    match = AD_IMPRESSION_PATTERN.search(line)
    if not match:
        return

    fields = _extract_bundle_fields(line)
    platform = _normalize_platform(fields.get("ad_platform") or _extract_kv(line, "ad_platform") or "unknown")
    ad_unit = fields.get("ad_unit_name") or _extract_kv(line, "ad_unit_name")
    ad_format = fields.get("ad_format") or _extract_kv(line, "ad_format")
    ad_source = fields.get("ad_source") or _extract_kv(line, "ad_source")
    value = fields.get("value") or _extract_kv(line, "value")
    params_count = _count_bundle_params(line)
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
        params_count=params_count,
        raw_log=line.strip(),
    )
    impressions.append(item.__dict__)

    fmt = (ad_format or "unknown").strip()
    plat = (platform or "unknown").strip()
    fmt_counts = ctx.setdefault("ad_format_counts", {})
    plat_counts = ctx.setdefault("ad_platform_counts", {})
    params_list = ctx.setdefault("firebase_params_count_list", [])
    fmt_counts[fmt] = fmt_counts.get(fmt, 0) + 1
    plat_counts[plat] = plat_counts.get(plat, 0) + 1
    params_list.append(params_count)

    progress = f"{idx}/{IMPRESSION_TARGET}" if IMPRESSION_TARGET else f"{idx}"
    print(
        f"🎉 ad_impression#{idx}（{progress}）：ad_platform={platform}, "
        f"ad_unit={ad_unit}, ad_format={ad_format}, ad_source={ad_source}, "
        f"value={value}, params_count={params_count}, time={ts}"
    )
    print(f"    raw: {line.strip()}")
    print(f"    firebase埋点属性ad_impression参数长度 params_count: {params_count}")
    if params_count > 25:
        print(f"⚠️ 包含{params_count}个参数，超过了Firebase Analytics单个事件最多25个参数的限制，会影响收益上报")
    write_app_ctx(ctx)

    package = ctx.get("package")
    component = ctx.get("launch_component")
    if isinstance(package, str) and package:
        _force_stop_and_restart_later(package, component if isinstance(component, str) else None, 10, ctx, idx)


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
    with FIREBASE_LOG_PATH.open("a", encoding="utf-8") as output:
        lines_since_flush = 0
        last_flush = time.time()
        while True:
            if end_at is not None and time.time() >= end_at:
                break
            if stop_event is not None and stop_event.is_set():
                break
            if stop_when is not None and stop_when(ctx):
                break

            readable, _, _ = select.select([fd], [], [], 0.2)
            if not readable:
                continue

            line = stdout_io.readline()
            if not line:
                continue

            output.write(line)
            lines_since_flush += 1
            now = time.time()
            if lines_since_flush >= 200 or (now - last_flush) >= 1:
                output.flush()
                lines_since_flush = 0
                last_flush = now
            handle_log_line(line, ctx)

        output.flush()
    return time.time() - start


AD_CLOSE_KEYWORDS = ["关闭", "跳过", "Skip", "Close", "×", "X", "我知道了", "稍后再说"]


def close_ad_if_exists(device, quick: bool = False) -> bool:
    keywords = AD_CLOSE_KEYWORDS[:3] if quick else AD_CLOSE_KEYWORDS
    for keyword in keywords:
        elem = device(textContains=keyword)
        if elem.exists(timeout=0.3):
            try:
                elem.click()
                print(f"📢 关闭广告: {keyword}")
                time.sleep(0.3)
                return True
            except Exception as exc:
                print(f"⚠️ 点击广告关闭按钮失败({keyword}): {exc}")
    for text in ["关闭广告并继续打开", "关闭广告并继续", "关闭广告"]:
        elem = device(textContains=text)
        if elem.exists(timeout=0.3):
            try:
                elem.click()
                print(f"📢 关闭开屏广告: {text}")
                time.sleep(0.3)
                return True
            except Exception as exc:
                print(f"⚠️ 点击开屏广告关闭失败({text}): {exc}")
    return False


def wait_until_exists(selector_list: Sequence[Any], timeout: float = 5, interval: float = 0.5) -> Any:
    end = time.time() + timeout
    while time.time() < end:
        for selector in selector_list:
            if selector.exists(timeout=0.01):
                return selector
        time.sleep(interval)
    return None


def _get_wm_size() -> Optional[tuple[int, int]]:
    try:
        out = subprocess.check_output(["adb", "shell", "wm", "size"], text=True).strip()
    except Exception as exc:
        print(f"⚠️ 获取屏幕分辨率失败: {exc}")
        return None
    for line in out.splitlines():
        match = re.search(r"(Physical|Override) size:\s*(\d+)x(\d+)", line)
        if match:
            return int(match.group(2)), int(match.group(3))
    print(f"⚠️ 未解析到分辨率: {out}")
    return None


def swipe_right_once() -> None:
    size = _get_wm_size()
    if not size:
        return
    width, height = size
    start_x = max(0, min(width - 1, int(width * 200 / 1080)))
    end_x = max(0, min(width - 1, int(width * 900 / 1080)))
    y = max(0, min(height - 1, int(height * 1200 / 2400)))
    print(f"➡️ 右滑一次: adb shell input swipe {start_x} {y} {end_x} {y} 300")
    subprocess.run(["adb", "shell", "input", "swipe", str(start_x), str(y), str(end_x), str(y), "300"], check=True)


def set_default_launcher(package: str, app_name: str, ctx: Optional[AppCtx] = None) -> None:
    device = u2.connect()
    device.implicitly_wait(10)

    print("📴 先关闭 Wi-Fi（避免开屏广告）")
    wifi_disable()

    print(f"停止应用: {package}")
    try:
        device.app_stop(package)
    except Exception as exc:
        print(f"停止应用异常（可忽略）: {exc}")

    print(f"启动应用: {package}")
    device.app_start(package)
    if LAUNCH_WAIT > 0:
        print(f"启动后等待 {LAUNCH_WAIT}s...")
        time.sleep(LAUNCH_WAIT)

    close_ad_if_exists(device)

    print("等待 Continue/继续 按钮（最多 25s）")
    continue_selectors = [
        device(text="Continue"),
        device(text="continue"),
        device(text="CONTINUE"),
        device(text="继续"),
        device(textContains="继续"),
        device(textContains="Continue"),
    ]
    cont_btn = wait_until_exists(continue_selectors, timeout=25, interval=0.5)
    if not cont_btn:
        raise AssertionError("未找到 Continue/继续 按钮，终止流程")
    print('点击 "Continue/继续" 按钮')
    cont_btn.click()
    time.sleep(6)

    print("📶 启用 Wi-Fi（继续后恢复网络）")
    network_check = wifi_enable()
    if ctx is not None:
        ctx["actions"].append(
            {
                "time": _iso_now_seconds(),
                "action": "wifi_enable_network_check",
                "network_ok": network_check.get("ok"),
                "network_status": network_check.get("status"),
                "waited_sec": network_check.get("waited_sec"),
            }
        )
        write_app_ctx(ctx)

    print(f"选择默认桌面项（包含文本）：{app_name}")
    launcher_candidates = [
        device(textContains=app_name),
        device(descriptionContains=app_name),
        device(text=app_name),
        device(description=app_name),
    ]
    before_dump = device.dump_hierarchy()
    launcher_item = wait_until_exists(launcher_candidates, timeout=8, interval=0.5)
    if launcher_item:
        launcher_item.click()
    else:
        raise AssertionError(f"未找到包含应用名称的选项: {app_name}")

    time.sleep(2)
    after_dump = device.dump_hierarchy()
    if before_dump == after_dump:
        raise AssertionError("点击默认桌面选项后界面未变化，可能未成功跳转到桌面")
    print("✅ 默认桌面设置完成（检测到界面已变化）")
    swipe_right_once()


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


def firebase_listener(
    package: str,
    ctx: AppCtx,
    _promote_event: threading.Event,
    stop_event: threading.Event,
    _promote_fail_event: threading.Event,
) -> None:
    print("🎯 开启 Firebase Debug + 日志监听")
    enable_firebase_debug(package)
    ctx["firebase_log_start_time"] = _iso_now_seconds()
    write_app_ctx(ctx)
    proc = start_firebase_logcat_pipe()
    try:
        print(f"📡 监听 ad_impression，目标 {IMPRESSION_TARGET} 次（跳过 promote 必达）")

        def impression_target(current_ctx: AppCtx) -> bool:
            imps = cast(List[Dict[str, Any]], current_ctx.get("ad_impressions", []))
            return len(imps) >= IMPRESSION_TARGET

        pump_logcat_for_duration(proc, None, ctx, stop_when=impression_target, stop_event=stop_event)
    finally:
        terminate_proc(proc)


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
        "firebase_params_count_list": [],
        "preclean": None,
    }
    write_app_ctx(ctx)

    try:
        result = clean_fake_launchers()
        ctx["preclean"] = {
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }
        write_app_ctx(ctx)
        if result.stdout:
            print(result.stdout, end="\n" if not result.stdout.endswith("\n") else "")
        if result.stderr:
            print(result.stderr, end="\n" if not result.stderr.endswith("\n") else "")
    except Exception as exc:
        ctx["preclean"] = {
            "returncode": None,
            "stdout": None,
            "stderr": None,
            "error": str(exc),
        }
        write_app_ctx(ctx)
        print(f"❌ FAIL：预清理启动器失败: {exc}")
        sys.exit(1)

    print("🚀 AutoLauncherTest V3：安装 → 立即监听 Firebase → 缓冲10s → 设置默认桌面 → monkey 监听广告")
    if PACKAGE_PATH:
        latest_file = Path(PACKAGE_PATH)
        if not latest_file.is_file():
            ctx["result"] = "FAIL"
            ctx["fail_reason"] = f"安装包路径不存在: {latest_file}"
            write_app_ctx(ctx)
            print("❌ FAIL：安装包路径不存在，请检查")
            sys.exit(1)
    else:
        try:
            latest_file = find_latest_package_file(DEFAULT_PACKAGE_DIR)
        except Exception as exc:
            ctx["result"] = "FAIL"
            ctx["fail_reason"] = f"查找最新安装包失败: {exc}"
            write_app_ctx(ctx)
            print(f"❌ FAIL：查找最新安装包失败: {exc}")
            sys.exit(1)

    package_mtime = datetime.fromtimestamp(latest_file.stat().st_mtime)
    package_suffix = latest_file.suffix.lower()
    print(f"📦 发现安装包类型: {package_suffix.lstrip('.')}")
    print(f"📦 安装包路径: {latest_file}")
    print(f"📦 安装包更新时间: {package_mtime}")

    try:
        install_result = install_target_package(latest_file)
    except Exception as exc:
        ctx["result"] = "FAIL"
        ctx["fail_reason"] = f"安装失败: {exc}"
        write_app_ctx(ctx)
        print(f"❌ FAIL：安装失败: {exc}")
        sys.exit(1)

    ctx["package"] = install_result.package
    ctx["app_name"] = install_result.app_name
    ctx["launch_component"] = install_result.launch_component
    ctx["launch_component_source"] = install_result.launch_component_source
    ctx["package_file"] = install_result.package_file
    ctx["package_type"] = install_result.package_type
    ctx["install_done_time"] = _iso_now_seconds()
    write_app_ctx(ctx)

    if install_result.launch_component is None:
        print("⚠️ 未解析到启动 Component：后续重启将使用 monkey 兜底")

    package = install_result.package
    app_name = install_result.app_name

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
        set_default_launcher(package, app_name or package, ctx)
    except Exception as exc:
        ctx["result"] = "FAIL"
        ctx["fail_reason"] = f"设置默认桌面失败: {exc}"
        write_app_ctx(ctx)
        print(f"❌ FAIL：设置默认桌面失败: {exc}")
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
            impressions = cast(List[Dict[str, Any]], ctx.get("ad_impressions", []))
            if len(impressions) >= IMPRESSION_TARGET:
                impressions_reached = True
                print(f"🎯 达到曝光目标：{len(impressions)}/{IMPRESSION_TARGET}")
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
            f"ad_format={imp.get('ad_format')}, ad_source={imp.get('ad_source')}, "
            f"value={imp.get('value')}, params_count={imp.get('params_count')}"
        )
    fmt_counts = ctx.get("ad_format_counts") or {}
    plat_counts = ctx.get("ad_platform_counts") or {}
    if fmt_counts:
        print("  - ad_format_counts:", fmt_counts)
    if plat_counts:
        print("  - ad_platform_counts:", plat_counts)
    params_list = ctx.get("firebase_params_count_list") or []
    if params_list:
        print("  - firebase_params_count_list:", params_list)

    sys.exit(0)


if __name__ == "__main__":
    main()
