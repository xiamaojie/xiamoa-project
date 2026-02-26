#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
OpenClaw Gateway 开关脚本（兼容 macOS / Windows）

用法：
  python Openclaw_Status_Switch.py              # 切换（debug=false）
  python Openclaw_Status_Switch.py toggle       # 同上
  python Openclaw_Status_Switch.py toggle --debug true
  python Openclaw_Status_Switch.py toggle --wait 10
  python Openclaw_Status_Switch.py status
  python Openclaw_Status_Switch.py logs         # 追踪日志（仅 debug=true 时生成）

环境变量：
  OPENCLAW_PORT=18789
  OPENCLAW_LOG_FILE=./gateway.out   （默认保存到当前目录）
"""


import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path


# 参数配置（需要默认值时可改这里，命令行参数会覆盖）
DEFAULT_DEBUG = False  # 默认是否开启 verbose 日志（等价于 --debug true）
DEFAULT_PORT = int(os.environ.get("OPENCLAW_PORT", "18789"))  # 默认监听端口（可被环境变量覆盖）
DEFAULT_WAIT_SEC = 10.0  # 默认启动等待时长（秒）

def default_log_file() -> Path:
    env = os.environ.get("OPENCLAW_LOG_FILE")
    if env:
        return Path(env).expanduser()

    return Path.cwd() / "gateway.out"


LOG_FILE = default_log_file()


def can_listen(port: int) -> bool:
    """端口空闲则返回 True（即没有进程监听）。"""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.settimeout(0.5)
        s.connect(("127.0.0.1", port))
        return False
    except (ConnectionRefusedError, OSError):
        return True
    finally:
        try:
            s.close()
        except OSError:
            pass


def is_running(port: int) -> bool:
    """端口被监听则返回 True。"""
    return not can_listen(port)


def find_pid_by_port(port: int) -> int | None:
    """
    尽力查找端口监听进程 PID。
    macOS/Linux：使用 lsof
    Windows：使用 netstat + tasklist
    """
    if os.name != "nt":
        try:
            # lsof -nP -iTCP:18789 -sTCP:LISTEN
            out = subprocess.check_output(
                ["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN"],
                stderr=subprocess.DEVNULL,
                text=True,
            )
            lines = [ln.strip() for ln in out.splitlines() if ln.strip()]
            # 至少包含表头 + 一行数据
            if len(lines) >= 2:
                parts = lines[1].split()
                if len(parts) >= 2 and parts[1].isdigit():
                    return int(parts[1])
        except (subprocess.CalledProcessError, FileNotFoundError, OSError):
            return None
        return None

    # Windows
    try:
        # netstat -ano | findstr :18789 | findstr LISTENING
        out = subprocess.check_output(
            ["cmd", "/c", f'netstat -ano | findstr :{port} | findstr LISTENING'],
            stderr=subprocess.DEVNULL,
            text=True,
        )
        # 示例：TCP 127.0.0.1:18789 0.0.0.0:0 LISTENING 12345
        for ln in out.splitlines():
            ln = ln.strip()
            if not ln:
                continue
            parts = ln.split()
            if parts and parts[-1].isdigit():
                return int(parts[-1])
    except (subprocess.CalledProcessError, FileNotFoundError, OSError):
        return None
    return None


def run_cmd_quiet(cmd: list[str]) -> tuple[int, str]:
    try:
        p = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        return p.returncode, p.stdout or ""
    except FileNotFoundError:
        return 127, f"未找到命令：{cmd[0]}"
    except Exception as e:
        return 1, str(e)


def start_gateway(port: int, debug: bool, log_file: Path, wait_sec: float) -> None:
    log_file.parent.mkdir(parents=True, exist_ok=True)

    if debug:
        # 写入日志
        stdout_target = open(log_file, "w", encoding="utf-8", errors="replace")
        stderr_target = subprocess.STDOUT
        cmd = ["openclaw", "gateway", "--verbose"]
        print(f"[openclaw-toggle] 正在启动 gateway（debug=true），日志：{log_file}")
    else:
        # 静默启动
        stdout_target = subprocess.DEVNULL
        stderr_target = subprocess.DEVNULL
        cmd = ["openclaw", "gateway"]
        print("[openclaw-toggle] 正在启动 gateway（debug=false，静默）。")
    print(f"[openclaw-toggle] 启动命令：{' '.join(cmd)}")

    # 后台分离进程
    if os.name == "nt":
        creation_flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
        start_new_session = False
    else:
        # macOS/Linux
        creation_flags = 0
        start_new_session = True

    try:
        env = os.environ.copy()
        env["OPENCLAW_PORT"] = str(port)
        subprocess.Popen(
            cmd,
            stdout=stdout_target,
            stderr=stderr_target,
            stdin=subprocess.DEVNULL,
            creationflags=creation_flags,
            start_new_session=start_new_session,
            close_fds=(os.name != "nt"),
            env=env,
        )
    except FileNotFoundError:
        print("[openclaw-toggle] 错误：找不到 openclaw 命令。请确认已安装并在 PATH 中。")
        sys.exit(127)

    # 轮询端口，避免固定等待过长/过短
    deadline = time.monotonic() + wait_sec
    while time.monotonic() < deadline:
        if is_running(port):
            break
        time.sleep(0.2)

    if is_running(port):
        url = f"http://127.0.0.1:{port}/"
        print(f"[openclaw-toggle] 启动成功，监听 127.0.0.1:{port}")
        print(f"[openclaw-toggle] 访问地址：{url}")
        if debug:
            print(f"[openclaw-toggle] 查看日志：python {Path(__file__).name} logs")
    else:
        print("[openclaw-toggle] 警告：启动后未检测到端口监听，可能启动失败。")
        print("[openclaw-toggle] 建议：在前台执行 openclaw gateway --verbose 以排查。")
        sys.exit(1)


def stop_gateway(port: int) -> None:
    if not is_running(port):
        print("[openclaw-toggle] gateway 未运行。")
        return

    pid = find_pid_by_port(port)
    print(f"[openclaw-toggle] 正在停止 port {port}（pid={pid or 'unknown'}）")

    # 先尝试优雅停止（可能提示 service not loaded，但不一定失败）
    stop_cmd = ["openclaw", "gateway", "stop"]
    print(f"[openclaw-toggle] 停止命令：{' '.join(stop_cmd)}")
    run_cmd_quiet(stop_cmd)

    deadline = time.monotonic() + 4.0
    while time.monotonic() < deadline:
        if not is_running(port):
            print("[openclaw-toggle] 已停止。")
            return
        time.sleep(0.2)

    # 仍在监听则尝试结束 PID
    pid = find_pid_by_port(port)
    if pid is None:
        print("[openclaw-toggle] 未能解析 PID，端口仍被占用。")
        print(f"[openclaw-toggle] 请手动停止监听 {port} 的进程。")
        sys.exit(1)

    try:
        if os.name == "nt":
            # 先尝试温和结束，再尝试强制结束
            subprocess.run(["taskkill", "/PID", str(pid), "/T"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            time.sleep(1.0)
            if is_running(port):
                subprocess.run(["taskkill", "/F", "/PID", str(pid), "/T"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        else:
            os.kill(pid, signal.SIGTERM)
            time.sleep(1.0)
            if is_running(port):
                os.kill(pid, signal.SIGKILL)
    except Exception as e:
        print(f"[openclaw-toggle] 结束进程失败 pid={pid}: {e}")
        sys.exit(1)

    deadline = time.monotonic() + 4.0
    while time.monotonic() < deadline:
        if not is_running(port):
            print("[openclaw-toggle] 已停止。")
            return
        time.sleep(0.2)
    print("[openclaw-toggle] 停止失败：端口仍被占用。")
    sys.exit(1)


def show_status(port: int) -> None:
    if is_running(port):
        pid = find_pid_by_port(port)
        print(f"运行中 port={port} pid={pid or 'unknown'}")
    else:
        print(f"已停止 port={port}")


def tail_logs(log_file: Path) -> None:
    if not log_file.exists():
        print(f"[openclaw-toggle] 未找到日志文件：{log_file}")
        print("[openclaw-toggle] 使用 --debug true 启动以生成日志。")
        return

    print(f"[openclaw-toggle] 正在追踪日志 {log_file}（Ctrl+C 退出）")
    if os.name == "nt":
        # Windows 简单追踪实现
        with open(log_file, "r", encoding="utf-8", errors="replace") as f:
            f.seek(0, os.SEEK_END)
            try:
                while True:
                    line = f.readline()
                    if line:
                        print(line, end="")
                    else:
                        time.sleep(0.3)
            except KeyboardInterrupt:
                pass
    else:
        # 使用系统 tail -f
        try:
            subprocess.run(["tail", "-f", str(log_file)])
        except KeyboardInterrupt:
            pass


def parse_args(argv: list[str]) -> tuple[str, bool, int, Path, float]:
    command = "toggle"
    debug = DEFAULT_DEBUG
    port = DEFAULT_PORT
    log_file = LOG_FILE
    wait_sec = DEFAULT_WAIT_SEC

    # 支持：command [--debug true/false] [--port N] [--log-file PATH] [--wait SEC]
    idx = 0
    while idx < len(argv):
        arg = argv[idx]
        if arg in ("toggle", "status", "logs"):
            command = arg
            idx += 1
            continue
        if arg == "--debug":
            if idx + 1 >= len(argv):
                print("[openclaw-toggle] 错误：--debug 需要 true/false")
                sys.exit(2)
            debug = argv[idx + 1].lower() == "true"
            idx += 2
            continue
        if arg == "--port":
            if idx + 1 >= len(argv):
                print("[openclaw-toggle] 错误：--port 需要端口号")
                sys.exit(2)
            try:
                port = int(argv[idx + 1])
            except ValueError:
                print("[openclaw-toggle] 错误：--port 需要整数")
                sys.exit(2)
            idx += 2
            continue
        if arg == "--log-file":
            if idx + 1 >= len(argv):
                print("[openclaw-toggle] 错误：--log-file 需要路径")
                sys.exit(2)
            log_file = Path(argv[idx + 1])
            idx += 2
            continue
        if arg == "--wait":
            if idx + 1 >= len(argv):
                print("[openclaw-toggle] 错误：--wait 需要秒数")
                sys.exit(2)
            try:
                wait_sec = float(argv[idx + 1])
            except ValueError:
                print("[openclaw-toggle] 错误：--wait 需要数字")
                sys.exit(2)
            if wait_sec <= 0:
                print("[openclaw-toggle] 错误：--wait 必须大于 0")
                sys.exit(2)
            idx += 2
            continue

        print(f"[openclaw-toggle] 错误：未知参数 {arg}")
        sys.exit(2)

    return command, debug, port, log_file.expanduser(), wait_sec


def main() -> None:
    command, debug, port, log_file, wait_sec = parse_args(sys.argv[1:])

    if command == "status":
        show_status(port)
        return
    if command == "logs":
        tail_logs(log_file)
        return

    if is_running(port):
        stop_gateway(port)
    else:
        start_gateway(port=port, debug=debug, log_file=log_file, wait_sec=wait_sec)


if __name__ == "__main__":
    main()
