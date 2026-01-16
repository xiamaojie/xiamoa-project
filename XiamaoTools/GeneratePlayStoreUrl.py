import sys
import subprocess
from PySide6.QtWidgets import QApplication, QWidget, QLabel, QLineEdit, QTextBrowser, QPushButton, QVBoxLayout, QMessageBox


class GooglePlayLinkGenerator(QWidget):
    """生成谷歌商店的下载链接，并支持复制与手机 Chrome 打开"""

    def __init__(self):
        super().__init__()
        self.copy_button = None
        self.open_browser_button = None
        self.generate_button = None
        self.output_field = None
        self.output_label = None
        self.input_field = None
        self.input_label = None
        self.init_ui()

    def init_ui(self):
        self.setWindowTitle("Google Play 链接生成工具")
        self.setGeometry(100, 100, 500, 300)

        # 输入框
        self.input_label = QLabel("请输入包名（以 com 开头）:", self)
        self.input_field = QLineEdit(self)
        self.input_field.setFixedHeight(90)  # 3cm ≈ 90 像素

        # 输出框
        self.output_label = QLabel("生成的链接:", self)
        self.output_field = QTextBrowser(self)
        self.output_field.setOpenExternalLinks(True)  # 支持点击链接直接打开
        self.output_field.setFixedHeight(90)  # 3cm ≈ 90 像素

        # 按钮
        self.generate_button = QPushButton("生成链接", self)
        self.generate_button.clicked.connect(self.google_play_store_url)

        self.copy_button = QPushButton("复制链接", self)
        self.copy_button.clicked.connect(self.copy_to_clipboard)

        self.open_browser_button = QPushButton("在手机 Chrome 打开", self)
        self.open_browser_button.clicked.connect(self.open_in_mobile_chrome)

        # 布局
        layout = QVBoxLayout()
        layout.addWidget(self.input_label)
        layout.addWidget(self.input_field)
        layout.addWidget(self.generate_button)
        layout.addWidget(self.output_label)
        layout.addWidget(self.output_field)
        layout.addWidget(self.copy_button)
        layout.addWidget(self.open_browser_button)  # 添加在手机 Chrome 打开按钮

        self.setLayout(layout)

    def google_play_store_url(self):
        package_name = self.input_field.text().strip()

        # 校验包名
        if not package_name:
            self.show_error("包名不能为空！")
            return

        if not package_name.startswith("com"):
            self.show_error("包名必须以 'com' 开头！")
            return

        # 生成链接
        base_url = "https://play.google.com/store/apps/details?id="
        full_url = f"{base_url}{package_name}"
        self.output_field.setText(full_url)

    def copy_to_clipboard(self):
        link = self.output_field.toPlainText()
        if not link:
            self.show_error("没有可复制的链接！")
            return

        # 复制到剪贴板
        clipboard = QApplication.clipboard()
        clipboard.setText(link)
        QMessageBox.information(self, "复制成功", "链接已复制到剪贴板！")

    def open_in_mobile_chrome(self):
        link = self.output_field.toPlainText()
        if not link:
            self.show_error("没有可打开的链接！")
            return

        # ADB 命令启动手机上的 Chrome 并打开链接
        adb_command = f"adb shell am start -a android.intent.action.VIEW -d \"{link}\" com.android.chrome"
        try:
            subprocess.run(adb_command, shell=True, check=True)
            QMessageBox.information(self, "成功", "链接已在手机 Chrome 打开！")
        except subprocess.CalledProcessError:
            self.show_error("ADB 命令执行失败，请检查设备连接！")

    def show_error(self, message):
        QMessageBox.critical(self, "错误", message)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = GooglePlayLinkGenerator()
    window.show()
    sys.exit(app.exec())
