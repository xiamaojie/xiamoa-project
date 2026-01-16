"""
AppUpdateV5.py

功能概述：
- 从指定目录中找到最新的 APK 文件
- 校验手机时间与 NTP 服务器时间差
- 检查依赖（ADB）
- 使用 androguard 解析 APK 信息（包名、应用名、版本号、versionCode、targetSdk 等）
- 将当前版本信息写入 apkinfo.yaml，并打印上一次安装版本信息
- 自动卸载旧版本 APK
- 将最新 APK 安装到所有已连接设备
- 启动应用（优先级：Launcher Activity → 扩展 Splash/Main Activity → monkey）
- 可选：授予通知权限、调高音量、强行停止应用再重启等

注意：
- 历史版本记录文件为 apkinfo.yaml（与 AAB 版本的 appinfo.yaml 区分）
"""

import glob
import os
import re
import subprocess
import time
from typing import Optional, Dict, List
from concurrent.futures import ThreadPoolExecutor, Future, as_completed

from androguard.core.apk import APK
from androguard.core.axml import ResParserError
from loguru import logger
from datetime import datetime
import yaml
import ntplib

# 禁用 androguard 的 debug 日志
logger.remove()
logger.add(lambda msg: None, level="ERROR")

# 权限检查清单
# 禁用权限清单（全面禁止）
Disable_permission_list = {
    "REQUEST_INSTALL_PACKAGES": "用于安装 APK，Google Play 对此权限审核极为严格，仅限特定场景（如浏览器、企业分发）",
    "MANAGE_EXTERNAL_STORAGE": "访问所有共享存储内容，需充分说明必要性并通过 Google Play 特殊审核",
    "QUERY_ALL_PACKAGES": "可获取设备上所有已安装应用信息，存在隐私风险，需提供强理由",
    "BIND_DEVICE_ADMIN": "绑定设备管理员，涉及设备控制能力，易被滥用"
}
# 高危权限清单（非核心禁用）
List_of_high_risk_permissions = {
    "ACCESS_FINE_LOCATION": "获取精确位置",
    "ACCESS_BACKGROUND_LOCATION": "后台获取位置（需单独申请，且 Google Play 要求提供强必要性说明）",
    "WRITE_EXTERNAL_STORAGE": "Android 10 以下的传统外部存储读写权限",
    "READ_EXTERNAL_STORAGE": "Android 10 以下的传统外部存储读写权限",
    "READ_MEDIA_IMAGES": "Android 13+ 引入的细粒度媒体（图片）访问权限，需按需申请并说明用途；可用系统选择器代替",
    "READ_MEDIA_VIDEO": "Android 13+ 引入的细粒度媒体（视频）访问权限，需按需申请并说明用途；可用系统选择器代替",
    "USE_FULL_SCREEN_INTENT": "全屏通知"
}


# ===========================
# 通用工具：时间校验 & 依赖检查
# ===========================

def ensure_adb_server() -> None:
    """确保 adb server 已启动，启动失败抛出异常"""
    try:
        subprocess.run(["adb", "start-server"], check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=10)
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(f"ADB server 启动失败: {exc.stderr.decode().strip() if exc.stderr else exc}") from exc

def check_time_diff(max_diff_seconds: int = 60, ntp_timeout: int = 5) -> bool:
    """
    从 ADB 获取手机时间、从 NTP 获取服务器时间并进行对比。
    输出格式示例：
        成功从 NTP 服务器获取时间: pool.ntp.org
        手机本地时间: 2025-11-27 10:15:30
        NTP服务器时间: 2025-11-27 10:15:28.284071
        时间差（秒）: 1.715929
        ✔ 时间一致（差值在1分钟以内）
    """
    try:
        ensure_adb_server()
        # ---------- 1. 读取手机时间 ----------
        output = subprocess.check_output(
            ['adb', 'shell', "date +'%Y-%m-%d %H:%M:%S %Z'"],
            text=True
        ).strip()

        match = re.search(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})", output)
        if not match:
            raise ValueError(f"无法从ADB输出中提取时间: {output}")

        device_dt = datetime.strptime(match.group(1), "%Y-%m-%d %H:%M:%S")

        # ---------- 2. 获取 NTP 服务器时间 ----------
        NTP_SERVERS = [
            # 公共池
            "pool.ntp.org",
            "0.pool.ntp.org",
            "1.pool.ntp.org",
            "2.pool.ntp.org",
            "3.pool.ntp.org",
            "cn.pool.ntp.org",
            # 大厂节点
            "time.google.com",
            "time.cloudflare.com",
            "time.windows.com",
            "time.apple.com",
            # 国内稳定源
            "ntp.aliyun.com",
            "ntp1.aliyun.com",
            "time1.cloud.tencent.com",
            "time2.cloud.tencent.com",
            "ntp.ntsc.ac.cn",
        ]

        client = ntplib.NTPClient()
        server_dt = None
        last_error = None

        # 并发请求多个 NTP，取最快成功的
        with ThreadPoolExecutor(max_workers=min(5, len(NTP_SERVERS))) as executor:
            future_map = {
                executor.submit(client.request, host, version=3, timeout=ntp_timeout): host
                for host in NTP_SERVERS
            }
            for fut in as_completed(future_map):
                host = future_map[fut]
                try:
                    response = fut.result()
                    server_dt = datetime.fromtimestamp(response.tx_time)
                    print(f"成功从 NTP 服务器获取时间: {host}")
                    break
                except Exception as ntp_err:
                    last_error = ntp_err
                    continue

        if server_dt is None:
            raise RuntimeError(f"所有 NTP 服务器均不可用，最后错误：{last_error}")

        # ---------- 3. 输出两者时间对比 ----------
        print("手机本地时间:", device_dt)
        print("NTP服务器时间:", server_dt)

        diff = abs((device_dt - server_dt).total_seconds())
        print("时间差（秒）:", diff)

        if diff <= max_diff_seconds:
            print("✔ 时间一致（差值在1分钟以内）")
            return True
        else:
            print("✘ 时间不一致（超过1分钟）")
            return False
    except Exception as e:
        print(f"⚠️ 时间校验失败，已跳过：{e}")
        return False


def check_dependencies() -> None:
    """
    检查 ADB 是否可用。
    APK 安装不依赖 java/bundletool，仅保留 ADB 检查以保持行为一致性。
    """
    ensure_adb_server()
    try:
        subprocess.run(
            ["adb", "version"],
            check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        print("✅ ADB 已安装")
    except (subprocess.CalledProcessError, FileNotFoundError):
        raise EnvironmentError("❌ 未找到 ADB，请确保已安装并配置到 PATH")


def get_connected_devices() -> List[str]:
    """获取已连接的 Android 设备列表"""
    try:
        result = subprocess.run(["adb", "devices"], capture_output=True, text=True, check=True)
    except subprocess.CalledProcessError as exe:
        raise RuntimeError("ADB 命令执行失败，请检查 ADB 是否安装并正常运行") from exe

    devices = [
        line.split()[0]
        for line in result.stdout.splitlines()
        if line.strip() and not line.startswith("List of devices") and line.strip().endswith("device")
    ]
    if not devices:
        raise RuntimeError("未检测到连接的 Android 设备，请检查设备是否连接")
    print(f"📱 已连接设备: {devices}")
    return devices


def run_command(cmd: List[str], desc: str = "") -> None:
    """运行命令并输出结果，失败时抛出异常"""
    print(f"🔧 正在执行：{desc or ' '.join(cmd)}")
    try:
        result = subprocess.run(cmd, check=True, capture_output=True, text=True)
        print(f"✅ 成功：{desc or ' '.join(cmd)}")
        if result.stdout:
            print(result.stdout.strip())
    except subprocess.CalledProcessError as exe:
        err_msg = exe.stderr or exe.stdout or ""
        raise RuntimeError(f"❌ 执行失败：{' '.join(cmd)}\n错误信息：{err_msg.strip()}")


# ===========================
# APK 信息解析 & 历史版本记录
# ===========================

def extract_apk_info_from_apk(apk_path: str) -> Dict[str, Optional[str]]:
    """
    从 APK 文件中提取信息：包名、应用名、版本号、versionCode、target_sdk_version。
    并记录到 apkinfo.yaml（包含历史版本），返回预解析启动候选。
    """

    if not os.path.isfile(apk_path):
        raise FileNotFoundError(f"❌ APK 文件不存在: {apk_path}")

    print(f"📦 正在解析 APK: {apk_path}")

    package_name = None
    app_name = None
    version_name = None
    version_code = None
    target_sdk_version = None

    apk = None
    try:
        apk = APK(apk_path)

        package_name = apk.get_package()
        version_name = apk.get_androidversion_name()
        version_code = apk.get_androidversion_code()

        try:
            app_name = apk.get_app_name()
        except ResParserError as parse_err:
            print(f"⚠️ resources.arsc 解析失败: {parse_err}，应用名降级为包名。")
            app_name = package_name or "<unknown_app>"

        try:
            target_sdk_version = apk.get_target_sdk_version()

        except (AttributeError, ValueError, TypeError):
            target_sdk_version = None

    except Exception as parse_err:
        print(f"❌ APK 解析失败: {parse_err}")
        # 保持 None 值即可，不退出脚本

    print(f"📛 包名: {package_name}")
    print(f"📌 应用名称: {app_name}")
    print(f"📌 版本号: {version_name}")
    print(f"📌 versionCode: {version_code}")
    print(f"📌 targetSdkVersion: {target_sdk_version}")

    try:
        target_sdk_int = int(target_sdk_version) if target_sdk_version is not None else -1
    except (ValueError, TypeError):
        target_sdk_int = -1

    if target_sdk_int >= 35:
        print(f"📌 targetSdkVersion版本是: {target_sdk_version}")
    else:
        print(f"⚠️ targetSdkVersion小于35，当前版本是:{target_sdk_version}")

    # 权限检查
    permissions = []
    try:
        if apk is not None:
            permissions = apk.get_permissions() or []
    except Exception as perm_err:
        print(f"⚠️ 获取权限列表失败: {perm_err}")

    print(f"🔐 共申请权限 {len(permissions)} 个")

    def find_matches(target_dict, perm_list):
        target_upper = {k.upper(): v for k, v in target_dict.items()}
        hits = []
        for perm_name in perm_list:
            perm_upper = perm_name.upper()
            perm_suffix = perm_name.rsplit(".", 1)[-1].upper()
            if perm_upper in target_upper:
                hits.append((perm_name, target_upper[perm_upper]))
            elif perm_suffix in target_upper:
                hits.append((perm_name, target_upper[perm_suffix]))
        return hits

    disallowed_hits = find_matches(Disable_permission_list, permissions)
    high_risk_hits = find_matches(List_of_high_risk_permissions, permissions)

    if disallowed_hits:
        print("❌ 检测到禁用权限:")
        for perm, reason in disallowed_hits:
            print(f"    - {perm}: {reason}")
    else:
        print("✅ 未申请禁用权限")

    if high_risk_hits:
        print("⚠️ 检测到高风险权限:")
        for perm, reason in high_risk_hits:
            print(f"    - {perm}: {reason}")
    else:
        print("✅ 未申请高风险权限")

    if not disallowed_hits and not high_risk_hits:
        print("✅ 获取的权限未命中禁用或高风险清单")

    # 总是输出完整权限列表，便于审查
    if permissions:
        curr_perm_list = sorted(set(permissions))
        print(f"📃 当前申请的权限列表（共 {len(curr_perm_list)} 个）：")
        print("    " + ", ".join(curr_perm_list))
    else:
        print("📃 当前未申请任何权限")

    # 预解析 Launcher/Splash 候选
    launcher_candidates = []
    splash_candidates = []
    try:
        manifest = apk.get_android_manifest_xml()
        for app in manifest.findall("application"):
            for activity in app.findall("activity"):
                name = activity.get("{http://schemas.android.com/apk/res/android}name") or ""
                # MAIN/LAUNCHER
                for intent_filter in activity.findall("intent-filter"):
                    actions = [a.get("{http://schemas.android.com/apk/res/android}name") for a in intent_filter.findall("action")]
                    categories = [c.get("{http://schemas.android.com/apk/res/android}name") for c in intent_filter.findall("category")]
                    if "android.intent.action.MAIN" in actions and "android.intent.category.LAUNCHER" in categories:
                        launcher_candidates.append(f"{package_name}/{name}")
                if any(k.lower() in name.lower() for k in LAUNCH_ACTIVITY_KEYWORDS):
                    splash_candidates.append(f"{package_name}/{name}")
    except (AttributeError, TypeError, ValueError) as parse_manifest_err:
        print(f"⚠️ 解析 Manifest 启动信息失败：{parse_manifest_err}")
        launcher_candidates = []
        splash_candidates = []

    # ==========================
    # YAML 历史记录（apkinfo.yaml）
    # ==========================

    yaml_path = "apkinfo.yaml"

    if os.path.exists(yaml_path):
        try:
            with open(yaml_path, "r", encoding="utf-8") as f:
                yaml_data = yaml.safe_load(f) or {}
        except yaml.YAMLError as yaml_error:
            print(f"⚠️ 解析 apkinfo.yaml 失败: {yaml_error}")
            yaml_data = {}
    else:
        yaml_data = {}

    if package_name:
        old_info = yaml_data.get(package_name)

        if old_info:
            print(f"📜 上一次版本号: {old_info.get('version')}")
            print(f"📜 上一次 versionCode: {old_info.get('versionCode')}")
        else:
            print("📜 未找到历史版本记录（首次安装）")

        new_info = {
            "version": str(version_name or ""),
            "versionCode": int(version_code) if version_code is not None else 0,
        }

        if old_info and str(old_info.get("version")) == new_info["version"] and int(old_info.get("versionCode", -1)) == new_info["versionCode"]:
            print("ℹ️ 版本号未变化，跳过写入 apkinfo.yaml")
        else:
            yaml_data[package_name] = new_info
            with open(yaml_path, "w", encoding="utf-8") as f:
                yaml.dump(yaml_data, f, allow_unicode=True, sort_keys=False)
            print("💾 已更新 apkinfo.yaml 文件")

    return {
        "package_name": package_name,
        "app_name": app_name,
        "version_name": version_name,
        "version_code": version_code,
        "target_sdk_version": target_sdk_version,
        "launcher_candidates": launcher_candidates,
        "splash_candidates": splash_candidates,
    }



# ===========================
# 卸载 / 安装 APK
# ===========================

def uninstall_apk(package_name: str) -> None:
    """卸载指定包名应用（先清数据再卸载）"""
    if not package_name:
        print("❌ 卸载失败：包名为空")
        return

    print(f"正在执行卸载命令: adb shell pm clear {package_name}")
    subprocess.run(
        ["adb", "shell", "pm", "clear", package_name],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    time.sleep(0.5)

    print(f"正在执行卸载命令: adb uninstall {package_name}")
    result = subprocess.run(
        ["adb", "uninstall", package_name],
        stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )

    if b"Success" in result.stdout:
        print("✅ 卸载成功")
    else:
        print(f"⚠️ 卸载失败或未安装：{result.stdout.decode().strip()}")


def install_apk_to_device(apk_path: str, device_id: str) -> None:
    """将 APK 安装到指定设备"""
    if not os.path.isfile(apk_path):
        raise FileNotFoundError(f"❌ APK 文件不存在: {apk_path}")

    print(f"📲 正在安装到设备：{device_id}")
    cmd = ["adb", "-s", device_id, "install", "-r", apk_path]
    print(f"👉 执行命令: {' '.join(cmd)}")
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

    if result.returncode == 0 and ("Success" in result.stdout or not result.stderr.strip()):
        print(f"✅ 设备 {device_id} 安装成功")
    else:
        print(f"❌ 设备 {device_id} 安装失败")
        print("stdout:", result.stdout.strip())
        print("stderr:", result.stderr.strip())


def find_latest_apk(directory: str) -> str:
    """在目录中查找最近修改的 APK 文件"""
    directory = os.path.normpath(directory)
    if not os.path.isdir(directory):
        raise FileNotFoundError(f"❌ 指定目录不存在: {directory}")

    apk_files = glob.glob(os.path.join(directory, "*.apk"))
    if not apk_files:
        raise FileNotFoundError(f"❌ 未找到任何 APK 文件于目录: {directory}")

    latest_file = max(apk_files, key=os.path.getmtime)
    latest_time = datetime.fromtimestamp(os.path.getmtime(latest_file))
    print(f"📦 找到最新 APK：{latest_file}（更新时间: {latest_time}）")
    return latest_file


# ===========================
# 启动 Activity 策略（Launcher → 扩展 Splash → Monkey）
# ===========================

LAUNCH_ACTIVITY_KEYWORDS = [
    "Splash", "SplashActivity", "SplashScreen", "SplashScreenActivity",
    "Launch", "LauncherActivity", "LaunchActivity", "AppLaunch", "AppStart",
    "StartActivity", "StartUpActivity", "StartScreen",
    "WelcomeActivity", "WelcomeScreen", "IntroActivity", "Onboarding",
    "GuideActivity", "Boot", "LoadingActivity",
    "MainActivity", "MainPage", "HomeActivity", "IndexActivity", "EntryPoint",
    "StartupActivity", "EntryActivity",
]


def build_activity_regex(package_name: str) -> re.Pattern:
    """
    根据扩展词表生成更智能的 Activity 匹配 regex
    示例：
        com.xxx.xxx/xxx.splash.SplashActivity
        com.xxx.xxx/.WelcomeActivity
        com.xxx.xxx/xxx.MainActivity
    """
    keywords = "|".join([re.escape(k) for k in LAUNCH_ACTIVITY_KEYWORDS])
    pattern = rf"{re.escape(package_name)}/([\w\.]*({keywords})[\w\.]*)"
    return re.compile(pattern, re.IGNORECASE)


def get_launcher_activity(package_name: str) -> Optional[str]:
    """获取应用主启动 Activity"""
    try:
        result = subprocess.run(
            ["adb", "shell", "cmd", "package", "resolve-activity", "--brief", package_name],
            stdout=subprocess.PIPE, text=True, check=True
        )
        lines = [ln.strip() for ln in result.stdout.strip().splitlines() if ln.strip()]
        for ln in lines:
            if "/" in ln:
                return ln
        return None
    except subprocess.CalledProcessError:
        return None


def start_app(package_name: str, candidates: Optional[List[str]] = None) -> None:
    """
    智能启动应用：预解析候选 → Launcher → 扩展 Splash/Main → Monkey
    candidates: 预解析到的 Activity 路径列表，优先尝试
    """
    print("🚀 尝试启动应用...")

    # 预解析候选启动
    if candidates:
        for cand in candidates:
            adb_cmd = ["adb", "shell", "am", "start", "-n", cand]
            print(f"🔍 使用预解析候选启动: {cand}")
            print(f"👉 启动命令: {' '.join(adb_cmd)}")
            subprocess.run(adb_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return

    # ========== 第 1 种方式：launcher activity ==========
    launcher = get_launcher_activity(package_name)
    if launcher:
        print(f"🔍 检测到 Launcher Activity: {launcher}")
        adb_command = ["adb", "shell", "am", "start", "-n", launcher]
        print(f"👉 启动命令: {' '.join(adb_command)}")
        result = subprocess.run(adb_command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print("采用第1种 LauncherActivity 启动方式")
        if result.returncode == 0:
            return
        print("⚠️ LauncherActivity 启动失败，切换下一方案...")

    # ========== 第 2 种方式：扩展 Splash Activity 词表查找 ==========
    print("🔍 使用扩展 Splash / Main Activity 匹配策略...")

    dumpsys_output = subprocess.run(
        ["adb", "shell", "dumpsys", "package", package_name],
        capture_output=True, text=True
    ).stdout

    # 动态构建扩展 Activity 匹配 regex
    activity_regex = build_activity_regex(package_name)
    splash_match = activity_regex.search(dumpsys_output)

    if splash_match:
        splash_activity = splash_match.group(1)
        activity_path = f"{package_name}/{splash_activity}"
        adb_cmd = ["adb", "shell", "am", "start", "-n", activity_path]
        print(f"✨ 命中扩展 Activity：{splash_activity}")
        print(f"👉 启动命令: {' '.join(adb_cmd)}")
        subprocess.run(adb_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        print("采用第2种扩展 Splash/MainActivity 启动方式")
        return

    print("⚠️ 扩展 Activity 未匹配，继续使用 monkey ...")

    # ========== 第 3 种方式：monkey 启动 ==========
    monkey_cmd = ["adb", "shell", "monkey", "-p", package_name, "-c", "android.intent.category.LAUNCHER", "1"]
    print(f"✨ 启动命令: {' '.join(monkey_cmd)}")
    subprocess.run(monkey_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print("采用第3种 monkey 启动方式")


# ===========================
# 额外工具函数（可选）
# ===========================

def turn_up_the_volume(times: int = 15, delay: float = 0.1) -> None:
    """
    调高手机音量,兼容测试音频广告的场景：
    忘记测试机开启音量，导致一直不弹音频广告
    """
    for _ in range(times):
        subprocess.run(["adb", "shell", "input", "keyevent", "KEYCODE_VOLUME_UP"])
        time.sleep(delay)
    print(f"📢 手机音量已调高 {times} 次，具备音频广告播放条件")


def open_notice_permission(package_name: str) -> None:
    """打开通知权限（可按需调用）"""
    print("正在授予通知权限...")
    if not package_name:
        print("未获取到包名，无法授予通知权限")
        return
    permission_command = ["adb", "shell", "pm", "grant", package_name, "android.permission.POST_NOTIFICATIONS"]
    permission_result = subprocess.run(permission_command, stdout=subprocess.PIPE,
                                       stderr=subprocess.PIPE, text=True)
    if permission_result.returncode == 0:
        print(f"✅ 成功授予通知权限: {package_name}")
    else:
        err_text = permission_result.stderr
        print(f"❌ 授予通知权限失败，请检查包名是否正确。错误信息：{err_text}")


def force_stop_app(package_name: str) -> None:
    """停止 APP，适合某些需要停止后再重启才生效的场景"""
    if not package_name:
        print("未获取到包名，无法停止应用")
        return
    time.sleep(3)
    force_command = ["adb", "shell", "am", "force-stop", package_name]
    subprocess.run(force_command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    print(f"⏹ 已强制停止应用: {package_name}")


# ===========================
# 主流程：安装 APK
# ===========================

def install_apk(
    apk_path: Optional[str] = None,
    directory: str = "/Users/admin/Downloads",
) -> None:
    """主流程：安装 APK 到所有已连接设备"""
    print("🚀 启动 APK 安装流程")

    apk_path = apk_path or find_latest_apk(directory)
    print(f"📦 本次使用的 APK 文件: {apk_path}")
    if not os.path.isfile(apk_path):
        raise FileNotFoundError(f"❌ 找不到 APK 文件: {apk_path}")

    check_dependencies()
    devices = get_connected_devices()

    # 异步解析 APK 信息，不阻塞安装流程
    with ThreadPoolExecutor(max_workers=1) as executor:
        info_future: Future = executor.submit(extract_apk_info_from_apk, apk_path)

        # 快速解析包名（用于卸载/启动）
        package_name = None
        try:
            package_name = APK(apk_path).get_package()
        except (RuntimeError, ValueError, OSError) as parse_err:
            print(f"⚠️ 快速解析包名失败：{parse_err}")

        if package_name:
            print(f"准备安装：包名={package_name}")
        else:
            print("⚠️ 未能解析到包名，后续卸载/启动可能受影响")

    # 尝试卸载旧版本
    if package_name:
        uninstall_apk(package_name)

    # 安装到所有设备
    for device in devices:
        install_apk_to_device(apk_path, device)

    # 启动应用
    if package_name:
        candidates = []
        try:
            parsed_info = info_future.result()
            if parsed_info:
                candidates.extend(parsed_info.get("launcher_candidates", []))
                candidates.extend(parsed_info.get("splash_candidates", []))
        except (RuntimeError, ValueError, OSError) as info_err:
            print(f"⚠️ APK 信息解析线程失败：{info_err}")
        start_app(package_name, candidates=candidates if candidates else None)
    else:
        # 确保线程收尾
        try:
            info_future.result()
        except (RuntimeError, ValueError, OSError):
            pass


# ===========================
# CLI 入口
# ===========================

if __name__ == "__main__":
    # 先进行时间校验（与 AAB 脚本保持一致）
    # check_time_diff()

    import argparse

    parser = argparse.ArgumentParser(description="📦 使用 ADB 安装 APK 到 Android 设备")
    # 指定路径,不需要时需要注释
    parser.add_argument(
        "--apk",
        help="APK 文件路径（可选）",
        default="/Users/admin/Downloads/vasdolly_output/googleplay-EarthMapProLiveView-1.0.0-release.apk",
        # default="",
    )
    parser.add_argument(
        "--directory",
        help="搜索 APK 的目录（默认: /Users/admin/Downloads）",
        default="/Users/admin/Downloads"
    )

    args = parser.parse_args()
    try:
        install_apk(
            apk_path=args.apk,
            directory=args.directory,
        )
        print("🎉 APK 安装流程完成！")
    except KeyboardInterrupt:
        print("⚠️ 操作已中断（KeyboardInterrupt）")
    except (FileNotFoundError, RuntimeError, EnvironmentError, ValueError) as err:
        print(f"💥 运行时错误: {err}")
    except subprocess.CalledProcessError as sub_exc:
        stderr = sub_exc.stderr.decode().strip() if isinstance(sub_exc.stderr, (bytes, bytearray)) else (sub_exc.stderr or "")
        print(f"💥 子进程执行失败 (返回码 {sub_exc.returncode})，错误输出：{stderr}")
