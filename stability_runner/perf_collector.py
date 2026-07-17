from __future__ import annotations

import csv
import re
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .utils import adb_shell, get_logger


@dataclass
class PerfSample:
    timestamp: float
    pid: str
    cpu_percent: Optional[float]
    rss_kb: Optional[int]
    pss_kb: Optional[int]


class PerfCollector:
    def __init__(self, serial: str, package_name: str, output_dir: Path, interval: int = 10) -> None:
        self.serial = serial
        self.package_name = package_name
        self.output_dir = output_dir
        self.interval = interval
        self.samples: list[PerfSample] = []
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        get_logger().info("开始性能采样: interval=%ss", self.interval)
        self._thread = threading.Thread(target=self._loop, name="perf_collector", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=self.interval + 5)
        self._write_csv()

    def _loop(self) -> None:
        while not self._stop.is_set():
            self.collect_once()
            self._stop.wait(self.interval)

    def collect_once(self) -> None:
        ts = time.time()
        pid = self._pidof()
        cpu = self._cpu_percent(pid)
        rss = self._rss_kb(pid)
        pss = self._pss_kb()
        self.samples.append(PerfSample(ts, pid or "", cpu, rss, pss))
        self._dump_command("meminfo", "dumpsys meminfo " + self.package_name, ts)
        self._dump_command("gfxinfo", "dumpsys gfxinfo " + self.package_name, ts)

    def _pidof(self) -> Optional[str]:
        try:
            out = adb_shell(self.serial, f"pidof {self.package_name}", timeout=10)
            return out.split()[0] if out.strip() else None
        except RuntimeError:
            return None

    def _cpu_percent(self, pid: Optional[str]) -> Optional[float]:
        if not pid:
            return None
        try:
            out = adb_shell(self.serial, f"top -b -n 1 -p {pid}", timeout=15)
        except RuntimeError:
            return None
        for line in out.splitlines():
            if pid in line:
                match = re.search(r"(\d+(?:\.\d+)?)%", line)
                if match:
                    return float(match.group(1))
                header = next((item for item in out.splitlines() if "%CPU" in item), "")
                parts = line.split()
                headers = header.replace("[", " ").replace("]", " ").split()
                if "%CPU" in headers and len(parts) >= len(headers):
                    idx = headers.index("%CPU")
                    value = parts[idx]
                    if value.replace(".", "", 1).isdigit():
                        return float(value)
                for idx, part in enumerate(parts):
                    if part in {"R", "S", "D"} and idx + 1 < len(parts):
                        value = parts[idx + 1]
                        if value.replace(".", "", 1).isdigit():
                            return float(value)
        return None

    def _rss_kb(self, pid: Optional[str]) -> Optional[int]:
        if not pid:
            return None
        try:
            out = adb_shell(self.serial, f"cat /proc/{pid}/status", timeout=10)
        except RuntimeError:
            return None
        match = re.search(r"VmRSS:\s+(\d+)\s+kB", out)
        return int(match.group(1)) if match else None

    def _pss_kb(self) -> Optional[int]:
        try:
            out = adb_shell(self.serial, f"dumpsys meminfo {self.package_name}", timeout=20)
        except RuntimeError:
            return None
        match = re.search(r"TOTAL\s+(\d+)", out)
        return int(match.group(1)) if match else None

    def _dump_command(self, prefix: str, command: str, timestamp: float) -> None:
        try:
            out = adb_shell(self.serial, command, timeout=30)
        except RuntimeError as exc:
            out = str(exc)
        file_name = f"{prefix}_{int(timestamp)}.txt"
        (self.output_dir / file_name).write_text(out, encoding="utf-8", errors="replace")

    def _write_csv(self) -> None:
        csv_path = self.output_dir / "perf_samples.csv"
        with csv_path.open("w", newline="", encoding="utf-8") as file_obj:
            writer = csv.DictWriter(file_obj, fieldnames=["timestamp", "pid", "cpu_percent", "rss_kb", "pss_kb"])
            writer.writeheader()
            for sample in self.samples:
                writer.writerow(sample.__dict__)
