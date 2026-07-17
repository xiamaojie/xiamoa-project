from __future__ import annotations

import re
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Optional

from .utils import adb_cmd, get_logger, run_command


LOGCAT_TS_RE = re.compile(r"^(\d{2})-(\d{2})\s+(\d{2}):(\d{2}):(\d{2})\.(\d{3})")


@dataclass
class AnalysisWindow:
    started_at: float
    ended_at: float
    started_iso: str
    ended_iso: str

    def to_dict(self) -> dict:
        return asdict(self)


def build_analysis_window(run_results: list, fallback_started: float, fallback_ended: float) -> AnalysisWindow:
    starts = [getattr(result, "started_at", None) for result in run_results if getattr(result, "started_at", None)]
    ends = [getattr(result, "ended_at", None) for result in run_results if getattr(result, "ended_at", None)]
    started_at = min(starts) if starts else fallback_started
    ended_at = max(ends) if ends else fallback_ended
    return AnalysisWindow(
        started_at=started_at,
        ended_at=ended_at,
        started_iso=datetime.fromtimestamp(started_at).isoformat(timespec="seconds"),
        ended_iso=datetime.fromtimestamp(ended_at).isoformat(timespec="seconds"),
    )


def line_in_window(line: str, window: Optional[AnalysisWindow]) -> bool:
    if window is None:
        return True
    parsed = parse_logcat_datetime(line, datetime.fromtimestamp(window.started_at).year)
    if parsed is None:
        return True
    epoch = parsed.timestamp()
    return window.started_at - 2 <= epoch <= window.ended_at + 2


def parse_logcat_datetime(line: str, year: int) -> Optional[datetime]:
    match = LOGCAT_TS_RE.match(line)
    if not match:
        return None
    month, day, hour, minute, second, millis = [int(part) for part in match.groups()]
    try:
        return datetime(year, month, day, hour, minute, second, millis * 1000)
    except ValueError:
        return None


def snapshot_tombstones(serial: str, output_file: Path) -> dict[str, str]:
    output_file.parent.mkdir(parents=True, exist_ok=True)
    result = run_command(adb_cmd(serial, "shell", "ls", "-l", "/data/tombstones"), timeout=20, check=False)
    text = (result.stdout + result.stderr).strip()
    output_file.write_text(text, encoding="utf-8", errors="replace")
    return parse_tombstone_listing(text)


def parse_tombstone_listing(text: str) -> dict[str, str]:
    tombstones: dict[str, str] = {}
    for line in text.splitlines():
        parts = line.split()
        if not parts:
            continue
        name = parts[-1]
        if re.fullmatch(r"tombstone_\d+(?:\.pb)?", name):
            tombstones[name] = line
    return tombstones


def pull_new_tombstones(serial: str, before: dict[str, str], after: dict[str, str], output_dir: Path) -> list[str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    changed = [name for name, line in after.items() if before.get(name) != line]
    pulled: list[str] = []
    for name in sorted(changed):
        remote = f"/data/tombstones/{name}"
        result = run_command(adb_cmd(serial, "pull", remote, str(output_dir / name)), timeout=60, check=False)
        if result.returncode == 0:
            pulled.append(str(output_dir / name))
        else:
            get_logger().warning("拉取 tombstone 失败: %s %s", remote, (result.stderr or result.stdout).strip())
    return pulled
