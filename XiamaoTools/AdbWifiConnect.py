import subprocess
import re
import time

def run_cmd(cmd):
    """ 执行 shell 命令并返回输出 """
    result = subprocess.run(cmd, capture_output=True, text=True)
    return result.stdout.strip()

def get_adb_devices():
    """ 获取已连接设备列表 (USB & 无线) """
    devices_output = run_cmd(["adb", "devices"]).split("\n")[1:]
    devices = [line.split()[0] for line in devices_output if line.strip() and "device" in line]

    # 获取无线设备（形如 IP:PORT）
    wireless_devices = [d for d in devices if ":" in d]
    wired_devices = [d for d in devices if ":" not in d]

    return wired_devices, wireless_devices

def get_device_ip(device):
    """ 获取设备的 Wi-Fi IP 地址（解析 wlan0 接口） """
    ip_info = run_cmd(["adb", "-s", device, "shell", "ip addr show wlan0"])
    match = re.search(r'inet (\d+\.\d+\.\d+\.\d+)/', ip_info)
    return match.group(1) if match else None

def connect_adb_wireless(device, ports=[5555, 5585]):
    """ 连接 ADB 无线（尝试多个端口） """
    _, wireless_devices = get_adb_devices()

    # 📌 **如果无线 ADB 已连接，则直接使用**
    if wireless_devices:
        print(f"✅ 无线 ADB 设备已连接: {wireless_devices[0]}")
        return wireless_devices[0]

    for port in ports:
        print(f"🔄 设备 {device} 尝试开启 ADB TCPIP 端口 {port} ...")
        run_cmd(["adb", "-s", device, "tcpip", str(port)])
        time.sleep(3)

        ip_address = get_device_ip(device)
        if not ip_address:
            print(f"❌ 无法获取设备 {device} 的 IP")
            continue

        wireless_device = f"{ip_address}:{port}"
        print(f"🔗 尝试连接无线 ADB: adb connect {wireless_device}")

        connect_result = run_cmd(["adb", "connect", wireless_device])

        if "connected" in connect_result or "already connected" in connect_result:
            print(f"✅ 成功无线连接至: {wireless_device}")
            return wireless_device
        else:
            print(f"⚠️ 无线 ADB 连接失败: {connect_result}")

    print("⚠️ 所有端口均无法连接无线 ADB，回退 USB")
    return None

if __name__ == "__main__":
    wired_devices, wireless_devices = get_adb_devices()

    if wireless_devices:
        selected_device = wireless_devices[0]
    elif wired_devices:
        selected_device = connect_adb_wireless(wired_devices[0])
    else:
        print("😢 没有检测到任何 ADB 设备")
        selected_device = None

    if selected_device:
        print(f"✅ 使用设备: {selected_device}")
        print(f"🔷 你可以使用命令: adb -s {selected_device} shell")
    else:
        print("❌ 无线 & USB 连接失败，请检查设备")