from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .utils import adb_cmd, get_logger


@dataclass
class LogcatCollector:
    serial: str
    output_file: Path
    process: Optional[subprocess.Popen[str]] = None

    def start(self) -> None:
        self.output_file.parent.mkdir(parents=True, exist_ok=True)
        get_logger().info("开始采集 logcat: %s", self.output_file)
        file_obj = self.output_file.open("w", encoding="utf-8", errors="replace")
        self.process = subprocess.Popen(
            adb_cmd(self.serial, "logcat", "-v", "threadtime"),
            stdout=file_obj,
            stderr=subprocess.STDOUT,
            text=True,
        )
        # Keep a reference so the descriptor is not closed too early.
        self._file_obj = file_obj

    def stop(self) -> None:
        if self.process and self.process.poll() is None:
            get_logger().info("停止 logcat 采集")
            self.process.terminate()
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)
        file_obj = getattr(self, "_file_obj", None)
        if file_obj:
            file_obj.close()
