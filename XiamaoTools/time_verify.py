import subprocess
import re
from datetime import datetime
import ntplib


def check_time_diff(max_diff_seconds=60):
    """
    从ADB获取手机时间、从NTP获取服务器时间并进行对比。
    输出格式如下：
    成功从 NTP 服务器获取时间: pool.ntp.org
    手机本地时间: 2025-11-27 10:15:30
    NTP服务器时间: 2025-11-27 10:15:28.284071
    时间差（秒）: 1.715929
    ✔ 时间一致（差值在1分钟以内）
    """

    # ---------- 1. 读取手机时间 ----------
    output = subprocess.check_output(
        ['adb', 'shell', "date +'%Y-%m-%d %H:%M:%S %Z'"],
        text=True
    ).strip()

    match = re.search(r"(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2})", output)
    if not match:
        raise ValueError(f"无法从ADB输出中提取时间: {output}")

    device_dt = datetime.strptime(match.group(1), "%Y-%m-%d %H:%M:%S")

    # ---------- 2. 获取 NTP 服务器时间 ----------
    NTP_SERVERS = [
        # 公共池
        "pool.ntp.org",
        "0.pool.ntp.org",
        "1.pool.ntp.org",
        "2.pool.ntp.org",
        "3.pool.ntp.org",
        "cn.pool.ntp.org",
        # 大厂节点
        "time.google.com",
        "time.cloudflare.com",
        "time.windows.com",
        "time.apple.com",
        # 国内稳定源
        "ntp.aliyun.com",
        "ntp1.aliyun.com",
        "time1.cloud.tencent.com",
        "time2.cloud.tencent.com",
        "ntp.ntsc.ac.cn",
    ]

    client = ntplib.NTPClient()
    server_dt = None
    last_error = None

    for host in NTP_SERVERS:
        try:
            response = client.request(host, version=3, timeout=2)
            server_dt = datetime.fromtimestamp(response.tx_time)
            print(f"成功从 NTP 服务器获取时间: {host}")
            break
        except Exception as e:
            last_error = e
            print(f"NTP 服务器不可用: {host}，原因: {e}")

    if server_dt is None:
        raise RuntimeError(f"所有 NTP 服务器均不可用，最后错误：{last_error}")

    # ---------- 3. 输出两者时间对比 ----------
    print("手机本地时间:", device_dt)
    print("NTP服务器时间:", server_dt)

    diff = abs((device_dt - server_dt).total_seconds())
    print("时间差（秒）:", diff)

    if diff <= max_diff_seconds:
        print("✔ 时间一致（差值在1分钟以内）")
        return True
    else:
        print("✘ 时间不一致（超过1分钟）")
        return False


# main
if __name__ == "__main__":
    check_time_diff()
