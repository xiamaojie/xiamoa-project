from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional


DEFAULT_DOWNLOADS = Path.home() / "Downloads"
DEFAULT_OUTPUT_ROOT = Path.home() / "TestLog" / "android_stability"
DEFAULT_BUNDLETOOL = Path("/Users/admin/bundletool.jar")


@dataclass
class EventRatios:
    pct_touch: Optional[int] = None
    pct_motion: Optional[int] = None
    pct_trackball: Optional[int] = None
    pct_nav: Optional[int] = None
    pct_majornav: Optional[int] = None
    pct_syskeys: Optional[int] = None
    pct_appswitch: Optional[int] = None
    pct_anyevent: Optional[int] = None

    def to_monkey_args(self) -> list[str]:
        mapping = {
            "pct_touch": "--pct-touch",
            "pct_motion": "--pct-motion",
            "pct_trackball": "--pct-trackball",
            "pct_nav": "--pct-nav",
            "pct_majornav": "--pct-majornav",
            "pct_syskeys": "--pct-syskeys",
            "pct_appswitch": "--pct-appswitch",
            "pct_anyevent": "--pct-anyevent",
        }
        args: list[str] = []
        for attr, option in mapping.items():
            value = getattr(self, attr)
            if value is not None:
                args.extend([option, str(value)])
        return args


@dataclass
class RunnerConfig:
    apk_path: Path
    package_name: Optional[str]
    serial: Optional[str]
    mode: str
    minutes: int
    throttle: int
    seed: Optional[int]
    events: Optional[int]
    output_root: Path
    bundletool: Path
    install_timeout: int
    command_timeout_extra: int
    perf_interval: int
    ratios: EventRatios = field(default_factory=EventRatios)
    skip_install: bool = False
    keep_app: bool = False
    verbose: bool = False


def find_latest_package(directory: Path = DEFAULT_DOWNLOADS) -> Path:
    candidates = []
    if directory.exists():
        for suffix in ("*.apk", "*.aab"):
            candidates.extend(directory.glob(suffix))
    candidates = [path for path in candidates if path.is_file()]
    if not candidates:
        raise FileNotFoundError(f"未在 {directory} 找到 .apk 或 .aab 文件")
    return max(candidates, key=lambda path: path.stat().st_mtime)


def positive_int(value: str) -> int:
    number = int(value)
    if number <= 0:
        raise argparse.ArgumentTypeError("必须是正整数")
    return number


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Android APK/AAB 稳定性回归测试工具")
    parser.add_argument("--apk", "--aab", dest="apk", help="APK/AAB 路径；不填则读取 ~/Downloads 最新包")
    parser.add_argument("--package-name", "--package", dest="package_name", help="应用包名；不填则自动解析")
    parser.add_argument("--serial", help="ADB 设备序列号；不填则自动选择唯一在线设备")
    parser.add_argument("--mode", choices=["monkey", "fastbot", "both"], default="monkey", help="测试模式")
    parser.add_argument("--minutes", type=positive_int, default=5, help="运行分钟数，例如 5/10/20/30")
    parser.add_argument("--throttle", type=positive_int, default=300, help="事件间隔，单位 ms")
    parser.add_argument("--seed", type=int, help="Monkey/Fastbot 随机种子")
    parser.add_argument("--events", type=positive_int, help="Monkey 事件数；不填按分钟和 throttle 估算")
    parser.add_argument("--output-root", default=str(DEFAULT_OUTPUT_ROOT), help="报告根目录")
    parser.add_argument("--bundletool", default=None, help="bundletool.jar 路径；默认 $BUNDLETOOL_JAR 或 /Users/admin/bundletool.jar")
    parser.add_argument("--install-timeout", type=positive_int, default=300, help="安装超时时间，秒")
    parser.add_argument("--perf-interval", type=positive_int, default=10, help="性能采样间隔，秒")
    parser.add_argument("--skip-install", action="store_true", help="跳过安装，直接对已安装应用测试")
    parser.add_argument("--keep-app", action="store_true", help="测试结束后保留应用；默认不卸载最终包，仅影响未来扩展")
    parser.add_argument("--verbose", action="store_true", help="输出调试日志")

    parser.add_argument("--pct-touch", type=int)
    parser.add_argument("--pct-motion", type=int)
    parser.add_argument("--pct-trackball", type=int)
    parser.add_argument("--pct-nav", type=int)
    parser.add_argument("--pct-majornav", type=int)
    parser.add_argument("--pct-syskeys", type=int)
    parser.add_argument("--pct-appswitch", type=int)
    parser.add_argument("--pct-anyevent", type=int)
    return parser


def load_config(argv: Optional[list[str]] = None) -> RunnerConfig:
    import os

    parser = build_parser()
    args = parser.parse_args(argv)
    package_path = Path(args.apk).expanduser().resolve() if args.apk else find_latest_package().resolve()
    if not package_path.exists():
        raise FileNotFoundError(f"安装包不存在: {package_path}")
    if package_path.suffix.lower() not in {".apk", ".aab"}:
        raise ValueError(f"仅支持 .apk/.aab: {package_path}")

    bundletool_raw = args.bundletool or os.environ.get("BUNDLETOOL_JAR") or str(DEFAULT_BUNDLETOOL)
    return RunnerConfig(
        apk_path=package_path,
        package_name=args.package_name,
        serial=args.serial,
        mode=args.mode,
        minutes=args.minutes,
        throttle=args.throttle,
        seed=args.seed,
        events=args.events,
        output_root=Path(args.output_root).expanduser().resolve(),
        bundletool=Path(bundletool_raw).expanduser().resolve(),
        install_timeout=args.install_timeout,
        command_timeout_extra=60,
        perf_interval=args.perf_interval,
        ratios=EventRatios(
            pct_touch=args.pct_touch,
            pct_motion=args.pct_motion,
            pct_trackball=args.pct_trackball,
            pct_nav=args.pct_nav,
            pct_majornav=args.pct_majornav,
            pct_syskeys=args.pct_syskeys,
            pct_appswitch=args.pct_appswitch,
            pct_anyevent=args.pct_anyevent,
        ),
        skip_install=args.skip_install,
        keep_app=args.keep_app,
        verbose=args.verbose,
    )
