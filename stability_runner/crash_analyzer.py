from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional

from .time_window import AnalysisWindow, line_in_window
from .utils import read_text_best_effort


CRASH_PATTERNS = [
    "FATAL EXCEPTION",
    "native crash",
    "Fatal signal",
    "*** *** *** ***",
]

KEYWORDS = [
    "FATAL EXCEPTION",
    "ANR",
    "Fatal signal",
    "tombstone",
    "system_server",
    "OutOfMemoryError",
    "SIGSEGV",
    "SIGABRT",
    "Watchdog",
    "ActivityManager",
    "lowmemorykiller",
]


@dataclass
class CrashSummary:
    has_crash: bool
    crash_count: int
    stack_summaries: list[str]
    keyword_counts: dict[str, int]
    tombstone_lines: list[str]
    system_server_lines: list[str]

    def to_dict(self) -> dict:
        return asdict(self)


def extract_android_runtime_crashes(log_file: Path, package_name: str, window: AnalysisWindow, output_file: Path) -> list[str]:
    lines = [line for line in read_text_best_effort(log_file).splitlines() if line_in_window(line, window)]
    blocks: list[str] = []
    idx = 0
    while idx < len(lines):
        line = lines[idx]
        if "AndroidRuntime" not in line or "FATAL EXCEPTION" not in line:
            idx += 1
            continue
        block = _collect_android_runtime_block(lines, idx)
        if package_name in "\n".join(block):
            blocks.append("\n".join(block))
        idx += max(1, len(block))

    output_file.parent.mkdir(parents=True, exist_ok=True)
    if blocks:
        content = "\n\n".join(f"===== AndroidRuntime Crash {num} =====\n{block}" for num, block in enumerate(blocks, 1))
    else:
        content = f"No AndroidRuntime crash block for {package_name} in current run window.\n"
    output_file.write_text(content, encoding="utf-8", errors="replace")
    return blocks


def analyze_crash(log_file: Path, package_name: str) -> CrashSummary:
    text = read_text_best_effort(log_file)
    lines = text.splitlines()
    stack_summaries: list[str] = []
    crash_count = 0
    keyword_counts = Counter()
    tombstone_lines: list[str] = []
    system_server_lines: list[str] = []
    seen_tombstones: set[str] = set()

    for keyword in KEYWORDS:
        keyword_counts[keyword] = text.count(keyword)

    return _analyze_lines(lines, package_name, None)


def analyze_crash_in_window(log_file: Path, package_name: str, window: AnalysisWindow, tombstone_files: list[Path] | None = None) -> CrashSummary:
    lines = [line for line in read_text_best_effort(log_file).splitlines() if line_in_window(line, window)]
    summary = _analyze_lines(lines, package_name, window)
    if tombstone_files:
        _merge_tombstone_files(summary, tombstone_files, package_name)
    return summary


def _analyze_lines(lines: list[str], package_name: str, window: Optional[AnalysisWindow]) -> CrashSummary:
    text = "\n".join(lines)
    stack_summaries: list[str] = []
    keyword_counts = Counter()
    tombstone_lines: list[str] = []
    system_server_lines: list[str] = []

    for keyword in KEYWORDS:
        keyword_counts[keyword] = text.count(keyword)

    for idx, line in enumerate(lines):
        lower = line.lower()
        if "tombstone" in lower or "fatal signal" in line:
            tombstone_lines.append(line[:500])
        if "system_server" in line or "Watchdog" in line:
            system_server_lines.append(line[:500])
        if package_name not in line and "FATAL EXCEPTION" not in line:
            continue
        if any(pattern in line for pattern in CRASH_PATTERNS):
            block = lines[idx : min(len(lines), idx + 35)]
            if package_name not in "\n".join(block):
                continue
            stack_summaries.append(_summarize_block(lines, idx))

    # Avoid counting repeated AndroidRuntime header lines as separate crashes.
    unique_summaries = []
    seen = set()
    for summary in stack_summaries:
        key = summary[:300]
        if key not in seen:
            seen.add(key)
            unique_summaries.append(summary)

    return CrashSummary(
        has_crash=bool(unique_summaries),
        crash_count=len(unique_summaries),
        stack_summaries=unique_summaries[:10],
        keyword_counts=dict(keyword_counts),
        tombstone_lines=tombstone_lines[:30],
        system_server_lines=system_server_lines[:30],
    )


def _merge_tombstone_files(summary: CrashSummary, tombstone_files: list[Path], package_name: str) -> None:
    seen = set(summary.stack_summaries)
    for path in tombstone_files:
        if path.suffix == ".pb":
            continue
        text = read_text_best_effort(path, max_bytes=200_000)
        if not text or f"Cmdline: {package_name}" not in text:
            continue
        compact = _summarize_tombstone(path.name, text)
        if compact not in seen:
            seen.add(compact)
            summary.stack_summaries.append(compact)
    summary.stack_summaries = summary.stack_summaries[:10]
    summary.crash_count = len(seen)
    summary.has_crash = summary.crash_count > 0


def _summarize_tombstone(name: str, text: str) -> str:
    keep = []
    for line in text.splitlines():
        if (
            line.startswith("Cmdline:")
            or line.startswith("pid:")
            or "signal " in line
            or line.startswith("Abort message:")
            or line.strip().startswith("#")
            or "/lib/" in line
        ):
            keep.append(line[:500])
        if len(keep) >= 20:
            break
    return f"{name}\n" + "\n".join(keep)


def _summarize_block(lines: list[str], start: int, radius: int = 35) -> str:
    block = lines[start : min(len(lines), start + radius)]
    important = []
    for line in block:
        if (
            "FATAL EXCEPTION" in line
            or "Process:" in line
            or "AndroidRuntime" in line
            or "Caused by:" in line
            or re.search(r"\bat\s+[A-Za-z0-9_.$]+", line)
            or "Fatal signal" in line
        ):
            important.append(line.strip())
    return "\n".join(important[:15]) or "\n".join(block[:10])


def _collect_android_runtime_block(lines: list[str], start: int) -> list[str]:
    block = [lines[start]]
    for line in lines[start + 1 : min(len(lines), start + 220)]:
        if "AndroidRuntime" in line and "FATAL EXCEPTION" in line:
            break
        if "AndroidRuntime" in line:
            block.append(line)
            continue
        if block and ("Process:" in line or line.lstrip().startswith("at ") or "Caused by:" in line):
            block.append(line)
            continue
        if len(block) > 3:
            break
    return block
