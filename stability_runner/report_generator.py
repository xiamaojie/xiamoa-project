from __future__ import annotations

import html
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any

from .utils import write_json


def dataclass_to_dict(value: Any) -> Any:
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, list):
        return [dataclass_to_dict(item) for item in value]
    if isinstance(value, dict):
        return {key: dataclass_to_dict(item) for key, item in value.items()}
    if isinstance(value, Path):
        return str(value)
    return value


def build_conclusion(report: dict[str, Any]) -> str:
    crash = report.get("analysis", {}).get("crash", {})
    anr = report.get("analysis", {}).get("anr", {})
    perf = report.get("analysis", {}).get("performance", {})
    problems = []
    if crash.get("has_crash"):
        problems.append("Crash")
    if anr.get("has_anr"):
        problems.append("ANR")
    if perf.get("high_cpu_samples"):
        problems.append("High CPU")
    if perf.get("high_memory_samples"):
        problems.append("High Memory")
    return "FAIL: " + ", ".join(problems) if problems else "PASS: 未发现明确稳定性阻断问题"


def generate_reports(output_dir: Path, report: dict[str, Any]) -> dict[str, str]:
    report = dataclass_to_dict(report)
    report["conclusion"] = build_conclusion(report)
    json_path = output_dir / "report.json"
    md_path = output_dir / "report.md"
    html_path = output_dir / "report.html"
    write_json(json_path, report)
    md_path.write_text(_markdown(report), encoding="utf-8")
    html_path.write_text(_html(report), encoding="utf-8")
    return {"json": str(json_path), "markdown": str(md_path), "html": str(html_path)}


def _markdown(report: dict[str, Any]) -> str:
    crash = report["analysis"]["crash"]
    anr = report["analysis"]["anr"]
    perf = report["analysis"]["performance"]
    paths = report.get("artifacts", {})
    lines = [
        "# Android 稳定性测试报告",
        "",
        f"- 结论: **{report['conclusion']}**",
        f"- 包名: `{report['package_name']}`",
        f"- 设备: `{report['device'].get('serial', '')}` {report['device'].get('brand', '')} {report['device'].get('model', '')}",
        f"- 模式: `{report['config'].get('mode')}`",
        f"- 运行时长: `{report['config'].get('minutes')}` 分钟",
        f"- 安装包: `{report['package_path']}`",
        "",
        "## 稳定性摘要",
        "",
        f"- Crash: {'是' if crash.get('has_crash') else '否'}，数量: {crash.get('crash_count', 0)}",
        f"- ANR: {'是' if anr.get('has_anr') else '否'}，数量: {anr.get('anr_count', 0)}",
        f"- 高 CPU 样本: {len(perf.get('high_cpu_samples', []))}",
        f"- 高内存样本: {len(perf.get('high_memory_samples', []))}",
        "",
        "## 关键异常关键词统计",
        "",
    ]
    for key, value in crash.get("keyword_counts", {}).items():
        lines.append(f"- `{key}`: {value}")

    lines.extend(["", "## Crash 堆栈摘要", ""])
    lines.append(f"AndroidRuntime crash block 数量: {report['analysis'].get('android_runtime_crash_count', 0)}")
    lines.append("")
    if crash.get("stack_summaries"):
        for idx, summary in enumerate(crash["stack_summaries"], 1):
            lines.extend([f"### Crash {idx}", "", "```text", summary[:4000], "```", ""])
    else:
        lines.append("未发现明确 Crash 堆栈。")

    lines.extend(["", "## ANR 摘要", ""])
    if anr.get("events"):
        for event in anr["events"]:
            lines.extend(
                [
                    f"- line {event.get('line_no')}, time `{event.get('timestamp')}`",
                    "",
                    "```text",
                    event.get("reason", "")[:1000],
                    "```",
                ]
            )
    else:
        lines.append("未发现明确 ANR。")

    lines.extend(["", "## 性能摘要", ""])
    lines.append(f"- 最大 CPU: {perf.get('max_cpu_percent')}")
    lines.append(f"- 最大 RSS KB: {perf.get('max_rss_kb')}")
    lines.append(f"- 最大 PSS KB: {perf.get('max_pss_kb')}")

    lines.extend(["", "## 产物", ""])
    for key, value in paths.items():
        lines.append(f"- {key}: `{value}`")
    lines.append("")
    return "\n".join(lines)


def _html(report: dict[str, Any]) -> str:
    md = _markdown(report)
    escaped = html.escape(md)
    status = "fail" if report["conclusion"].startswith("FAIL") else "pass"
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <title>Android Stability Report</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; margin: 32px; color: #202124; }}
    .status {{ display: inline-block; padding: 6px 10px; border-radius: 4px; font-weight: 700; }}
    .pass {{ background: #e6f4ea; color: #137333; }}
    .fail {{ background: #fce8e6; color: #a50e0e; }}
    pre {{ white-space: pre-wrap; background: #f8f9fa; border: 1px solid #dadce0; padding: 16px; border-radius: 6px; }}
  </style>
</head>
<body>
  <div class="status {status}">{html.escape(report["conclusion"])}</div>
  <pre>{escaped}</pre>
</body>
</html>
"""


def analyze_performance(samples: list[Any]) -> dict[str, Any]:
    rows = [asdict(sample) if is_dataclass(sample) else sample for sample in samples]
    cpu_values = [row["cpu_percent"] for row in rows if row.get("cpu_percent") is not None]
    rss_values = [row["rss_kb"] for row in rows if row.get("rss_kb") is not None]
    pss_values = [row["pss_kb"] for row in rows if row.get("pss_kb") is not None]
    high_cpu = [row for row in rows if row.get("cpu_percent") is not None and row["cpu_percent"] >= 80]
    high_memory = [row for row in rows if row.get("pss_kb") is not None and row["pss_kb"] >= 800 * 1024]
    return {
        "sample_count": len(rows),
        "max_cpu_percent": max(cpu_values) if cpu_values else None,
        "max_rss_kb": max(rss_values) if rss_values else None,
        "max_pss_kb": max(pss_values) if pss_values else None,
        "high_cpu_samples": high_cpu[:20],
        "high_memory_samples": high_memory[:20],
    }
