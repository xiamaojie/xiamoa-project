from __future__ import annotations

import re
import subprocess
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .utils import adb_cmd, adb_shell, get_logger, run_command


@dataclass
class InstallResult:
    package_name: str
    package_path: str
    package_type: str
    installed: bool
    method: str
    output: str = ""


def find_latest_download_package(downloads: Path) -> Path:
    candidates = [path for pattern in ("*.apk", "*.aab") for path in downloads.glob(pattern) if path.is_file()]
    if not candidates:
        raise FileNotFoundError(f"未在 {downloads} 找到 .apk/.aab")
    return max(candidates, key=lambda path: path.stat().st_mtime)


def parse_package_name(package_path: Path, bundletool: Optional[Path] = None) -> str:
    suffix = package_path.suffix.lower()
    if suffix == ".apk":
        return parse_apk_package_name(package_path)
    if suffix == ".aab":
        return parse_aab_package_name(package_path, bundletool)
    raise ValueError(f"不支持的安装包类型: {package_path}")


def parse_apk_package_name(apk_path: Path) -> str:
    try:
        from androguard.core.apk import APK

        apk = APK(str(apk_path))
        package_name = apk.get_package()
        if package_name:
            return package_name
    except Exception as exc:
        get_logger().debug("androguard 解析 APK 失败: %s", exc)

    for cmd in (["aapt", "dump", "badging", str(apk_path)], ["aapt2", "dump", "badging", str(apk_path)]):
        result = run_command(cmd, timeout=30, check=False)
        match = re.search(r"package: name='([^']+)'", result.stdout)
        if match:
            return match.group(1)
    raise RuntimeError(f"无法解析 APK 包名: {apk_path}")


def parse_aab_package_name(aab_path: Path, bundletool: Optional[Path] = None) -> str:
    if bundletool and bundletool.exists():
        result = run_command(
            ["java", "-jar", str(bundletool), "dump", "manifest", "--bundle", str(aab_path), "--xpath", "/manifest/@package"],
            timeout=60,
            check=False,
        )
        package_name = result.stdout.strip().strip('"')
        if result.returncode == 0 and package_name:
            return package_name

    # Fallback catches plain-text package names in some bundletool-generated manifests.
    with zipfile.ZipFile(aab_path) as zip_file:
        for name in ("base/manifest/AndroidManifest.xml", "base/manifest/AndroidManifest.xml.pb"):
            if name in zip_file.namelist():
                raw = zip_file.read(name)
                text = raw.decode("utf-8", errors="ignore")
                match = re.search(r"package=\"([A-Za-z0-9_.]+)\"", text)
                if match:
                    return match.group(1)
    raise RuntimeError(f"无法解析 AAB 包名；请确认 bundletool 可用: {aab_path}")


def package_installed(serial: str, package_name: str) -> bool:
    result = run_command(adb_cmd(serial, "shell", "pm", "list", "packages", package_name), timeout=20, check=False)
    return f"package:{package_name}" in result.stdout


def uninstall_if_present(serial: str, package_name: str) -> None:
    if package_installed(serial, package_name):
        get_logger().info("卸载旧包: %s", package_name)
        run_command(adb_cmd(serial, "uninstall", package_name), timeout=90, check=False)


def adb_install_apk(serial: str, apk_path: Path, timeout: int) -> subprocess.CompletedProcess[str]:
    return run_command(adb_cmd(serial, "install", "--no-streaming", "-r", "-d", "-g", str(apk_path)), timeout=timeout, check=False)


def install_package(
    serial: str,
    package_path: Path,
    package_name: str,
    bundletool: Path,
    timeout: int,
    skip_install: bool = False,
) -> InstallResult:
    if skip_install:
        if not package_installed(serial, package_name):
            raise RuntimeError(f"--skip-install 已启用，但设备上未安装 {package_name}")
        return InstallResult(package_name, str(package_path), package_path.suffix.lower().lstrip("."), True, "skip")

    uninstall_if_present(serial, package_name)
    suffix = package_path.suffix.lower()
    if suffix == ".apk":
        result = adb_install_apk(serial, package_path, timeout)
        output = (result.stdout + "\n" + result.stderr).strip()
        if result.returncode != 0 or "Success" not in output:
            raise RuntimeError(f"APK 安装失败: {output}")
        installed = package_installed(serial, package_name)
        return InstallResult(package_name, str(package_path), "apk", installed, "adb install", output)

    if suffix == ".aab":
        if not bundletool.exists():
            raise FileNotFoundError(f"AAB 安装需要 bundletool.jar，不存在: {bundletool}")
        with tempfile.TemporaryDirectory(prefix="stability_apks_") as temp_dir:
            apks_path = Path(temp_dir) / "app.apks"
            universal_apk = Path(temp_dir) / "universal.apk"
            build = run_command(
                [
                    "java",
                    "-jar",
                    str(bundletool),
                    "build-apks",
                    "--bundle",
                    str(package_path),
                    "--output",
                    str(apks_path),
                    "--mode=universal",
                    "--overwrite",
                ],
                timeout=timeout,
                check=False,
            )
            if build.returncode != 0:
                raise RuntimeError(f"bundletool build-apks 失败: {(build.stderr or build.stdout).strip()}")
            with zipfile.ZipFile(apks_path) as apks_zip:
                apk_names = [name for name in apks_zip.namelist() if name.endswith(".apk")]
                selected = "universal.apk" if "universal.apk" in apk_names else (apk_names[0] if apk_names else "")
                if not selected:
                    raise RuntimeError(f"bundletool 产物中未找到 APK: {apks_path}")
                universal_apk.write_bytes(apks_zip.read(selected))
            install = adb_install_apk(serial, universal_apk, timeout)
            output = (install.stdout + "\n" + install.stderr).strip()
            if install.returncode != 0:
                raise RuntimeError(f"AAB universal APK 安装失败: {output}")
        installed = package_installed(serial, package_name)
        return InstallResult(package_name, str(package_path), "aab", installed, "bundletool universal + adb install", output)

    raise ValueError(f"不支持的安装包类型: {package_path}")


def launch_app(serial: str, package_name: str) -> None:
    # Monkey launch is intentionally used as the most compatible fallback.
    run_command(
        adb_cmd(serial, "shell", "monkey", "-p", package_name, "-c", "android.intent.category.LAUNCHER", "1"),
        timeout=30,
        check=False,
    )
    try:
        adb_shell(serial, f"am force-stop {package_name}", timeout=15)
    except RuntimeError:
        pass
