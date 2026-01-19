#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
测试用例: test_select_live_earth_map
生成时间: 2026-01-12 18:41:06

定位策略（按优先级）：
1. ID 定位 - 最稳定，跨设备兼容
2. 文本定位 - 稳定，跨设备兼容
3. 百分比定位 - 跨分辨率兼容（坐标自动转换）
"""
import time
import uiautomator2 as u2

PACKAGE_NAME = "com.earth.explorer.launcher.live.map.satelliteview"

# === 配置（根据 App 情况调整）===
LAUNCH_WAIT = 10       # 启动后等待时间（秒），开屏广告较长可调高
CLOSE_AD_ON_LAUNCH = True  # 是否尝试关闭启动广告
AD_CLOSE_KEYWORDS = ['关闭', '跳过', 'Skip', 'Close', '×', 'X', '我知道了', '稍后再说']


def log(msg):
    """统一打印日志，实时刷新"""
    print(msg, flush=True)


def smart_wait(d, seconds=1):
    """等待页面稳定"""
    time.sleep(seconds)


def close_ad_if_exists(d, quick=False):
    """尝试关闭广告弹窗（quick=True 时只检查常见的）"""
    keywords = AD_CLOSE_KEYWORDS[:3] if quick else AD_CLOSE_KEYWORDS
    for keyword in keywords:
        elem = d(textContains=keyword)
        if elem.exists(timeout=0.3):  # 缩短超时
            try:
                elem.click()
                print(f'  📢 关闭广告: {keyword}')
                time.sleep(0.3)
                return True
            except:
                pass
    # 开屏广告特定文案
    ad_close_texts = ['关闭广告并继续打开', '关闭广告并继续', '关闭广告']
    for txt in ad_close_texts:
        elem = d(textContains=txt)
        if elem.exists(timeout=0.3):
            try:
                elem.click()
                print(f'  📢 关闭开屏广告: {txt}')
                time.sleep(0.3)
                return True
            except:
                pass
    return False


def safe_click(d, selector, timeout=3):
    """安全点击（带等待）"""
    try:
        if selector.exists(timeout=timeout):
            selector.click()
            return True
        return False
    except Exception as e:
        print(f'  ⚠️ 点击失败: {e}')
        return False


def assert_exists(selector, name, timeout=3):
    """断言元素存在"""
    if not selector.exists(timeout=timeout):
        raise AssertionError(f"未找到元素: {name}")


def wait_until_exists(selector_list, name, timeout=5, interval=0.5):
    """循环等待任意一个选择器出现"""
    end = time.time() + timeout
    while time.time() < end:
        for sel in selector_list:
            if sel.exists(timeout=0.01):
                return sel
        time.sleep(interval)
    return None


def click_by_percent(d, x_percent, y_percent):
    """
    百分比点击（跨分辨率兼容）
    
    原理：屏幕左上角 (0%, 0%)，右下角 (100%, 100%)
    优势：同样的百分比在不同分辨率设备上都能点到相同相对位置
    """
    info = d.info
    width = info.get('displayWidth', 0)
    height = info.get('displayHeight', 0)
    x = int(width * x_percent / 100)
    y = int(height * y_percent / 100)
    d.click(x, y)
    return True


def test_main():
    # 连接设备
    d = u2.connect()
    d.implicitly_wait(10)  # 设置全局等待

    # 杀进程确保干净启动
    log(f"停止应用: {PACKAGE_NAME}")
    try:
        d.app_stop(PACKAGE_NAME)
    except Exception as e:
        log(f"停止应用异常（可忽略）: {e}")

    # 启动应用
    log(f"启动应用: {PACKAGE_NAME}")
    d.app_start(PACKAGE_NAME)
    log(f"启动后等待 {LAUNCH_WAIT}s...")
    time.sleep(LAUNCH_WAIT)  # 等待启动（可调整）

    # 尝试关闭启动广告（可选，根据 App 情况调整）
    if CLOSE_AD_ON_LAUNCH:
        log("尝试关闭广告弹窗（如果存在）")
        close_ad_if_exists(d)
        # 若仍被广告遮挡，可按返回键兜底
        if d(textContains='广告').exists(timeout=0.5) or d(descriptionContains='广告').exists(timeout=0.5):
            log("广告可能未关闭，按返回键兜底")
            d.press('back')
        # 再等一会儿以确保弹窗消失
        time.sleep(1)

    # 点击 “试一试” 按钮（多种定位兜底）
    try_btn_selectors = [
        d(resourceId='com.earth.explorer.launcher.live.map.satelliteview:id/tv_have_a_try'),
        d(text='试一试'),
        d(textContains='试一试')
    ]
    try_btn = wait_until_exists(try_btn_selectors, '试一试按钮', timeout=10, interval=0.5)
    if not try_btn:
        log("未看到“试一试”，按返回键兜底再等待 2s 再查找")
        d.press('back')
        time.sleep(2)
        try_btn = wait_until_exists(try_btn_selectors, '试一试按钮', timeout=6, interval=0.5)
        if not try_btn:
            raise AssertionError("未找到元素: 试一试按钮")
    log("点击 \"试一试\" 按钮")
    safe_click(d, try_btn, timeout=2)
    log("点击空白区域以提前关闭提示（如未关闭则继续等待）")
    click_by_percent(d, 50.0, 60.0)  # 空白区域
    log("等待 1s")
    time.sleep(1)
    log("兜底再等待 5s")
    time.sleep(5)

    # 在默认主屏幕应用选择页选择 Live Earth Map（文本优先，坐标兜底）
    live_earth_by_text = d(text='Live Earth Map')
    if live_earth_by_text.exists(timeout=2):
        log("选择 Live Earth Map（文本）")
        safe_click(d, live_earth_by_text, timeout=2)
    else:
        log("未找到文本，使用坐标兜底点击 Live Earth Map 单选框 (11.1%, 17.2%)")
        click_by_percent(d, 11.1, 17.2)  # 估算的单选框位置
    log("等待 1s")
    time.sleep(1)

    # 断言桌面图标存在（验证已返回桌面）
    icon_candidates = [
        d(descriptionContains='Live Earth'),
        d(textContains='Live Earth'),
    ]
    icon_found = wait_until_exists(icon_candidates, '桌面 Live Earth 图标', timeout=5, interval=0.5)
    if not icon_found:
        raise AssertionError("未找到元素: 桌面 Live Earth 图标")
    log('✅ 测试完成')


if __name__ == '__main__':
    test_main()
