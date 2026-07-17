from __future__ import annotations

import sys
import time
from datetime import datetime
from pathlib import Path

from .anr_analyzer import analyze_anr_in_window
from .config_loader import RunnerConfig, load_config
from .crash_analyzer import analyze_crash_in_window, extract_android_runtime_crashes
from .device_info import collect_device_info, prepare_device, select_device
from .fastbot_runner import run_fastbot
from .installer import install_package, parse_package_name
from .logcat_collector import LogcatCollector
from .monkey_runner import RunResult, run_monkey
from .perf_collector import PerfCollector
from .report_generator import analyze_performance, generate_reports
from .time_window import build_analysis_window, pull_new_tombstones, snapshot_tombstones
from .utils import get_logger, safe_package_for_path, setup_logger


def main(argv: list[str] | None = None) -> int:
    config = load_config(argv)
    package_name = config.package_name or parse_package_name(config.apk_path, config.bundletool)
    output_dir = _create_output_dir(config, package_name)
    logger = setup_logger(output_dir / "runner.log", config.verbose)
    logger.info("输出目录: %s", output_dir)
    logger.info("安装包: %s", config.apk_path)
    logger.info("包名: %s", package_name)

    run_results: list[RunResult] = []
    logcat = None
    perf = None
    install_result = None
    device = {}
    error = None
    serial = None
    fallback_started = time.time()
    tombstones_before = {}
    tombstones_after = {}
    pulled_tombstones: list[str] = []

    try:
        serial = select_device(config.serial)
        logger.info("目标设备: %s", serial)
        prepare_device(serial, output_dir)
        device_info = collect_device_info(serial)
        device = device_info.to_dict()

        install_result = install_package(
            serial=serial,
            package_path=config.apk_path,
            package_name=package_name,
            bundletool=config.bundletool,
            timeout=config.install_timeout,
            skip_install=config.skip_install,
        )
        if not install_result.installed:
            raise RuntimeError(f"安装后未检测到包名: {package_name}")

        tombstones_before = snapshot_tombstones(serial, output_dir / "tombstones" / "before.txt")
        logcat = LogcatCollector(serial, output_dir / "logs" / "logcat.txt")
        logcat.start()
        perf = PerfCollector(serial, package_name, output_dir / "perf", config.perf_interval)
        perf.start()

        if config.mode in {"monkey", "both"}:
            run_results.append(
                run_monkey(
                    serial=serial,
                    package_name=package_name,
                    minutes=config.minutes,
                    throttle=config.throttle,
                    seed=config.seed,
                    events=config.events,
                    ratios=config.ratios,
                    output_file=output_dir / "logs" / "monkey_output.txt",
                    timeout_extra=config.command_timeout_extra,
                )
            )
        if config.mode in {"fastbot", "both"}:
            result = run_fastbot(
                serial=serial,
                package_name=package_name,
                minutes=config.minutes,
                throttle=config.throttle,
                seed=config.seed,
                output_dir=output_dir / "logs",
                timeout_extra=config.command_timeout_extra,
            )
            if result:
                run_results.append(result)
    except Exception as exc:
        error = str(exc)
        get_logger().exception("稳定性测试失败: %s", exc)
    finally:
        if perf:
            perf.stop()
        if logcat:
            logcat.stop()
        if serial:
            tombstones_after = snapshot_tombstones(serial, output_dir / "tombstones" / "after.txt")
            pulled_tombstones = pull_new_tombstones(
                serial,
                tombstones_before,
                tombstones_after,
                output_dir / "tombstones" / "new",
            )

    logcat_file = output_dir / "logs" / "logcat.txt"
    analysis_input = _create_analysis_input(output_dir)
    analysis_window = build_analysis_window(run_results, fallback_started, time.time())
    crash = analyze_crash_in_window(analysis_input, package_name, analysis_window, [Path(path) for path in pulled_tombstones])
    android_runtime_file = output_dir / "logs" / "crash_androidruntime.txt"
    android_runtime_blocks = extract_android_runtime_crashes(logcat_file, package_name, analysis_window, android_runtime_file)
    anr = analyze_anr_in_window(logcat_file, package_name, analysis_window)
    performance = analyze_performance(perf.samples if perf else [])
    report = {
        "package_name": package_name,
        "package_path": str(config.apk_path),
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "device": device,
        "config": _config_for_report(config),
        "install": install_result,
        "runs": run_results,
        "analysis_window": analysis_window,
        "analysis": {
            "crash": crash,
            "android_runtime_crash_count": len(android_runtime_blocks),
            "anr": anr,
            "performance": performance,
        },
        "artifacts": {
            "output_dir": str(output_dir),
            "runner_log": str(output_dir / "runner.log"),
            "logcat": str(logcat_file),
            "analysis_input": str(analysis_input),
            "android_runtime_crashes": str(android_runtime_file),
            "perf_csv": str(output_dir / "perf" / "perf_samples.csv"),
            "monkey_output": str(output_dir / "logs" / "monkey_output.txt"),
            "tombstones_before": str(output_dir / "tombstones" / "before.txt"),
            "tombstones_after": str(output_dir / "tombstones" / "after.txt"),
            "new_tombstones": pulled_tombstones,
        },
        "error": error,
    }
    report_paths = generate_reports(output_dir, report)
    get_logger().info("报告已生成: %s", report_paths)
    print(f"输出目录: {output_dir}")
    print(f"JSON: {report_paths['json']}")
    print(f"Markdown: {report_paths['markdown']}")
    print(f"HTML: {report_paths['html']}")
    return 1 if error else 0


def _create_output_dir(config: RunnerConfig, package_name: str) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = config.output_root / f"{timestamp}_{safe_package_for_path(package_name)}"
    output_dir.mkdir(parents=True, exist_ok=False)
    (output_dir / "logs").mkdir()
    return output_dir


def _config_for_report(config: RunnerConfig) -> dict:
    return {
        "mode": config.mode,
        "minutes": config.minutes,
        "throttle": config.throttle,
        "seed": config.seed,
        "events": config.events,
        "output_root": str(config.output_root),
        "bundletool": str(config.bundletool),
        "perf_interval": config.perf_interval,
        "skip_install": config.skip_install,
        "ratios": config.ratios.__dict__,
    }


def _create_analysis_input(output_dir: Path) -> Path:
    combined = output_dir / "logs" / "analysis_input.txt"
    parts = []
    for source in (output_dir / "logs" / "logcat.txt", output_dir / "logs" / "monkey_output.txt", output_dir / "logs" / "fastbot_output.txt"):
        if source.exists():
            parts.append(f"\n===== {source.name} =====\n")
            parts.append(source.read_text(encoding="utf-8", errors="replace"))
    combined.write_text("".join(parts), encoding="utf-8", errors="replace")
    return combined


if __name__ == "__main__":
    sys.exit(main())
