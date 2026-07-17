from __future__ import annotations

import tempfile
from pathlib import Path

from .anr_analyzer import analyze_anr
from .crash_analyzer import analyze_crash
from .report_generator import analyze_performance, generate_reports


SAMPLE_LOG = """05-13 10:00:00.000  1000  1000 E AndroidRuntime: FATAL EXCEPTION: main
05-13 10:00:00.000  1000  1000 E AndroidRuntime: Process: com.example.demo, PID: 1000
05-13 10:00:00.000  1000  1000 E AndroidRuntime: java.lang.RuntimeException: demo crash
05-13 10:00:00.001  1000  1000 E AndroidRuntime: Caused by: java.lang.IllegalStateException: bad state
05-13 10:00:10.000  2000  2000 E ActivityManager: ANR in com.example.demo
05-13 10:00:10.001  2000  2000 E ActivityManager: Reason: Input dispatching timed out
"""


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="stability_self_check_") as temp_dir:
        root = Path(temp_dir)
        log_file = root / "logcat.txt"
        log_file.write_text(SAMPLE_LOG, encoding="utf-8")
        crash = analyze_crash(log_file, "com.example.demo")
        anr = analyze_anr(log_file, "com.example.demo")
        report = {
            "package_name": "com.example.demo",
            "package_path": "/tmp/demo.apk",
            "created_at": "self-check",
            "device": {"serial": "offline"},
            "config": {"mode": "self-check", "minutes": 1},
            "install": None,
            "runs": [],
            "analysis": {"crash": crash, "anr": anr, "performance": analyze_performance([])},
            "artifacts": {"logcat": str(log_file)},
            "error": None,
        }
        paths = generate_reports(root, report)
        assert crash.has_crash, "crash analyzer did not detect sample crash"
        assert anr.has_anr, "anr analyzer did not detect sample ANR"
        for path in paths.values():
            assert Path(path).exists(), f"missing report: {path}"
        print("self-check passed")
        for key, value in paths.items():
            print(f"{key}: {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
