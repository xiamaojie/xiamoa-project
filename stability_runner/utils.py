from __future__ import annotations

import json
import logging
import shlex
import subprocess
import time
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any, Iterable, Optional


LOGGER_NAME = "stability_runner"


def setup_logger(log_file: Optional[Path] = None, verbose: bool = False) -> logging.Logger:
    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(logging.DEBUG if verbose else logging.INFO)
    logger.handlers.clear()

    formatter = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    stream_handler.setLevel(logging.DEBUG if verbose else logging.INFO)
    logger.addHandler(stream_handler)

    if log_file:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setFormatter(formatter)
        file_handler.setLevel(logging.DEBUG)
        logger.addHandler(file_handler)

    return logger


def get_logger() -> logging.Logger:
    return logging.getLogger(LOGGER_NAME)


def run_command(
    cmd: list[str],
    timeout: Optional[int] = None,
    check: bool = False,
    cwd: Optional[Path] = None,
) -> subprocess.CompletedProcess[str]:
    logger = get_logger()
    logger.debug("run: %s", " ".join(shlex.quote(part) for part in cmd))
    try:
        result = subprocess.run(
            cmd,
            cwd=str(cwd) if cwd else None,
            timeout=timeout,
            check=False,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
    except FileNotFoundError as exc:
        raise RuntimeError(f"命令不存在: {cmd[0]}") from exc
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"命令超时: {' '.join(cmd)}") from exc

    if check and result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()
        raise RuntimeError(f"命令失败({result.returncode}): {' '.join(cmd)}\n{detail}")
    return result


def adb_cmd(serial: Optional[str], *parts: str) -> list[str]:
    cmd = ["adb"]
    if serial:
        cmd.extend(["-s", serial])
    cmd.extend(parts)
    return cmd


def adb_shell(serial: Optional[str], shell_args: Iterable[str] | str, timeout: Optional[int] = 30) -> str:
    if isinstance(shell_args, str):
        cmd = adb_cmd(serial, "shell", shell_args)
    else:
        cmd = adb_cmd(serial, "shell", *list(shell_args))
    result = run_command(cmd, timeout=timeout, check=True)
    return result.stdout.strip()


def now_ms() -> int:
    return int(time.time() * 1000)


def safe_package_for_path(package_name: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in package_name)


def write_json(path: Path, data: Any) -> None:
    def default(obj: Any) -> Any:
        if is_dataclass(obj):
            return asdict(obj)
        if isinstance(obj, Path):
            return str(obj)
        raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")

    path.write_text(json.dumps(data, ensure_ascii=False, indent=2, default=default), encoding="utf-8")


def read_text_best_effort(path: Path, max_bytes: Optional[int] = None) -> str:
    try:
        if max_bytes is None:
            return path.read_text(encoding="utf-8", errors="replace")
        with path.open("rb") as file_obj:
            return file_obj.read(max_bytes).decode("utf-8", errors="replace")
    except FileNotFoundError:
        return ""
