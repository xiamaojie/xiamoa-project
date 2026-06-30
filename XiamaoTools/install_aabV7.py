"""
install_aabV7.py

功能概述：
- 自动查找/指定 AAB，使用 bundletool 生成 APKS 并安装到所有连接设备
- 并发 NTP 校时（取最快节点），比对手机时间
- 生成 APKS 后异步解析 APK 信息（包名/版本/targetSdk/权限、高危/禁用命中），安装/启动不被解析阻塞
- 快速解析包名用于卸载旧版；安装完成后自动启动应用
- 预解析 Manifest 中的 Launcher/Splash 候选，启动时优先尝试，失败回退 resolve/dumpsys/monkey 兜底
- 安装前校验网络/VPN 状态：遍历所有连接设备，dumpsys connectivity 一次判断
- 记录历史版本信息到 appinfo.yaml（版本未变跳过写入），权限列表压缩展示
- CLI 参数：--aab/--directory/--keystore/--ks-key-alias/--ks-pass/--key-pass

使用提示：
- 直接运行：python install_aabV7.py（默认在 Downloads 下找最新 AAB）
- 指定 AAB：python install_aabV7.py --aab /path/to/app.aab
- 需要签名时传入 keystore 参数。
"""
import os
import re
import subprocess
import tempfile
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor, Future, as_completed
from datetime import datetime
from typing import Optional, Dict, List

import ntplib
import socket
import yaml  # 新增：用于读取和保存 appinfo.yaml
from androguard.core.apk import APK
from loguru import logger

logger.remove()
logger.add(lambda msg: None, level="ERROR")

# 配置 bundletool 的 JAR 文件路径
BUNDLETOOL_JAR = "/Users/admin/bundletool.jar"

# 权限检查清单、
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
    # "WRITE_EXTERNAL_STORAGE": "Android 10 以下的传统外部存储读写权限",
    # "READ_EXTERNAL_STORAGE": "Android 10 以下的传统外部存储读写权限",
    "READ_MEDIA_IMAGES": "Android 13+ 引入的细粒度媒体（图片）访问权限，需按需申请并说明用途；可用系统选择器代替",
    "READ_MEDIA_VIDEO": "Android 13+ 引入的细粒度媒体（视频）访问权限，需按需申请并说明用途；可用系统选择器代替",
    "USE_FULL_SCREEN_INTENT": "全屏通知",
    # ------ 新增高危权限（Google Play 严格审核） ------
    "BLUETOOTH_CONNECT": "蓝牙连接权限；非核心蓝牙功能将被拒审",
    "BLUETOOTH_SCAN": "蓝牙扫描权限；被视为定位权限，需声明用途并合理化",
    "ACTIVITY_RECOGNITION": "身体活动识别；仅运动健身等核心功能场景可申请",
    "NEARBY_WIFI_DEVICES": "Android 13+ 附近 Wi-Fi 设备扫描；可能推断位置，被视为高危权限",
    "RECORD_AUDIO": "录音权限；必须由用户主动触发且为核心功能所需，否则会被拒审",
    "CAMERA": "摄像头访问；必须符合最小权限原则并对应可见核心功能",
    "USE_EXACT_ALARM": "Android 13+ 精确闹钟；仅闹钟、日程提醒类应用有资格",
    "SCHEDULE_EXACT_ALARM": "安排精确闹钟；与 USE_EXACT_ALARM 审核逻辑相同"
}


def check_time_diff(max_diff_seconds=60, ntp_timeout=5):
    """
    并发获取 NTP 时间，与手机时间比对。
    max_diff_seconds: 允许的最大差值（秒）。
    ntp_timeout: 单个 NTP 请求超时（秒）。
    """

    # ---------- 1. 读取手机时间 ----------
    try:
        output = subprocess.check_output(
            ['adb', 'shell', "date +%s"],
            text=True,
            timeout=5
        ).strip()
        device_epoch = float(output)
        device_dt = datetime.fromtimestamp(device_epoch)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, ValueError) as adb_err:
        raise RuntimeError(f"无法从 ADB 获取设备时间: {adb_err}")

    # ---------- 2. 获取 NTP 服务器时间 ----------
    NTP_SERVERS = [
        # 公共池
        "pool.ntp.org",
        "ntp.aliyun.com",
        "0.pool.ntp.org",
        "1.pool.ntp.org",
        "2.pool.ntp.org",
        "3.pool.ntp.org",
        "cn.pool.ntp.org",
        # 国内稳定源
        "ntp1.aliyun.com",
        "time1.cloud.tencent.com",
        "time2.cloud.tencent.com",
        "ntp.ntsc.ac.cn",
        # 大厂节点
        "time.google.com",
        "time.cloudflare.com",
        "time.windows.com",
        "time.apple.com",
    ]

    server_dt = None
    last_error = None

    # 并发请求多个 NTP，取最快成功的
    with ThreadPoolExecutor(max_workers=min(5, len(NTP_SERVERS))) as executor:
        future_map = {
            executor.submit(lambda h: ntplib.NTPClient().request(h, version=3, timeout=ntp_timeout), host): host
            for host in NTP_SERVERS
        }
        for fut in as_completed(future_map):
            host = future_map[fut]
            try:
                response = fut.result()
                server_dt = datetime.fromtimestamp(response.tx_time)
                print(f"成功从 NTP 服务器获取时间: {host}")
                break
            except (ntplib.NTPException, OSError, socket.timeout) as ntp_err:
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


def check_dependencies() -> None:
    """检查 adb、java、bundletool 是否可用"""
    for cmd, name in [(["adb", "version"], "ADB"), (["java", "-version"], "Java")]:
        try:
            subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            print(f"✅ {name} 已安装")
        except (subprocess.CalledProcessError, FileNotFoundError):
            raise EnvironmentError(f"❌ 未找到 {name}，请确保已安装并配置到 PATH")

    if not os.path.isfile(BUNDLETOOL_JAR):
        raise FileNotFoundError(f"❌ bundletool jar 文件不存在: {BUNDLETOOL_JAR}")

    try:
        result = subprocess.run(
            ["java", "-jar", BUNDLETOOL_JAR, "version"],
            check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
        )
        print(f"✅ bundletool 可用，版本: {result.stdout.strip()}")
    except subprocess.CalledProcessError as bundle_exc:
        raise RuntimeError(f"❌ bundletool 运行失败: {bundle_exc.stderr.strip()}")


def get_connected_devices() -> List[str]:
    """获取已连接的 Android 设备列表"""
    try:
        result = subprocess.run(["adb", "devices"], capture_output=True, text=True, check=True, timeout=10)
    except subprocess.TimeoutExpired as exe:
        raise RuntimeError("ADB 命令超时，请检查设备连接或 adb server 状态") from exe
    except subprocess.CalledProcessError as exe:
        raise RuntimeError("ADB 命令执行失败，请检查 ADB 是否安装并正常运行") from exe

    devices = [
        line.split()[0]
        for line in result.stdout.splitlines()
        if line.strip() and not line.startswith("List of devices") and line.strip().endswith("device")
    ]
    if not devices:
        raise RuntimeError("未检测到连接的 Android 设备，请检查设备是否连接")
    return devices


def check_network_and_vpn_status(devices: Optional[List[str]] = None, verbose: bool = True) -> Dict[str, str]:
    """
    系统级网络 & VPN 状态检测（每台设备只执行一次 dumpsys connectivity，先看 Active default network 再判定 VPN/VALIDATED）
    状态枚举：
        - NO_NETWORK
        - NETWORK_OK_NO_VPN
        - VPN_ON_NOT_VALIDATED
        - VPN_ON_AND_VALIDATED
    返回 dict: {device_id: status}
    """
    try:
        target_devices = devices if devices is not None else get_connected_devices()
    except Exception as vpn_err:
        if verbose:
            print(f"⚠️ 获取设备列表失败，跳过网络/VPN 检测：{vpn_err}")
        return {}

    if isinstance(target_devices, str):
        target_devices = [target_devices]

    results: Dict[str, str] = {}

    for device_id in target_devices:
        adb_prefix = ["adb", "-s", device_id]
        try:
            output = subprocess.check_output(
                adb_prefix + ["shell", "dumpsys", "connectivity"],
                text=True,
                stderr=subprocess.DEVNULL
            )
        except subprocess.CalledProcessError:
            status = "NO_NETWORK"
            results[device_id] = status
            if verbose:
                print(f"设备 {device_id} 当前网络状态: {status}")
                print("❌ 当前设备无可用网络（飞行模式或无连接）")
            continue

        active_match = re.search(r"Active default network:\s*(\S+)", output)
        prefix = f"[{device_id}] " if len(target_devices) > 1 else ""

        if not active_match or active_match.group(1) == "none":
            status = "NO_NETWORK"
            results[device_id] = status
            if verbose:
                print(f"{prefix}当前网络状态: {status}")
                print(f"{prefix}❌ 当前设备无可用网络（飞行模式或无连接）")
            continue

        has_vpn_connected = "VPN CONNECTED" in output
        has_is_vpn = "IS_VPN" in output
        has_validated = "IS_VALIDATED" in output

        if has_vpn_connected and has_is_vpn:
            if "IS_VPN&EVER_VALIDATED&IS_VALIDATED" in output or ("IS_VPN" in output and "IS_VALIDATED" in output):
                status = "VPN_ON_AND_VALIDATED"
                results[device_id] = status
                if verbose:
                    print(f"{prefix}当前网络状态: {status}")
                    print(f"{prefix}🌍 VPN 正常，已验证可访问海外网络")
                continue
            status = "VPN_ON_NOT_VALIDATED"
            results[device_id] = status
            if verbose:
                print(f"{prefix}当前网络状态: {status}")
                print(f"{prefix}⚠️ VPN 已开启，但节点可能异常，尚未验证外网连通性")
            continue

        if has_validated:
            status = "NETWORK_OK_NO_VPN"
            results[device_id] = status
            if verbose:
                print(f"{prefix}当前网络状态: {status}")
                print(f"{prefix}⚠️ 当前为直连网络，未开启 VPN")
            continue

        status = "NO_NETWORK"
        results[device_id] = status
        if verbose:
            print(f"{prefix}当前网络状态: {status}")
            print(f"{prefix}❌ 当前设备无可用网络（未通过系统 VALIDATED 校验）")

    return results


def run_command(cmd: List[str], desc: str = "", timeout: int = 120) -> None:
    """运行命令并输出结果，失败时抛出异常"""
    print(f"🔧 正在执行：{desc or ' '.join(cmd)}")
    try:
        result = subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=timeout)
        print(f"✅ 成功：{desc or ' '.join(cmd)}")
        if result.stdout:
            print(result.stdout.strip())
    except subprocess.TimeoutExpired:
        raise RuntimeError(f"❌ 执行超时（>{timeout}s）：{' '.join(cmd)}，请检查网络/USB 连接或命令是否卡住")
    except subprocess.CalledProcessError as exe:
        err_msg = exe.stderr or exe.stdout or ""
        raise RuntimeError(f"❌ 执行失败：{' '.join(cmd)}\n错误信息：{err_msg.strip()}")


def generate_apks(
        aab_path: str,
        output_apks_path: str,
        bundletool_jar: str,
        keystore_path: Optional[str] = None,
        ks_key_alias: Optional[str] = None,
        ks_pass: Optional[str] = None,
        key_pass: Optional[str] = None
) -> None:
    """使用 bundletool 生成 APKS 文件（可选签名）"""
    print("📦 正在生成 APKS 文件...")
    cmd = [
        "java", "-jar", bundletool_jar,
        "build-apks",
        f"--bundle={aab_path}",
        f"--output={output_apks_path}",
        "--overwrite",
        "--mode=universal"
    ]
    if all([keystore_path, ks_key_alias, ks_pass, key_pass]):
        cmd += [
            f"--ks={keystore_path}",
            f"--ks-key-alias={ks_key_alias}",
            f"--ks-pass=pass:{ks_pass}",
            f"--key-pass=pass:{key_pass}"
        ]
    run_command(cmd, "生成 APKS")


def install_apks(apks_path: str, device_id: str, bundletool_jar: str) -> None:
    """将 APKS 安装到指定设备"""
    print(f"📲 正在安装到设备：{device_id}")
    cmd = [
        "java", "-jar", bundletool_jar,
        "install-apks",
        f"--apks={apks_path}",
        f"--device-id={device_id}"
    ]
    run_command(cmd, f"安装到设备 {device_id}")


def extract_apk_info_from_apks(apks_path: str) -> Dict[str, str]:
    """
    解析 APKS 中第一个 APK：
    - 包名、应用名、版本号、versionCode、targetSdk
    - 权限清单（含禁用/高危命中提示，压缩列表展示）
    - 写入 appinfo.yaml（版本未变跳过）
    - 返回预解析启动候选（Manifest 中 MAIN/LAUNCHER 与 Splash 关键词）
    """
    if not zipfile.is_zipfile(apks_path):
        raise ValueError(f"❌ 文件不是有效的 ZIP/APKS: {apks_path}")
    with zipfile.ZipFile(apks_path, 'r') as z:
        apk_files = [f for f in z.namelist() if f.endswith('.apk')]
        if not apk_files:
            raise RuntimeError("❌ APKS 中未找到任何 APK 文件")
        with tempfile.NamedTemporaryFile(suffix=".apk", delete=False) as tmp_apk:
            tmp_apk.write(z.read(apk_files[0]))
            tmp_apk_path = tmp_apk.name

    try:
        apk = APK(tmp_apk_path)
        package_name = apk.package
        app_name = apk.get_app_name()
        version_name = apk.get_androidversion_name()
        version_code = apk.get_androidversion_code()
        target_sdk_version = apk.get_target_sdk_version()
        permissions = apk.get_permissions() or []

        print(f"📛 包名: {package_name}")
        print(f"📌 应用名称: {app_name}")
        print(f"📌 版本号: {version_name}")
        print(f"📌 GooglePlay内部版本号，versionCode是: {version_code}")

        # === 🔥 新增：读取 & 打印上一次版本号并写入 YAML ===
        yaml_path = "appinfo.yaml"

        # 读取历史 YAML
        if os.path.exists(yaml_path):
            with open(yaml_path, "r", encoding="utf-8") as f:
                try:
                    yaml_data = yaml.safe_load(f) or {}
                except yaml.YAMLError as yaml_err:
                    # YAML 解析出错时，忽略并继续使用空字典
                    print(f"⚠️ 解析 appinfo.yaml 失败: {yaml_err}")
                    yaml_data = {}
        else:
            yaml_data = {}

        # 获取旧历史数据
        old_info = yaml_data.get(package_name)
        if old_info:
            print(f"📜 上一次版本号: {old_info.get('version')}")
            print(f"📜 上一次 versionCode: {old_info.get('versionCode')}")
        else:
            print("📜 未找到历史版本记录（首次安装）")

        new_info = {
            "version": str(version_name),
            "versionCode": int(version_code),
        }

        # 若版本信息未变化则跳过写入，避免不必要的 IO
        if old_info and str(old_info.get("version")) == new_info["version"] and int(old_info.get("versionCode", -1)) == \
                new_info["versionCode"]:
            print("ℹ️ 版本号未变化，跳过写入 appinfo.yaml")
        else:
            yaml_data[package_name] = new_info
            with open(yaml_path, "w", encoding="utf-8") as f:
                yaml.dump(yaml_data, f, allow_unicode=True, sort_keys=False)
            print("💾 已更新 appinfo.yaml文件")
        # === 🔥 新增结束 ===

        try:
            target_sdk_int = int(target_sdk_version)
        except (ValueError, TypeError):
            target_sdk_int = -1

        if target_sdk_int >= 35:
            print(f"📌 targetSdkVersion版本是: {target_sdk_version}")
        else:
            print(f"⚠️ targetSdkVersion小于35，当前版本是:{target_sdk_version}")

        # 权限检查
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

        # 打印当前应用申请的所有权限
        if permissions:
            curr_perm_list = sorted(set(permissions))
            print(f"📃 当前申请的权限列表（共 {len(curr_perm_list)} 个）：")
            print("    " + ", ".join(curr_perm_list))
        else:
            print("📃 当前未申请任何权限")

        # 预解析 Launcher/Splash 候选
        launcher_candidates = []
        splash_candidates = []
        manifest = apk.get_android_manifest_xml()
        try:
            for app in manifest.findall("application"):
                for activity in app.findall("activity"):
                    name = activity.get("{http://schemas.android.com/apk/res/android}name") or ""
                    for intent_filter in activity.findall("intent-filter"):
                        actions = [a.get("{http://schemas.android.com/apk/res/android}name") for a in
                                   intent_filter.findall("action")]
                        categories = [c.get("{http://schemas.android.com/apk/res/android}name") for c in
                                      intent_filter.findall("category")]
                        if "android.intent.action.MAIN" in actions and "android.intent.category.LAUNCHER" in categories:
                            launcher_candidates.append(f"{package_name}/{name}")
                    if any(k.lower() in name.lower() for k in LAUNCH_ACTIVITY_KEYWORDS):
                        splash_candidates.append(f"{package_name}/{name}")
        except (AttributeError, TypeError, ValueError) as parse_manifest_err:
            print(f"⚠️ 解析 Manifest 启动信息失败：{parse_manifest_err}")
            launcher_candidates = []
            splash_candidates = []

        return {
            "package_name": package_name,
            "app_name": app_name,
            "version_name": version_name,
            "target_sdk_version": target_sdk_version,
            "version_code": version_code,
            "launcher_candidates": launcher_candidates,
            "splash_candidates": splash_candidates
        }
    finally:
        os.remove(tmp_apk_path)


def get_package_name_from_apks(apks_path: str) -> Optional[str]:
    """轻量解析：仅提取包名，用于卸载/启动，避免完整解析阻塞"""
    if not zipfile.is_zipfile(apks_path):
        return None
    with zipfile.ZipFile(apks_path, 'r') as z:
        apk_files = [f for f in z.namelist() if f.endswith('.apk')]
        if not apk_files:
            return None
        with tempfile.NamedTemporaryFile(suffix=".apk", delete=False) as tmp_apk:
            tmp_apk.write(z.read(apk_files[0]))
            tmp_apk_path = tmp_apk.name
    try:
        apk = APK(tmp_apk_path)
        return apk.package
    except (ValueError, OSError) as parse_err:
        print(f"⚠️ 快速解析包名失败：{parse_err}")
        return None
    finally:
        os.remove(tmp_apk_path)


def uninstall_apk(package_name: str) -> None:
    """卸载指定包名的应用"""
    uninstall_command = ["adb", "uninstall", package_name]
    print(f"正在执行卸载命令: adb uninstall {package_name}")
    result = subprocess.run(uninstall_command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    time.sleep(0.5)
    if b"Success" in result.stdout:
        print("✅ 卸载成功")
    else:
        print(f"⚠️ 卸载失败或未安装：{result.stdout.decode().strip()}")


def get_launcher_activity(package_name: str) -> Optional[str]:
    """获取应用主启动 Activity"""
    try:
        result = subprocess.run(
            ["adb", "shell", "cmd", "package", "resolve-activity", "--brief", package_name],
            stdout=subprocess.PIPE, text=True, check=True
        )
        lines = [line for line in result.stdout.strip().splitlines() if "/" in line]
        return lines[0] if lines else None
    except subprocess.CalledProcessError:
        return None


# 扩展了启动方式2，增加了对 Activity 名称的智能匹配 Splash 命中规则
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


def start_app(package_name: str, candidates: Optional[List[str]] = None) -> None:
    """
    智能启动应用：预解析候选 → Launcher → 扩展 Splash → Monkey
    candidates: 预解析的 Activity 候选（如 Manifest 中的 MAIN/LAUNCHER 或 Splash）
    """
    print("🚀 尝试启动应用...")

    # ========== 预解析候选启动 ==========
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


def find_latest_aab(directory: str) -> str:
    """在目录中查找最近修改的 AAB 文件"""
    directory = os.path.normpath(directory)
    if not os.path.isdir(directory):
        raise FileNotFoundError(f"❌ 指定目录不存在: {directory}")
    aab_files = [
        os.path.join(directory, f)
        for f in os.listdir(directory)
        if f.endswith(".aab") and os.path.isfile(os.path.join(directory, f))
    ]
    if not aab_files:
        raise FileNotFoundError(f"❌ 未找到任何 AAB 文件于目录: {directory}")
    latest_file = max(aab_files, key=os.path.getmtime)
    latest_time = datetime.fromtimestamp(os.path.getmtime(latest_file))
    print(f"📦 找到最新 AAB：{latest_file}（更新时间: {latest_time}）")
    return latest_file


def install_aab(
        aab_path: Optional[str] = None,
        directory: str = "/Users/admin/Downloads",
        keystore_path: Optional[str] = None,
        ks_key_alias: Optional[str] = None,
        ks_pass: Optional[str] = None,
        key_pass: Optional[str] = None
) -> None:
    """主流程：安装 AAB 到所有已连接设备"""
    print("🚀 启动安装流程")
    aab_path = aab_path or find_latest_aab(directory)
    print(f"📦 本次使用的 AAB 文件: {aab_path}")
    if not os.path.isfile(aab_path):
        raise FileNotFoundError(f"❌ 找不到 AAB 文件: {aab_path}")

    check_dependencies()
    devices = get_connected_devices()
    print(f"📱 已连接设备: {devices}")

    with tempfile.TemporaryDirectory() as tmp_dir:
        apks_path = os.path.join(tmp_dir, "output.apks")
        generate_apks(
            aab_path,
            apks_path,
            bundletool_jar=BUNDLETOOL_JAR,
            keystore_path=keystore_path,
            ks_key_alias=ks_key_alias,
            ks_pass=ks_pass,
            key_pass=key_pass
        )

        # 异步解析 APK 详情（权限/版本），安装流程不等待
        executor = ThreadPoolExecutor(max_workers=1)
        info_future: Future = executor.submit(extract_apk_info_from_apks, apks_path)

        package_name = get_package_name_from_apks(apks_path)
        if package_name:
            try:
                uninstall_apk(package_name)
            except Exception as uninstall_err:
                print(f"⚠️ 卸载旧版本失败：{uninstall_err}")
        else:
            print("⚠️ 未能解析包名，跳过卸载步骤")

        for device in devices:
            install_apks(apks_path, device, bundletool_jar=BUNDLETOOL_JAR)

        parsed_info = None
        if package_name and info_future:
            try:
                parsed_info = info_future.result()
            except Exception as parse_err:
                print(f"⚠️ APK 信息解析线程失败：{parse_err}，使用兜底启动")

        candidates = []
        if parsed_info:
            candidates.extend(parsed_info.get("launcher_candidates", []))
            candidates.extend(parsed_info.get("splash_candidates", []))

        if package_name:
            start_app(package_name, candidates=candidates if candidates else None)

        executor.shutdown(wait=False)

        print(f"🧹 清理临时目录: {tmp_dir}")


if __name__ == "__main__":
    # check_time_diff()
    # # 先检查所有已连接设备的网络/VPN 状态（若无设备则跳过）
    # check_network_and_vpn_status()
    import argparse

    parser = argparse.ArgumentParser(description="📦 使用 bundletool 安装 AAB 到 Android 设备")
    # 不指定路径安装
    parser.add_argument("--aab", help="AAB 文件路径（可选）", default=None)
    # 指定路径安装，这是游戏路径的包
    # parser.add_argument("--aab", help="AAB 文件路径（可选）", default="/Users/admin/Downloads/ArrowsanDarrows-release.aab")
    parser.add_argument("--directory", help="搜索 AAB 的目录（默认: /Users/admin/Downloads）",
                        default="/Users/admin/Downloads")
    parser.add_argument("--keystore", help="签名 keystore 文件（可选）", default=None)
    parser.add_argument("--ks-key-alias", help="keystore 别名（可选）", default=None)
    parser.add_argument("--ks-pass", help="keystore 密码（可选）", default=None)
    parser.add_argument("--key-pass", help="key 密码（可选）", default=None)
    # 指定签名文件路径
    # parser.add_argument("--keystore", help="签名 keystore 文件（可选）",
    #                     default=r"/Users/admin/Downloads/DramaGold-1.0.7-release.aab")
    # parser.add_argument("--ks-key-alias", help="keystore 别名（可选）", default="PalmDebug")
    # parser.add_argument("--ks-pass", help="keystore 密码（可选）", default="PalmDebug")
    # parser.add_argument("--key-pass", help="key 密码（可选）", default="PalmDebug")

    args = parser.parse_args()
    try:
        install_aab(
            aab_path=args.aab,
            directory=args.directory,
            keystore_path=args.keystore,
            ks_key_alias=args.ks_key_alias,
            ks_pass=args.ks_pass,
            key_pass=args.key_pass
        )
        print("🎉 AAB 安装完成！")
    except KeyboardInterrupt:
        print("⚠️ 操作已中断（KeyboardInterrupt）")
    except (FileNotFoundError, RuntimeError, EnvironmentError, ValueError) as err:
        # 这些都是可预期的运行时错误，给出简洁提示
        print(f"💥 运行时错误: {err}")
    except subprocess.CalledProcessError as sub_exc:
        # 子进程错误（adb/java/bundletool 等），提供更多上下文
        stderr = sub_exc.stderr.decode().strip() if isinstance(sub_exc.stderr, (bytes, bytearray)) else (
                sub_exc.stderr or "")
        print(f"💥 子进程执行失败 (返回码 {sub_exc.returncode})，错误输出：{stderr}")
