#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
OpenClaw Gateway 开关脚本（兼容 macOS / Windows）

功能：
- toggle：运行中则关闭；未运行则启动
- start：仅启动
- stop：仅关闭
- status：查看状态
- logs：追踪日志（仅 debug=true 启动时有意义）

用法：
  python Openclaw_Status_Switch.py
  python Openclaw_Status_Switch.py toggle
  python Openclaw_Status_Switch.py start
  python Openclaw_Status_Switch.py stop
  python Openclaw_Status_Switch.py status
  python Openclaw_Status_Switch.py logs
  python Openclaw_Status_Switch.py start --debug true
  python Openclaw_Status_Switch.py toggle --wait 10
  python Openclaw_Status_Switch.py start --port 18789
  python Openclaw_Status_Switch.py start --log-file ./gateway.out

环境变量：
  OPENCLAW_PORT=18789
  OPENCLAW_LOG_FILE=./gateway.out
"""

import os
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional, Tuple


DEFAULT_DEBUG = False
DEFAULT_PORT = int(os.environ.get("OPENCLAW_PORT", "18789"))
DEFAULT_WAIT_SEC = 10.0


def default_log_file() -> Path:
    env = os.environ.get("OPENCLAW_LOG_FILE")
    if env:
        return Path(env).expanduser()
    return Path.cwd() / "gateway.out"


LOG_FILE = default_log_file()


def print_msg(msg: str) -> None:
    print(f"[openclaw-toggle] {msg}")


def run_cmd_quiet(cmd: list[str]) -> Tuple[int, str]:
    try:
        p = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        return p.returncode, p.stdout or ""
    except FileNotFoundError:
        return 127, f"未找到命令：{cmd[0]}"
    except Exception as e:
        return 1, str(e)


def can_listen(port: int) -> bool:
    """端口空闲则 True。"""
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
    """端口被监听则 True。"""
    return not can_listen(port)


def wait_port_state(port: int, expected_running: bool, timeout_sec: float) -> bool:
    deadline = time.monotonic() + timeout_sec
    while time.monotonic() < deadline:
        running = is_running(port)
        if running == expected_running:
            return True
        time.sleep(0.2)
    return is_running(port) == expected_running


def find_pid_by_port(port: int) -> Optional[int]:
    """根据监听端口查找 PID。"""
    if os.name != "nt":
        try:
            out = subprocess.check_output(
                ["lsof", "-nP", f"-iTCP:{port}", "-sTCP:LISTEN"],
                stderr=subprocess.DEVNULL,
                text=True,
            )
            lines = [ln.strip() for ln in out.splitlines() if ln.strip()]
            if len(lines) >= 2:
                for line in lines[1:]:
                    parts = line.split()
                    if len(parts) >= 2 and parts[1].isdigit():
                        return int(parts[1])
        except (subprocess.CalledProcessError, FileNotFoundError, OSError):
            return None
        return None

    try:
        out = subprocess.check_output(
            ["cmd", "/c", f'netstat -ano | findstr :{port} | findstr LISTENING'],
            stderr=subprocess.DEVNULL,
            text=True,
        )
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


def find_pids_by_name(name_keyword: str) -> list[int]:
    """按进程名关键字查找 PID，用于兜底。"""
    pids: list[int] = []

    if os.name == "nt":
        rc, out = run_cmd_quiet(["cmd", "/c", "tasklist"])
        if rc == 0:
            for line in out.splitlines():
                if name_keyword.lower() in line.lower():
                    parts = line.split()
                    if len(parts) >= 2 and parts[1].isdigit():
                        pids.append(int(parts[1]))
        return pids

    rc, out = run_cmd_quiet(["ps", "aux"])
    if rc == 0:
        for line in out.splitlines():
            if name_keyword in line and "grep" not in line:
                parts = line.split()
                if len(parts) >= 2 and parts[1].isdigit():
                    pids.append(int(parts[1]))
    return pids


def is_macos() -> bool:
    return sys.platform == "darwin"


def start_gateway(port: int, debug: bool, log_file: Path, wait_sec: float) -> None:
    if is_running(port):
        pid = find_pid_by_port(port)
        print_msg(f"gateway 已在运行：port={port}, pid={pid or 'unknown'}")
        return

    log_file.parent.mkdir(parents=True, exist_ok=True)

    if debug:
        stdout_target = open(log_file, "w", encoding="utf-8", errors="replace")
        stderr_target = subprocess.STDOUT
        cmd = ["openclaw", "gateway", "--verbose"]
        print_msg(f"正在启动 gateway（debug=true），日志：{log_file}")
    else:
        stdout_target = subprocess.DEVNULL
        stderr_target = subprocess.DEVNULL
        cmd = ["openclaw", "gateway"]
        print_msg("正在启动 gateway（debug=false，静默）。")

    print_msg(f"启动命令：{' '.join(cmd)}")

    if os.name == "nt":
        creation_flags = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS
        start_new_session = False
        close_fds = False
    else:
        creation_flags = 0
        start_new_session = True
        close_fds = True

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
            close_fds=close_fds,
            env=env,
        )
    except FileNotFoundError:
        print_msg("错误：找不到 openclaw 命令。请确认已安装并在 PATH 中。")
        sys.exit(127)

    if wait_port_state(port, True, wait_sec):
        print_msg(f"启动成功，监听 127.0.0.1:{port}")
        print_msg(f"访问地址：http://127.0.0.1:{port}/")
        if debug:
            print_msg(f"查看日志：python {Path(__file__).name} logs")
    else:
        print_msg("警告：启动后未检测到端口监听，可能启动失败。")
        print_msg("建议手动前台执行：openclaw gateway --verbose")
        sys.exit(1)


def try_openclaw_stop() -> None:
    stop_cmd = ["openclaw", "gateway", "stop"]
    print_msg(f"停止命令：{' '.join(stop_cmd)}")
    rc, out = run_cmd_quiet(stop_cmd)
    print_msg(f"gateway stop 返回码：{rc}")
    if out.strip():
        print(out.strip())


def try_launchctl_bootout() -> None:
    if not is_macos():
        return
    uid = os.getuid()
    cmd = ["launchctl", "bootout", f"gui/{uid}/ai.openclaw.gateway"]
    print_msg(f"尝试停止 launchctl 服务：{' '.join(cmd)}")
    rc, out = run_cmd_quiet(cmd)

    # rc=0：成功
    # rc=3：通常表示已经不存在 / 已经被停掉，可视为可接受
    if rc == 0:
        print_msg("launchctl 服务已停止。")
    elif rc == 3:
        print_msg("launchctl 服务已不存在或已提前停止。")
    else:
        print_msg(f"launchctl bootout 返回码：{rc}")

    if out.strip():
        print(out.strip())


def kill_pid(pid: int) -> bool:
    try:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(pid), "/T"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            time.sleep(1.0)
            subprocess.run(
                ["taskkill", "/F", "/PID", str(pid), "/T"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return True

        os.kill(pid, signal.SIGTERM)
        time.sleep(1.0)
        try:
            os.kill(pid, 0)
            os.kill(pid, signal.SIGKILL)
        except OSError:
            pass
        return True
    except Exception as e:
        print_msg(f"结束进程失败 pid={pid}: {e}")
        return False


def stop_gateway(port: int) -> None:
    if not is_running(port):
        print_msg(f"gateway 未运行（port={port}）。")
        return

    first_pid = find_pid_by_port(port)
    print_msg(f"准备停止 gateway：port={port}, pid={first_pid or 'unknown'}")

    # 1. 优雅停止
    try_openclaw_stop()
    if wait_port_state(port, False, 4.0):
        print_msg("已停止（通过 openclaw gateway stop）。")
        return

    # 2. macOS service 兜底
    try_launchctl_bootout()
    if wait_port_state(port, False, 4.0):
        print_msg("已停止（通过 launchctl bootout）。")
        return

    # 3. 按端口查 PID 再杀
    pid = find_pid_by_port(port)
    if pid is not None:
        print_msg(f"端口仍被占用，尝试结束监听进程 pid={pid}")
        if kill_pid(pid) and wait_port_state(port, False, 4.0):
            print_msg("已停止（通过 PID 杀进程）。")
            return

    # 4. 按进程名兜底
    fallback_pids = find_pids_by_name("openclaw-gateway")
    if fallback_pids:
        print_msg(f"尝试按进程名兜底结束：{fallback_pids}")
        for p in fallback_pids:
            kill_pid(p)
        if wait_port_state(port, False, 4.0):
            print_msg("已停止（通过进程名兜底）。")
            return

    # 5. 最终失败
    still_pid = find_pid_by_port(port)
    print_msg("停止失败：端口仍被占用。")
    print_msg(f"当前端口占用 pid={still_pid or 'unknown'}")
    sys.exit(1)


def show_status(port: int) -> None:
    if is_running(port):
        pid = find_pid_by_port(port)
        print(f"运行中 port={port} pid={pid or 'unknown'}")
    else:
        print(f"已停止 port={port}")


def tail_logs(log_file: Path) -> None:
    if not log_file.exists():
        print_msg(f"未找到日志文件：{log_file}")
        print_msg("使用 --debug true 启动以生成日志。")
        return

    print_msg(f"正在追踪日志 {log_file}（Ctrl+C 退出）")
    if os.name == "nt":
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

    idx = 0
    while idx < len(argv):
        arg = argv[idx]

        if arg in ("toggle", "start", "stop", "status", "logs"):
            command = arg
            idx += 1
            continue

        if arg == "--debug":
            if idx + 1 >= len(argv):
                print_msg("错误：--debug 需要 true/false")
                sys.exit(2)
            debug = argv[idx + 1].lower() == "true"
            idx += 2
            continue

        if arg == "--port":
            if idx + 1 >= len(argv):
                print_msg("错误：--port 需要端口号")
                sys.exit(2)
            try:
                port = int(argv[idx + 1])
            except ValueError:
                print_msg("错误：--port 需要整数")
                sys.exit(2)
            idx += 2
            continue

        if arg == "--log-file":
            if idx + 1 >= len(argv):
                print_msg("错误：--log-file 需要路径")
                sys.exit(2)
            log_file = Path(argv[idx + 1]).expanduser()
            idx += 2
            continue

        if arg == "--wait":
            if idx + 1 >= len(argv):
                print_msg("错误：--wait 需要秒数")
                sys.exit(2)
            try:
                wait_sec = float(argv[idx + 1])
            except ValueError:
                print_msg("错误：--wait 需要数字")
                sys.exit(2)
            if wait_sec <= 0:
                print_msg("错误：--wait 必须大于 0")
                sys.exit(2)
            idx += 2
            continue

        print_msg(f"错误：未知参数 {arg}")
        sys.exit(2)

    return command, debug, port, log_file, wait_sec


def main() -> None:
    command, debug, port, log_file, wait_sec = parse_args(sys.argv[1:])

    if command == "status":
        show_status(port)
        return

    if command == "logs":
        tail_logs(log_file)
        return

    if command == "start":
        start_gateway(port=port, debug=debug, log_file=log_file, wait_sec=wait_sec)
        return

    if command == "stop":
        stop_gateway(port=port)
        return

    # toggle
    if is_running(port):
        stop_gateway(port=port)
    else:
        start_gateway(port=port, debug=debug, log_file=log_file, wait_sec=wait_sec)


if __name__ == "__main__":
    main()