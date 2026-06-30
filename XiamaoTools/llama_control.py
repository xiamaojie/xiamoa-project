#!/usr/bin/env python3
# 阿里本地微型模型
import os
import signal
import subprocess
import time
from pathlib import Path

PORT = 9000

LLAMA_SERVER = Path("~/llama.cpp/build/bin/llama-server").expanduser()
MODEL = Path("~/llama.cpp/models/qwen1_5-1_8b-chat-q4_k_m.gguf").expanduser()

CMD = [
    str(LLAMA_SERVER),
    "-m", str(MODEL),
    "-ngl", "99",
    "-c", "4096",
    "--port", str(PORT),
]

def pids_listening_on_port():
    try:
        out = subprocess.check_output(
            ["sh", "-lc", f"lsof -nP -iTCP:{PORT} -sTCP:LISTEN | tail -n +2 | awk '{{print $2}}'"],
            text=True
        ).strip()
    except subprocess.CalledProcessError:
        return []

    if not out:
        return []
    return sorted({int(x) for x in out.split() if x.isdigit()})

def stop_server():
    pids = pids_listening_on_port()
    if not pids:
        print("Server not running.")
        return

    print(f"Stopping {pids}")
    for pid in pids:
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass

    time.sleep(1)

    # force kill if still running
    for pid in pids_listening_on_port():
        os.kill(pid, signal.SIGKILL)

    print("Stopped.")

def start_server():
    if not LLAMA_SERVER.exists():
        print("llama-server not found")
        return

    if not MODEL.exists():
        print("model not found")
        return

    subprocess.Popen(
        CMD,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True
    )

    time.sleep(1)
    print(f"Started http://localhost:{PORT}")

def main():
    if pids_listening_on_port():
        stop_server()
    else:
        start_server()

if __name__ == "__main__":
    main()