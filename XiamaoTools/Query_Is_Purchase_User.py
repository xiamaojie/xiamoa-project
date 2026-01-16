# 查询是否买量
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError
import time


def query_is_purchase_user(gaid, adjust_id="lr8jmgiz1b7k"):
    """
    判断指定广告 GAID 对应用户是否买量用户。
    参数:
        gaid: str, 广告ID (必填)
        adjust_id: str, Adjust后台页面搜索用ID，默认是测试包名的adjust_id "lr8jmgiz1b7k"
    """
    if not gaid:
        raise ValueError("参数 gaid 必需传递（广告ID不能为空）")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/114.0.0.0 Safari/537.36"
            ),
            locale="zh-CN",
        )
        page = context.new_page()

        # 伪装脚本隐藏webdriver等
        page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            window.navigator.chrome = { runtime: {} };
            Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3], });
            Object.defineProperty(navigator, 'languages', { get: () => ['zh-CN', 'zh'], });
        """)

        # 打开Adjust页面，填登录信息（请补自己账号和密码）
        page.goto("https://suite.adjust.com/")
        page.locator("#input-1").fill("dev@toukagames.com")  # 用户名
        page.locator("#input-2").fill("Touka2309@@.")  # 密码
        page.locator('button[type="submit"]').click()

        # 选择应用/控制台页面
        page.locator('text=AppView').first.click()
        page.get_by_text("所有应用").click()
        page.get_by_placeholder("搜索").fill(adjust_id)
        page.keyboard.press("Enter")
        page.get_by_text("测试控制台").click()

        page.locator('[name="advertisingId"]').fill(gaid)
        page.get_by_text("查看设备数据").click()

        # 检查弹窗提示
        try:
            locator = page.locator('//h2[contains(text(), "未找到广告 ID。")]')
            locator.wait_for(state="visible", timeout=3000)
            text = locator.inner_text()
            print(f"{gaid}：提示弹窗【{text}】，不是买量用户，流程结束。")
            browser.close()
            return False  # 返回False代表不是买量用户
        except PlaywrightTimeoutError:
            pass  # 没弹出，继续下方流程

        # 非弹窗情况，抓取并判断数据
        for _ in range(2):
            page.mouse.wheel(0, 800)
            page.wait_for_timeout(500)
        xpath = "/html/body/div[1]/div[2]/div[2]/div/main/div/section/div/div/div[2]/div/div[3]/div[2]/div/div[3]/p"
        value_text = page.locator(f"xpath={xpath}").inner_text()
        time.sleep(5)
        if "Organic" in value_text:
            print(f"{gaid}:是自然用户")
            browser.close()
            return False
        else:
            print(f"{gaid}:是买量用户（链接名称显示为：{value_text}）")
            browser.close()
            return True


if __name__ == '__main__':
    query_is_purchase_user(gaid="993dac66-7726-402a-89c4-bcb017be0a27")
