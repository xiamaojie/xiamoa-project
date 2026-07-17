from __future__ import annotations

from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional

from .utils import adb_cmd, adb_shell, run_command


@dataclass
class DeviceInfo:
    serial: str
    model: str = ""
    brand: str = ""
    manufacturer: str = ""
    android_version: str = ""
    sdk: str = ""
    abi: str = ""
    build_fingerprint: str = ""
    battery: str = ""
    current_time: str = ""

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


def ensure_adb() -> None:
    run_command(["adb", "version"], timeout=10, check=True)


def list_online_devices() -> list[str]:
    ensure_adb()
    result = run_command(["adb", "devices"], timeout=10, check=True)
    devices: list[str] = []
    for line in result.stdout.splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 2 and parts[1] == "device":
            devices.append(parts[0])
    return devices


def select_device(serial: Optional[str] = None) -> str:
    devices = list_online_devices()
    if serial:
        if serial not in devices:
            raise RuntimeError(f"设备未在线或未授权: {serial}; 当前在线设备: {devices}")
        return serial
    if not devices:
        raise RuntimeError("未发现在线 adb 设备，请连接设备并确认授权")
    if len(devices) > 1:
        raise RuntimeError(f"发现多个在线设备，请通过 --serial 指定: {', '.join(devices)}")
    return devices[0]


def collect_device_info(serial: str) -> DeviceInfo:
    def prop(name: str) -> str:
        try:
            return adb_shell(serial, ["getprop", name], timeout=10)
        except RuntimeError:
            return ""

    def shell(command: str) -> str:
        try:
            return adb_shell(serial, command, timeout=10)
        except RuntimeError:
            return ""

    return DeviceInfo(
        serial=serial,
        model=prop("ro.product.model"),
        brand=prop("ro.product.brand"),
        manufacturer=prop("ro.product.manufacturer"),
        android_version=prop("ro.build.version.release"),
        sdk=prop("ro.build.version.sdk"),
        abi=prop("ro.product.cpu.abi"),
        build_fingerprint=prop("ro.build.fingerprint"),
        battery=shell("dumpsys battery | head -40"),
        current_time=shell("date '+%Y-%m-%d %H:%M:%S %Z'"),
    )


def prepare_device(serial: str, output_dir: Path) -> None:
    run_command(adb_cmd(serial, "logcat", "-c"), timeout=20, check=False)
    (output_dir / "device").mkdir(parents=True, exist_ok=True)
    info = collect_device_info(serial)
    (output_dir / "device" / "device_info.txt").write_text(
        "\n".join(f"{key}: {value}" for key, value in info.to_dict().items()),
        encoding="utf-8",
    )
    for name, command in {
        "packages.txt": "pm list packages",
        "disk.txt": "df -h",
        "activity_top.txt": "dumpsys activity top",
    }.items():
        try:
            (output_dir / "device" / name).write_text(adb_shell(serial, command, timeout=20), encoding="utf-8")
        except RuntimeError as exc:
            (output_dir / "device" / name).write_text(str(exc), encoding="utf-8")
