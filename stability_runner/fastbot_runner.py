from __future__ import annotations

import shutil
import subprocess
import time
from pathlib import Path
from typing import Optional

from .monkey_runner import RunResult
from .utils import adb_cmd, adb_shell, get_logger, run_command


FASTBOT_JARS = ["/sdcard/monkeyq.jar", "/sdcard/framework.jar", "/sdcard/fastbot-thirdpart.jar"]


def fastbot_available(serial: str) -> tuple[bool, str]:
    try:
        missing = []
        for jar in FASTBOT_JARS:
            out = run_command(adb_cmd(serial, "shell", "ls", jar), timeout=10, check=False)
            if out.returncode != 0:
                missing.append(jar)
        if missing:
            return False, f"设备缺少 Fastbot jar: {', '.join(missing)}"
        return True, "Fastbot jar 已存在"
    except RuntimeError as exc:
        return False, str(exc)


def run_fastbot(
    serial: str,
    package_name: str,
    minutes: int,
    throttle: int,
    seed: Optional[int],
    output_dir: Path,
    timeout_extra: int = 60,
) -> Optional[RunResult]:
    ok, reason = fastbot_available(serial)
    if not ok:
        get_logger().warning("跳过 Fastbot: %s", reason)
        (output_dir / "fastbot_skipped.txt").write_text(reason, encoding="utf-8")
        return None

    device_output = f"/sdcard/fastbot_results/{package_name.replace('.', '_')}"
    try:
        adb_shell(serial, f"rm -rf {device_output} && mkdir -p {device_output}", timeout=20)
    except RuntimeError:
        pass

    cmd = adb_cmd(
        serial,
        "shell",
        f"CLASSPATH={':'.join(FASTBOT_JARS)}",
        "exec",
        "app_process",
        "/system/bin",
        "com.android.commands.monkey.Monkey",
        "-p",
        package_name,
        "--agent",
        "reuseq",
        "--running-minutes",
        str(minutes),
        "--throttle",
        str(throttle),
        "-v",
        "-v",
        "--output-directory",
        device_output,
    )
    if seed is not None:
        cmd.extend(["-s", str(seed)])

    output_file = output_dir / "fastbot_output.txt"
    started = time.time()
    get_logger().info("开始 Fastbot: %s 分钟", minutes)
    with output_file.open("w", encoding="utf-8", errors="replace") as file_obj:
        proc = subprocess.Popen(cmd, stdout=file_obj, stderr=subprocess.STDOUT, text=True)
        try:
            return_code = proc.wait(timeout=minutes * 60 + timeout_extra)
        except subprocess.TimeoutExpired:
            get_logger().warning("Fastbot 超时，终止进程")
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=5)
            return_code = proc.returncode if proc.returncode is not None else -9
    ended = time.time()

    pulled_dir = output_dir / "fastbot_device_logs"
    pulled_dir.mkdir(parents=True, exist_ok=True)
    run_command(adb_cmd(serial, "pull", f"{device_output}/.", str(pulled_dir)), timeout=120, check=False)
    return RunResult("fastbot", cmd, return_code, started, ended, str(output_file))
