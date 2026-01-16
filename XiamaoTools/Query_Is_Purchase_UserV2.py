# 查询是否买量界面版本
import sys
import time

from PySide6.QtCore import QThread, Signal
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QLabel,
    QLineEdit, QTextEdit, QPushButton, QCheckBox
)
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError


def query_is_purchase_user(gaid, adjust_id="lr8jmgiz1b7k", output_signal=None, headless=False):
    if not gaid:
        msg = "❌ 参数 gaid 必需传递（广告ID不能为空）"
        if output_signal:
            output_signal.emit(msg)
        return

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=headless)
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

            page.goto("https://suite.adjust.com/")
            page.locator("#input-1").fill("dev@toukagames.com")
            page.locator("#input-2").fill("Touka2508**@.")
            page.locator('button[type="submit"]').click()

            page.locator('text=AppView').first.click()
            page.get_by_text("所有应用").click()
            page.get_by_placeholder("搜索").fill(adjust_id)
            page.keyboard.press("Enter")
            page.get_by_text("测试控制台").click()

            page.locator('[name="advertisingId"]').fill(gaid)
            page.get_by_text("查看设备数据").click()

            try:
                locator = page.locator('//h2[contains(text(), "未找到广告 ID。")]')
                locator.wait_for(state="visible", timeout=3000)
                text = locator.inner_text()
                msg = f"{gaid}：提示弹窗【{text}】，不是买量用户，流程结束。"
                if output_signal:
                    output_signal.emit(msg)
                browser.close()
                return
            except PlaywrightTimeoutError:
                pass

            for _ in range(2):
                page.mouse.wheel(0, 800)
                page.wait_for_timeout(500)
            xpath = "/html/body/div[1]/div[2]/div[2]/div/main/div/section/div/div/div[2]/div/div[3]/div[2]/div/div[3]/p"
            value_text = page.locator(f"xpath={xpath}").inner_text()
            if "Organic" in value_text:
                msg = f"{gaid}: 是自然用户"
            else:
                msg = f"{gaid}: 是买量用户（链接名称显示为：{value_text}）"
            if output_signal:
                output_signal.emit(msg)
            browser.close()
    except Exception as e:
        if output_signal:
            output_signal.emit(f"❌ 出错了：{str(e)}")


class QueryThread(QThread):
    output = Signal(str)

    def __init__(self, gaid, adjust_id, headless):
        super().__init__()
        self.gaid = gaid
        self.adjust_id = adjust_id
        self.headless = headless

    def run(self):
        query_is_purchase_user(self.gaid, self.adjust_id, self.output, self.headless)


class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("查询是否买量用户")
        self.setMinimumSize(600, 400)

        layout = QVBoxLayout()

        self.gaid_input = QLineEdit()
        self.gaid_input.setPlaceholderText("请输入 GAID")
        self.gaid_input.setText("993dac66-7726-402a-89c4-bcb017be0a27")

        self.adjust_input = QLineEdit()
        self.adjust_input.setPlaceholderText("请输入 Adjust ID（可选）")
        self.adjust_input.setText("lr8jmgiz1b7k")

        self.headless_checkbox = QCheckBox("启用 Headless（后台运行浏览器）")
        self.headless_checkbox.setChecked(False)

        self.query_button = QPushButton("开始查询")
        self.query_button.clicked.connect(self.run_query)

        self.output_box = QTextEdit()
        self.output_box.setReadOnly(True)

        layout.addWidget(QLabel("GAID:"))
        layout.addWidget(self.gaid_input)

        layout.addWidget(QLabel("Adjust ID(可不传，不传默认测试包名的adjust_id):"))
        layout.addWidget(self.adjust_input)

        layout.addWidget(self.headless_checkbox)
        layout.addWidget(self.query_button)
        layout.addWidget(QLabel("结果输出："))
        layout.addWidget(self.output_box)

        self.setLayout(layout)

    def run_query(self):
        gaid = self.gaid_input.text().strip()
        adjust_id = self.adjust_input.text().strip() or "lr8jmgiz1b7k"
        headless = self.headless_checkbox.isChecked()

        self.output_box.append("🚀 开始查询...\n")

        self.thread = QueryThread(gaid, adjust_id, headless)
        self.thread.output.connect(self.append_output)
        self.thread.start()

    def append_output(self, text):
        self.output_box.append(text + "\n")


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
