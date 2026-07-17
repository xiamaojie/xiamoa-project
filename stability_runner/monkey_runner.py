from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .config_loader import EventRatios
from .utils import adb_cmd, get_logger


@dataclass
class RunResult:
    mode: str
    command: list[str]
    return_code: int
    started_at: float
    ended_at: float
    output_file: str

    @property
    def elapsed_seconds(self) -> float:
        return self.ended_at - self.started_at


def estimate_events(minutes: int, throttle_ms: int) -> int:
    return max(100, int(minutes * 60 * 1000 / max(1, throttle_ms)))


def estimate_chunk_events(throttle_ms: int) -> int:
    # Monkey does not sleep for every sub-event in compound gestures, so short
    # chunks are safer for honoring a wall-clock duration.
    return max(200, int(60 * 1000 / max(1, throttle_ms)))


def build_monkey_command(
    serial: str,
    package_name: str,
    minutes: int,
    throttle: int,
    seed: Optional[int],
    events: Optional[int],
    ratios: EventRatios,
) -> list[str]:
    event_count = events or estimate_events(minutes, throttle)
    cmd = adb_cmd(
        serial,
        "shell",
        "monkey",
        "-p",
        package_name,
        "--throttle",
        str(throttle),
        "--ignore-security-exceptions",
        "--monitor-native-crashes",
        "-v",
        "-v",
    )
    if seed is not None:
        cmd.extend(["-s", str(seed)])
    cmd.extend(ratios.to_monkey_args())
    cmd.append(str(event_count))
    return cmd


def run_monkey(
    serial: str,
    package_name: str,
    minutes: int,
    throttle: int,
    seed: Optional[int],
    events: Optional[int],
    ratios: EventRatios,
    output_file: Path,
    timeout_extra: int = 60,
) -> RunResult:
    output_file.parent.mkdir(parents=True, exist_ok=True)
    requested_events = events or estimate_events(minutes, throttle)
    chunk_events = requested_events if events else estimate_chunk_events(throttle)
    base_cmd = build_monkey_command(serial, package_name, minutes, throttle, seed, chunk_events, ratios)
    started = time.time()
    get_logger().info("开始 Monkey: %s 分钟, throttle=%sms", minutes, throttle)
    deadline = started + minutes * 60
    return_code = 0
    commands: list[str] = []
    with output_file.open("w", encoding="utf-8", errors="replace") as file_obj:
        round_no = 0
        while True:
            now = time.time()
            if now >= deadline:
                break
            round_no += 1
            cmd = build_monkey_command(serial, package_name, minutes, throttle, seed, chunk_events, ratios)
            commands.append(" ".join(cmd))
            remaining = max(1, int(deadline - now))
            file_obj.write(f"\n===== Monkey round {round_no}, events={chunk_events}, remaining={remaining}s =====\n")
            file_obj.flush()
            proc = subprocess.Popen(cmd, stdout=file_obj, stderr=subprocess.STDOUT, text=True)
            try:
                round_code = proc.wait(timeout=remaining + min(timeout_extra, 30))
            except subprocess.TimeoutExpired:
                reached_deadline = time.time() >= deadline
                if reached_deadline:
                    get_logger().info("Monkey 已达到目标时长，终止当前分段")
                else:
                    get_logger().warning("Monkey 分段超时，终止当前进程")
                proc.terminate()
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=5)
                if reached_deadline:
                    round_code = 0
                else:
                    round_code = proc.returncode if proc.returncode is not None else -9
            return_code = round_code
            if round_code not in (0, None):
                get_logger().warning("Monkey 分段返回非零: %s", round_code)
                break
    ended = time.time()
    command = base_cmd + ["# rounds=" + str(len(commands))]
    return RunResult("monkey", command, return_code, started, ended, str(output_file))
