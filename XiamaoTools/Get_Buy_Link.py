
# 根据传入的adjust_id，自动获取买量链接
import time

from playwright.sync_api import sync_playwright


def get_buy_link(adjust_id="lr8jmgiz1b7k"):
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
        page.locator("#input-2").fill("Touka2506**@.")  # 密码
        page.locator('button[type="submit"]').click()

        # 点击Campaign Lab
        locator = page.locator('xpath=/html/body/div[1]/div[2]/div[1]/div[2]/div[3]/div/div[2]')
        locator.wait_for(state="visible", timeout=10000)
        locator.click()
        # page.get_by_text("合作伙伴").click()
        # 点第一个包含“合作伙伴”的按钮
        page.get_by_text("合作伙伴").nth(0).click()
        # 点击应用无处的输入框
        page.locator("span[class*='Badge__Badge__label']", has_text="无").click()
        page.locator('input[aria-label="应用_search-input"]').fill(adjust_id)
        page.keyboard.press("Enter")
        page.locator(f'input[type="radio"][value="{adjust_id}"]').check()
        page.get_by_test_id("应用_apply-button").click()

        page.wait_for_selector('div[data-testid^="cell-name-"]', timeout=15000)

        # 等渠道a标签出现
        page.wait_for_selector('a[data-testid="ad-network-name"]', timeout=15000)

        # 关键：打印源码，排查数据是否已到DOM
        html_now = page.content()
        with open("debug_page.html", "w", encoding='utf-8') as f:
            f.write(html_now)

        links = page.locator('a[data-testid="ad-network-name"]')
        count = links.count()

        channel_names = []
        for i in range(count):
            name = links.nth(i).inner_text().strip()
            channel_names.append(name)
        print(f"获取到的聚道平台有{channel_names}")
        # 优先点Mintegral
        clicked = False
        for i, name in enumerate(channel_names):
            if name == "Mintegral":
                links.nth(i).click()
                print("已点击Mintegral")
                clicked = True
                break
        if not clicked and count > 0:
            links.nth(0).click()
            print(f"没有Mintegral，已点击第一个渠道：{channel_names[0]}")
        elif count == 0:
            print("没有可点击的渠道！")

        page.wait_for_selector('a[data-testid="network-level-link-name"]', timeout=10000)
        links = page.locator('a[data-testid="network-level-link-name"]')
        count = links.count()
        channel_names = [links.nth(i).inner_text().strip() for i in range(count)]
        print("聚道名称列表:", channel_names)
        # 点击第1个
        if count > 0:
            links.first.click()
            print("已点击第1个:", channel_names[0])
        # 复制url
        selector = 'span[data-testid="link-details.regular-link.click-url.copy-url.url"]'
        page.wait_for_selector(selector, timeout=10000)

        real_url = page.locator(selector).inner_text().strip()
        print("复制到的聚道链接是:", real_url)

        time.sleep(1)
        page.close()


if __name__ == '__main__':
    get_buy_link()
