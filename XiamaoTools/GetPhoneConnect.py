import subprocess
import re
import time


def run_cmd(cmd):
    try:
        result = subprocess.check_output(cmd, shell=True, encoding='utf-8')
        return result.strip()
    except subprocess.CalledProcessError as e:
        return ""


def check_usb_connection():
    devices = run_cmd("adb devices")
    print("ADB Devices:\n", devices)
    # 提取设备ID
    matches = re.findall(r'(\S+)\s+device', devices)
    return matches[0] if matches else None


def get_device_ip():
    # 获取 wlan0 下的 IP 地址
    ip_info = run_cmd("adb shell ip -f inet addr show wlan0")
    ip_match = re.search(r'inet\s+(\d+\.\d+\.\d+\.\d+)', ip_info)
    if ip_match:
        return ip_match.group(1)
    else:
        print("❌ 未获取到手机IP，请检查是否连接WIFI。")
        return None


def enable_tcpip():
    result = run_cmd("adb tcpip 5555")
    print(result)


def connect_wireless(ip):
    result = run_cmd(f"adb connect {ip}:5555")
    print(result)
    return "connected" in result or "already connected" in result


def check_final_connection(ip):
    devices = run_cmd("adb devices")
    print("\n最终ADB设备列表:\n", devices)
    return f"{ip}:5555" in devices


if __name__ == "__main__":
    print("📌 开始检查有线ADB连接...")
    device_id = check_usb_connection()
    if not device_id:
        print("❌ 未检测到有线ADB设备，请检查USB连接。")
        exit(1)

    print(f"✅ 检测到设备：{device_id}")
    print("📌 获取手机IP地址...")
    phone_ip = get_device_ip()
    if not phone_ip:
        exit(1)

    print(f"✅ 手机IP地址：{phone_ip}")
    print("📌 开启TCP/IP模式...")
    enable_tcpip()
    time.sleep(1)

    print("📌 尝试无线连接手机...")
    if connect_wireless(phone_ip):
        if check_final_connection(phone_ip):
            print(f"✅ 无线ADB连接成功：{phone_ip}:5555")
        else:
            print("❌ 无线连接失败，设备未出现在ADB列表中。")
    else:
        print("❌ 无法无线连接设备，请检查网络或防火墙设置。")
