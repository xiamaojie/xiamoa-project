

import sys
import urllib.parse
from PySide6.QtWidgets import (
    QApplication, QWidget, QLabel, QLineEdit, QPushButton, QVBoxLayout,
    QHBoxLayout, QMessageBox, QTextEdit, QComboBox
)
from PySide6.QtGui import QClipboard
from PySide6.QtCore import QSize

class BuyLinkGenerator(QWidget):
    def __init__(self):
        super().__init__()
        self.init_ui()

    def init_ui(self):
        self.setWindowTitle("买量链接生成工具")
        self.setGeometry(100, 100, 600, 500)

        # 平台选择
        self.platform_label = QLabel("选择平台：")
        self.platform_combo = QComboBox()
        self.platform_combo.addItems(["安卓", "iOS"])

        platform_layout = QHBoxLayout()
        platform_layout.addWidget(self.platform_label)
        platform_layout.addWidget(self.platform_combo)

        # 原始链接输入
        self.url_label = QLabel("🔗 请输入原始链接：")
        self.url_input = QLineEdit()
        self.url_input.setFixedSize(550, 90)  # 设置输入框高度大约为3厘米

        # 广告 ID 输入
        self.gaid_label = QLabel("🆔 请输入广告 ID（GAID/IDFA）：")
        self.gaid_input = QLineEdit()
        self.gaid_input.setFixedSize(550, 90)  # 设置输入框高度大约为3厘米

        # 生成按钮
        self.generate_button = QPushButton("生成买量链接")
        self.generate_button.clicked.connect(self.generate_buy_link)

        # 输出框
        self.result_label = QLabel("✅ 生成的最终买量链接：")
        self.result_output = QTextEdit()
        self.result_output.setReadOnly(True)
        self.result_output.setFixedHeight(150)  # 设置输出框高度

        # 复制按钮
        self.copy_button = QPushButton("复制链接")
        self.copy_button.clicked.connect(self.copy_to_clipboard)

        button_layout = QHBoxLayout()
        button_layout.addWidget(self.generate_button)
        button_layout.addWidget(self.copy_button)

        # 布局管理
        layout = QVBoxLayout()
        layout.addLayout(platform_layout)
        layout.addWidget(self.url_label)
        layout.addWidget(self.url_input)
        layout.addWidget(self.gaid_label)
        layout.addWidget(self.gaid_input)
        layout.addLayout(button_layout)
        layout.addWidget(self.result_label)
        layout.addWidget(self.result_output)

        self.setLayout(layout)

    def generate_buy_link(self):
        platform = self.platform_combo.currentText()
        platform_type = "iOS" if platform == "iOS" else "安卓"
        param_name = "idfa" if platform == "iOS" else "android_id"

        original_url = self.url_input.text().strip()
        if not original_url:
            QMessageBox.warning(self, "错误", "链接不能为空！")
            return

        gaid = self.gaid_input.text().strip()
        if not gaid:
            QMessageBox.warning(self, "错误", "广告 ID 不能为空！")
            return

        parsed_url = urllib.parse.urlparse(original_url)
        query_params = urllib.parse.parse_qs(urllib.parse.unquote(parsed_url.query))

        query_params[param_name] = [gaid]
        new_query_string = "&".join(f"{key}={value[0]}" for key, value in query_params.items())

        final_url = urllib.parse.urlunparse(parsed_url._replace(query=new_query_string))

        self.result_output.setPlainText(final_url)

    def copy_to_clipboard(self):
        clipboard = QApplication.clipboard()
        clipboard.setText(self.result_output.toPlainText())
        QMessageBox.information(self, "成功", "链接已复制到剪贴板！")

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = BuyLinkGenerator()
    window.show()
    sys.exit(app.exec())

