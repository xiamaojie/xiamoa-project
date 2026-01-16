import uiautomator2 as u2
import time
import platform
import subprocess
import re


def get_ip_addresses():
    system = platform.system()

    if system == "Windows":
        cmd = "ipconfig"
        pattern = r"IPv4 地址[.\s]*: ([\d.]+)"
    elif system == "Darwin":  # macOS
        cmd = "ifconfig"
        pattern = r"inet (\d+\.\d+\.\d+\.\d+)"
    else:
        return "Unsupported OS"

    try:
        output = subprocess.check_output(cmd, shell=True, text=True)
        match = re.findall(pattern, output)

        if match:
            # 过滤掉 127.0.0.1
            ip_list = [ip for ip in match if ip != "127.0.0.1"]
            if not ip_list:
                return "No valid IP found"

            # 过滤出以 192. 开头的 IP
            local_ips = [ip for ip in ip_list if ip.startswith("192.")]

            if local_ips:
                return local_ips
            else:
                return "检测到 VPN 连接，请关闭 VPN 后重试！"
        else:
            return "No IP found"
    except Exception as e:
        return f"Error: {e}"



# 关键词列表，可拓展使用
connection_keywords = [
    "已连接",
    "connected",
    # 扩展关键词示例：
    # "connected to wifi", "网络已连接"
]

def is_connected_text(text):
    """判断文本是否包含关键词（英文忽略大小写）"""
    for keyword in connection_keywords:
        if keyword.lower() in text.lower():
            return True
    return False

# 1. 杀掉设置页面
print("🛠️ 正在关闭设置页面...")
subprocess.run(["adb", "shell", "am", "force-stop", "com.android.settings"])
time.sleep(1)

# 2. 打开Wi-Fi设置页
print("🚀 启动 Wi-Fi 设置页...")
subprocess.run(["adb", "shell", "am", "start", "-a", "android.settings.WIFI_SETTINGS"])
time.sleep(2)

# 3. 连接设备
d = u2.connect()

# 4. 查找 Wi-Fi 节点并点击
try:
    print("🔍 查找已连接的Wi-Fi...")
    nodes = d.xpath('//*').all()
    found = False
    for node in nodes:
        text = node.attrib.get("text", "")
        if is_connected_text(text):
            print(f"✅ 匹配到节点: '{text}'，点击...")
            node.click()
            found = True
            break

    if not found:
        print("⚠️ 未找到包含连接状态的 Wi-Fi 节点。")
        exit()

except Exception as e:
    print(f"❌ 查找Wi-Fi节点出错：{e}")
    exit()

# 5. 点击“修改”按钮
time.sleep(1.5)  # 等待Wi-Fi详情页面加载
print("🛠️ 查找并点击 ‘修改’ 按钮...")
modify_button = d.xpath('//*[@content-desc="修改"]').get(timeout=5)
modify_button.click()
time.sleep(1)
# 点击高级选项
d.xpath('//*[@text="高级选项"]').get(timeout=5).click()
time.sleep(1)
# 点击代理无
d.xpath('//*[@text="无"]').get(timeout=5).click()
time.sleep(1)
# 点击代理为手动模式
d.xpath('//*[@text="手动"]').get(timeout=5).click()
time.sleep(1)
# 输入电脑ip地址
ip_address = get_ip_addresses()[0]
d.xpath('//*[@text="proxy.example.com"]').click()
d.send_keys(ip_address,clear=True)
time.sleep(0.5)
# 输入charles端口号
d.xpath('//*[@text="8080"]').click()
d.send_keys("8888",clear=True)
time.sleep(0.5)
d.xpath('//*[@text="保存"]').get(timeout=5).click()





