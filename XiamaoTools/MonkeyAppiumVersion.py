"""Appium+ADB对Android应用进行稳定性测试,模拟用户点击、滑动、下拉刷新、返回等操作，该脚本可以结合Android-studio看日志更加方便"""
import json
import random
import subprocess
import time
from appium import webdriver
from appium.options.android import UiAutomator2Options
from selenium.common.exceptions import NoSuchElementException
from selenium.webdriver import ActionChains

# 🚀 关闭已有 Appium 进程
print("❌ 关闭 Appium 服务...")
subprocess.run("pkill -f appium", shell=True)

# 🚀 启动 Appium
print("🚀 启动 Appium 服务...")
subprocess.Popen("appium --allow-insecure=adb_shell", shell=True, executable="/bin/bash",
                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

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


# 🎯 获取设备 ID
def get_device_id():
    result = subprocess.run("adb devices", shell=True, capture_output=True, text=True).stdout
    devices = [line.split()[0] for line in result.splitlines() if "device" in line and "List" not in line]
    return devices[0] if devices else None


# 🎯 获取 `APP_ACTIVITY`
def get_app_activity(package_name):
    print(f"🚀 启动 APP: {package_name}")
    subprocess.run(f"adb shell monkey -p {package_name} -c android.intent.category.LAUNCHER 1 > /dev/null 2>&1",
                   shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    time.sleep(3)
    output = subprocess.run(f"adb shell dumpsys window | grep mCurrentFocus",
                            shell=True, capture_output=True, text=True).stdout.strip()

    if not output:
        print("❌ APP Activity 获取失败")
        exit(1)

    activity_name = output.split()[-1].split("}")[0].split("/")[-1]
    app_activity = f"{package_name}/{activity_name}"
    print(f"✅ 获取 APP_ACTIVITY: {app_activity}")

    return app_activity


# todo 确保APP一直在前台（20% 概率强制重启，防止进入native广告页面，无法退出）
def bring_app_to_foreground(package_name):
    print("🔍 检测 APP 是否在前台...")
    current_package = subprocess.run(f"adb shell dumpsys window | grep mCurrentFocus",
                                     shell=True, capture_output=True, text=True).stdout.strip()

    print(f"📌 当前窗口信息: {current_package}")

    if package_name not in current_package:
        print("🚨 APP 在后台广告页面或崩溃，执行强制重启...")
        force_restart_app(package_name)
    else:
        if random.random() < 0.2:
            print("🔄 触发 20% 概率强制重启")
            force_restart_app(package_name)
        else:
            print("✅ APP 在前台，无需重启")


def force_restart_app(package_name):
    """ 强制停止并重新启动 APP """
    stop_command = f"adb shell am force-stop {package_name}"
    print(f"📌 执行命令: {stop_command}")
    subprocess.run(stop_command, shell=True)
    time.sleep(2)

    start_command = f"adb shell monkey -p {package_name} -c android.intent.category.LAUNCHER 1 > /dev/null 2>&1"
    print(f"📌 重新启动 APP: {start_command}")
    subprocess.run(start_command, shell=True)
    time.sleep(3)


# 🎯 处理广告
# def skip_splash_ads(driver):
#     try:
#         time.sleep(3)
#         skip_button = driver.find_element("xpath", "//*[contains(@text, '跳过')]")
#         skip_button.click()
#         print("✅ 成功跳过广告")
#     except:
#         print("📌 无广告")
# 处理开屏广告
def skip_splash_ads(driver):
    # 定义可能出现的跳过或继续相关的文字列表
    skip_keywords = ["跳过", "继续使用应用"]
    try:
        time.sleep(3)  # 等待 3 秒，确保页面加载
        # 使用 XPath 查找包含列表中任一关键字的元素
        for keyword in skip_keywords:
            try:
                skip_button = driver.find_element("xpath", f"//*[contains(@text, '{keyword}')]")
                skip_button.click()
                print(f"✅ 成功点击含有 '{keyword}' 的按钮")
                return  # 点击成功后退出函数，避免继续循环
            except NoSuchElementException:
                continue  # 当前关键词未找到，继续尝试下一个
        print("📌 无广告")  # 所有关键词都未找到，认为是无广告
    except Exception as e:
        print(f"📌 操作失败: {str(e)}")  # 捕获其他异常并输出详细信息


# 🎯 随机点击
def random_touch(driver, width, height):
    x, y = random.randint(100, width - 100), random.randint(100, height - 100)
    print(f"📍 随机点击: ({x}, {y})")

    actions = ActionChains(driver)
    actions.w3c_actions.pointer_action.move_to_location(x, y)
    actions.w3c_actions.pointer_action.pointer_down()
    actions.w3c_actions.pointer_action.pointer_up()
    actions.perform()


# 🎯 随机滑动
def random_swipe(driver, width, height):
    start_x, start_y = random.randint(100, width - 100), random.randint(100, height - 100)
    end_x, end_y = random.randint(100, width - 100), random.randint(100, height - 100)

    print(f"📍 滑动: ({start_x}, {start_y}) → ({end_x}, {end_y})")

    actions = ActionChains(driver)
    actions.w3c_actions.pointer_action.move_to_location(start_x, start_y)
    actions.w3c_actions.pointer_action.pointer_down()
    actions.w3c_actions.pointer_action.move_to_location(end_x, end_y)
    actions.w3c_actions.pointer_action.release()
    actions.perform()


# 🎯 下拉刷新
def pull_to_refresh(driver, width, height):
    start_x, start_y = width // 2, height // 3
    end_y = height // 2 + height // 3

    print(f"🔄 下拉刷新: ({start_x}, {start_y}) → ({start_x}, {end_y})")

    actions = ActionChains(driver)
    actions.w3c_actions.pointer_action.move_to_location(start_x, start_y)
    actions.w3c_actions.pointer_action.pointer_down()
    actions.w3c_actions.pointer_action.move_to_location(start_x, end_y)
    actions.w3c_actions.pointer_action.release()
    actions.perform()

    time.sleep(2)



# 🎯 返回操作
def perform_back_action(driver):
    print("🔙 执行返回操作")
    driver.back()
    time.sleep(2)


# 🎯 运行稳定性测试
def stability_test(package_name="com.hotpotgames.happysave.global"):
    device_id = get_device_id()
    app_activity = get_app_activity(package_name)

    caps = UiAutomator2Options()
    caps.platform_name = "Android"
    caps.device_name = device_id
    caps.app_package = package_name
    caps.app_activity = app_activity
    caps.automation_name = "UiAutomator2"
    caps.no_reset = True

    driver = webdriver.Remote(command_executor="http://127.0.0.1:4723", options=caps)

    # 📌 获取并存储屏幕大小
    screen_size = driver.get_window_size()
    width, height = screen_size["width"], screen_size["height"]
    print(f"📏 设备屏幕大小: {width}x{height}")

    skip_splash_ads(driver)

    start_time = time.time()

    while time.time() - start_time < TEST_DURATION:
        bring_app_to_foreground(package_name)

        # 🎯 每次按权重随机选择一个操作
        action = random.choices(["click", "swipe", "refresh", "back"], weights=[40, 20, 20, 20])[0]

        if action == "click":
            random_touch(driver, width, height)
        elif action == "swipe":
            random_swipe(driver, width, height)
        elif action == "refresh":
            pull_to_refresh(driver, width, height)
        elif action == "back":
            perform_back_action(driver)

        time.sleep(random.uniform(1, 2))

    driver.quit()


if __name__ == '__main__':
    # 运行测试时长，单位是秒
    TEST_DURATION = 600
    print("🚀 开始稳定性测试 ...")
    # TODO stability_test方法需要传递app包名，不传默认用测试包名"com.hotpotgames.happysave.global"
    stability_test()
    print("✅ 测试完成")
