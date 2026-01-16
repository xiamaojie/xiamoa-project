import json
import os
import subprocess
import sys

# 屏蔽控制台NotOpenSSLWarning警告
sys.stderr = open(os.devnull, 'w')
import time

from appium import webdriver
from appium.options.android import UiAutomator2Options
from appium.webdriver.common.appiumby import AppiumBy
from selenium.webdriver.common.actions.action_builder import ActionBuilder
from selenium.webdriver.common.actions.pointer_input import PointerInput
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

# 🚀 关闭已有 Appium 进程
print("❌ 关闭Appium 服务...")
subprocess.run("pkill -f appium", shell=True)

# 🚀 启动 Appium
print("🚀 启动 Appium 服务...")
subprocess.Popen("appium --allow-insecure=adb_shell", shell=True, executable="/bin/bash", stdout=subprocess.DEVNULL,
                 stderr=subprocess.DEVNULL)

time.sleep(2)

# 🚀 检查 Appium 服务器状态
try:
    result_output = subprocess.run("curl -s http://localhost:4723/status", shell=True, capture_output=True, text=True)
    appium_status = json.loads(result_output.stdout)

    if appium_status.get("value", {}).get("ready") is True:
        print("✅ Appium 服务已成功启动！")
    else:
        print("❌ Appium 服务未正常启动，请检查！")
        exit(1)

except Exception as e:
    print(f"❌ 连接 Appium 失败！错误信息: {str(e)}")
    exit(1)


# 🚀 获取当前系统语言
def get_current_locale():
    cmd = "adb shell getprop persist.sys.locale"
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    return result.stdout.strip()


# 记录初始语言
before_language_type = get_current_locale()

# 🚀 语言映射
LANGUAGE_NAMES = {
    "zh-Hans-CN": "中文",
    "en-US": "英语"
}

# 🚀 确定目标语言
current_language = get_current_locale()
current_language_name = LANGUAGE_NAMES.get(current_language, "未知")
print(f"📢 当前系统语言: {current_language} ({current_language_name})")

if current_language == "zh-Hans-CN":
    target_language = "English (United States)"
    target_language_name = "英语"
    confirm_keywords = ["更改", "确定", "确认"]
elif current_language == "en-US":
    target_language = "简体中文（中国）"
    target_language_name = "中文"
    confirm_keywords = ["change", "ok", "confirm", "apply"]
else:
    print("⚠️ 未知系统语言，或检查手机设备未连接问题，脚本终止")
    exit(1)

print(f"🎯 目标语言: {target_language} ({target_language_name})")

# 🚀 关闭Android设置
subprocess.run("adb shell am force-stop com.android.settings", shell=True)
time.sleep(1)

# 🚀 启动语言设置页面
subprocess.run("adb shell am start -a android.settings.LOCALE_SETTINGS | grep -v 'Starting:'", shell=True)
time.sleep(1)

# 关闭手机自动旋转功能，强制设置为竖屏，减少因手机横屏导致的切换失败
subprocess.run("adb shell 'settings put system accelerometer_rotation 0; settings put system user_rotation 0'",
               shell=True)

# 🚀 连接 Appium
options = UiAutomator2Options()
options.platform_name = "Android"
options.device_name = "Pixel_6"
options.automation_name = "uiautomator2"
options.no_reset = True

driver = webdriver.Remote("http://localhost:4723", options=options)
wait = WebDriverWait(driver, 5)
time.sleep(2)
print("✅ 成功连接 Appium WebDriver！")

# 🚀 获取语言列表
language_elements = driver.find_elements(AppiumBy.ID, "com.android.settings:id/label")
drag_handles = driver.find_elements(AppiumBy.ID, "com.android.settings:id/dragHandle")

# 📝 打印语言列表
print("📝 设备语言列表:")
for idx, lang in enumerate(language_elements, start=1):
    print(f"{idx}. {lang.text}")

# 🏷 **找到目标语言并拖拽**
try:
    target_lang = next(lang for lang in language_elements if target_language in lang.text)
    target_drag = drag_handles[language_elements.index(target_lang)]

    # 获取屏幕大小
    screen_size = driver.get_window_size()
    screen_height = screen_size["height"]

    # 计算拖动起点 (x, y) 和目标位置
    start_x = target_drag.location["x"] + target_drag.size["width"] // 2
    start_y = target_drag.location["y"] + target_drag.size["height"] // 2
    end_y = start_y - int(screen_height * 0.5)  # 拖拽 50% 屏幕高度

    print(f"⬆ 拖拽 '{target_language}' 从 ({start_x}, {start_y}) 到 ({start_x}, {end_y})...")

    # ⭐**🚀 修复 PointerInput 问题**
    pointer = PointerInput("touch", "finger")  # ← 修复
    actions = ActionBuilder(driver, mouse=pointer)
    actions.pointer_action.move_to_location(start_x, start_y)
    actions.pointer_action.pointer_down()
    actions.pointer_action.move_to_location(start_x, end_y)
    actions.pointer_action.pointer_up()
    actions.perform()

    time.sleep(2)

    # 🚀 **等待 "确认弹窗"**
    print("🔍 等待确认弹窗可见...")
    wait.until(EC.presence_of_element_located((AppiumBy.CLASS_NAME, "android.widget.Button")))

    # 🚀 **查找并点击确认按钮**
    buttons = driver.find_elements(AppiumBy.CLASS_NAME, "android.widget.Button")
    for btn in buttons:
        btn_text = btn.text.strip().lower()
        if any(keyword.lower() in btn_text for keyword in confirm_keywords):
            print(f"✅ 找到确认按钮 `{btn.text}`，立即点击！")
            btn.click()
            break
    else:
        print("❌ 未找到匹配的确认按钮！")

except Exception as e:
    print(f"❌ 发生错误: {str(e)}")
    driver.quit()
    exit(1)

# **检查语言是否切换成功**
after_language_type = get_current_locale()
if before_language_type != after_language_type:
    print(f"🌍 语言切换成功！当前语言: {current_language_name} → 目标语言: {target_language_name}")
else:
    print("语言切换失败")

# **清理 & 退出**
driver.quit()
subprocess.run("pkill -f appium", shell=True)
print("✅ 关闭 Appium 进程！")
subprocess.run("pkill -f python", shell=True)
print("✅ 关闭 Python 进程...")
