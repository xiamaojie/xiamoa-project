import sys
import time
import urllib.parse

from PySide6.QtWidgets import (
    QApplication, QWidget, QLabel, QLineEdit, QPushButton, QVBoxLayout,
    QHBoxLayout, QMessageBox, QTextEdit, QCheckBox
)
from PySide6.QtCore import QThread, Signal
from playwright.sync_api import sync_playwright


class LinkFetchThread(QThread):
    finished = Signal(str)
    failed = Signal(str)

    def __init__(self, adjust_id, headless):
        super().__init__()
        self.adjust_id = adjust_id
        self.headless = headless

    def run(self):
        try:
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=self.headless)
                context = browser.new_context(
                    user_agent=(
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/114.0.0.0 Safari/537.36"
                    ),
                    locale="zh-CN",
                )
                page = context.new_page()

                page.add_init_script("""
                    Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
                    window.navigator.chrome = { runtime: {} };
                    Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3], });
                    Object.defineProperty(navigator, 'languages', { get: () => ['zh-CN', 'zh'], });
                """)

                # 登录 Adjust
                page.goto("https://suite.adjust.com/")
                page.locator("#input-1").fill("dev@toukagames.com")
                page.locator("#input-2").fill("Touka2508**@.")
                page.locator('button[type="submit"]').click()

                # 进入 Campaign Lab
                locator = page.locator('xpath=/html/body/div[1]/div[2]/div[1]/div[2]/div[3]/div/div[2]')
                locator.wait_for(state="visible", timeout=10000)
                locator.click()
                # page.get_by_text("合作伙伴").click()
                # 点第一个包含“合作伙伴”的按钮
                page.get_by_text("合作伙伴").nth(0).click()
                # 点击应用无处的输入框
                page.locator("span[class*='Badge__Badge__label']", has_text="无").click()


                page.locator('input[aria-label="应用_search-input"]').fill(self.adjust_id)
                page.keyboard.press("Enter")
                page.locator(f'input[type="radio"][value="{self.adjust_id}"]').check()
                page.get_by_test_id("应用_apply-button").click()

                page.wait_for_selector('a[data-testid="ad-network-name"]', timeout=15000)
                links = page.locator('a[data-testid="ad-network-name"]')
                count = links.count()

                clicked = False
                for i in range(count):
                    name = links.nth(i).inner_text().strip()
                    if name == "Mintegral":
                        links.nth(i).click()
                        clicked = True
                        break
                if not clicked and count > 0:
                    links.nth(0).click()

                page.wait_for_selector('a[data-testid="network-level-link-name"]', timeout=10000)
                page.locator('a[data-testid="network-level-link-name"]').first.click()

                selector = 'span[data-testid="link-details.regular-link.click-url.copy-url.url"]'
                page.wait_for_selector(selector, timeout=10000)
                real_url = page.locator(selector).inner_text().strip()

                self.finished.emit(real_url)
                page.close()
        except Exception as e:
            self.failed.emit(str(e))


class BuyLinkGenerator(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("自动获取归因平台，生成买量链接")
        self.setMinimumSize(800, 600)
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout()

        # Adjust ID 输入
        self.adjust_label = QLabel("📦 Adjust ID（可不填，默认使用测试包名的 adjust_id）:")
        self.adjust_input = QLineEdit()
        self.adjust_input.setPlaceholderText("不填默认使用 lr8jmgiz1b7k")

        # GAID 输入
        self.gaid_label = QLabel("🆔 广告 ID（GAID，必填）:")
        self.gaid_input = QLineEdit()
        self.gaid_input.setPlaceholderText("例如：993dac66-7726-402a-89c4-bcb017be0a27")
        self.gaid_input.setText("993dac66-7726-402a-89c4-bcb017be0a27")  # 设置默认值

        # 设置选项
        self.headless_checkbox = QCheckBox("启用 Headless（后台运行浏览器）")
        self.headless_checkbox.setChecked(False)

        self.auto_fetch_checkbox = QCheckBox("自动获取归因链接")
        self.auto_fetch_checkbox.setChecked(False)  # ✅ 默认不勾选

        # 手动归因链接输入框（更大）
        self.link_input_label = QLabel("🔗 原始归因链接（如未自动获取）：")
        self.link_input = QTextEdit()
        self.link_input.setPlaceholderText("手动粘贴归因平台链接")
        self.link_input.setMinimumHeight(100)
        self.link_input.setStyleSheet("font-size: 16px;")

        # 按钮
        self.fetch_button = QPushButton("生成买量链接")
        self.fetch_button.clicked.connect(self.generate_buy_link)

        self.copy_button = QPushButton("复制链接")
        self.copy_button.clicked.connect(self.copy_to_clipboard)

        # 输出
        self.result_label = QLabel("✅ 最终买量链接：")
        self.result_output = QTextEdit()
        self.result_output.setReadOnly(True)

        layout.addWidget(self.adjust_label)
        layout.addWidget(self.adjust_input)
        layout.addWidget(self.gaid_label)
        layout.addWidget(self.gaid_input)
        layout.addWidget(self.headless_checkbox)
        layout.addWidget(self.auto_fetch_checkbox)
        layout.addWidget(self.link_input_label)
        layout.addWidget(self.link_input)
        layout.addWidget(self.fetch_button)
        layout.addWidget(self.copy_button)
        layout.addWidget(self.result_label)
        layout.addWidget(self.result_output)

        self.setLayout(layout)

    def generate_buy_link(self):
        self.result_output.clear()
        gaid = self.gaid_input.text().strip()
        adjust_id = self.adjust_input.text().strip() or "lr8jmgiz1b7k"
        headless = self.headless_checkbox.isChecked()
        auto_fetch = self.auto_fetch_checkbox.isChecked()

        if not gaid:
            QMessageBox.warning(self, "错误", "广告 ID 不能为空！")
            return

        if auto_fetch:
            self.fetch_button.setEnabled(False)
            self.fetch_button.setText("正在获取链接...")
            self.thread = LinkFetchThread(adjust_id, headless)
            self.thread.finished.connect(lambda url: self.build_url(url, gaid))
            self.thread.failed.connect(self.on_fetch_failed)
            self.thread.start()
        else:
            manual_url = self.link_input.toPlainText().strip()
            if not manual_url:
                QMessageBox.warning(self, "错误", "请输入归因链接或启用自动获取！")
                return
            self.build_url(manual_url, gaid)

    def build_url(self, base_url, gaid):
        parsed_url = urllib.parse.urlparse(base_url)
        query_params = urllib.parse.parse_qs(urllib.parse.unquote(parsed_url.query))

        query_params["android_id"] = [gaid]
        new_query = "&".join(f"{key}={value[0]}" for key, value in query_params.items())

        final_url = urllib.parse.urlunparse(parsed_url._replace(query=new_query))
        self.result_output.setPlainText(final_url)
        self.fetch_button.setEnabled(True)
        self.fetch_button.setText("生成买量链接")

    def on_fetch_failed(self, error_msg):
        self.fetch_button.setEnabled(True)
        self.fetch_button.setText("生成买量链接")
        QMessageBox.critical(self, "获取失败", f"获取归因链接失败：\n{error_msg}")

    def copy_to_clipboard(self):
        clipboard = QApplication.clipboard()
        clipboard.setText(self.result_output.toPlainText())
        QMessageBox.information(self, "成功", "链接已复制到剪贴板！")


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = BuyLinkGenerator()
    window.show()
    sys.exit(app.exec())
