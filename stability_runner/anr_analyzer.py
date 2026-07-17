from __future__ import annotations

import re
from dataclasses import dataclass, asdict
from pathlib import Path

from .time_window import AnalysisWindow, line_in_window
from .utils import read_text_best_effort


@dataclass
class AnrEvent:
    line_no: int
    timestamp: str
    reason: str
    context: str


@dataclass
class AnrSummary:
    has_anr: bool
    anr_count: int
    events: list[dict]

    def to_dict(self) -> dict:
        return asdict(self)


def analyze_anr(log_file: Path, package_name: str) -> AnrSummary:
    lines = read_text_best_effort(log_file).splitlines()
    events: list[AnrEvent] = []
    for idx, line in enumerate(lines):
        if " ANR " in line or "Application Not Responding" in line or "Input dispatching timed out" in line:
            if package_name in line or "ANR" in line or "Input dispatching timed out" in line:
                events.append(
                    AnrEvent(
                        line_no=idx + 1,
                        timestamp=_timestamp(line),
                        reason=_reason(line),
                        context="\n".join(lines[max(0, idx - 5) : min(len(lines), idx + 15)]),
                    )
                )
    deduped: list[AnrEvent] = []
    seen = set()
    for event in events:
        key = (event.timestamp, event.reason[:120])
        if key not in seen:
            seen.add(key)
            deduped.append(event)
    return AnrSummary(bool(deduped), len(deduped), [asdict(event) for event in deduped[:10]])


def analyze_anr_in_window(log_file: Path, package_name: str, window: AnalysisWindow) -> AnrSummary:
    lines = [line for line in read_text_best_effort(log_file).splitlines() if line_in_window(line, window)]
    events: list[AnrEvent] = []
    for idx, line in enumerate(lines):
        if (" ANR " in line or "Application Not Responding" in line or "Input dispatching timed out" in line) and package_name in line:
            events.append(
                AnrEvent(
                    line_no=idx + 1,
                    timestamp=_timestamp(line),
                    reason=_reason(line),
                    context="\n".join(lines[max(0, idx - 5) : min(len(lines), idx + 15)]),
                )
            )
    deduped: list[AnrEvent] = []
    seen = set()
    for event in events:
        key = (event.timestamp, event.reason[:120])
        if key not in seen:
            seen.add(key)
            deduped.append(event)
    return AnrSummary(bool(deduped), len(deduped), [asdict(event) for event in deduped[:10]])


def _timestamp(line: str) -> str:
    match = re.match(r"(\d{2}-\d{2}\s+\d{2}:\d{2}:\d{2}\.\d+)", line)
    return match.group(1) if match else ""


def _reason(line: str) -> str:
    for marker in ("Reason:", "ANR in", "Input dispatching timed out"):
        if marker in line:
            return line[line.find(marker) :].strip()[:500]
    return line.strip()[:500]
