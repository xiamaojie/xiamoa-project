import json
import sys
import re

from PySide6.QtWidgets import (
    QApplication, QWidget, QLabel, QTextEdit, QPushButton, QVBoxLayout,
    QHBoxLayout, QMessageBox
)


class ProlinkConfigGenerator(QWidget):
    def __init__(self):
        super().__init__()
        self.copy_button = None
        self.result_output = None
        self.result_label = None
        self.generate_button = None
        self.input_field = None
        self.input_label = None
        self.init_ui()

    def init_ui(self):
        self.setWindowTitle("Prolink 配置文件生成工具")
        self.setGeometry(100, 100, 600, 500)

        self.input_label = QLabel("请输入 resource 数据（格式：remark,md5,url）：")
        self.input_field = QTextEdit()
        self.input_field.setFixedHeight(80)

        self.generate_button = QPushButton("生成 JSON 配置")
        self.generate_button.clicked.connect(self.generate_prolink_config_file)

        self.result_label = QLabel("✅ 生成的 JSON 配置文件：")
        self.result_output = QTextEdit()
        self.result_output.setReadOnly(True)
        self.result_output.setFixedHeight(200)

        self.copy_button = QPushButton("复制 JSON")
        self.copy_button.clicked.connect(self.copy_to_clipboard)

        button_layout = QHBoxLayout()
        button_layout.addWidget(self.generate_button)
        button_layout.addWidget(self.copy_button)

        layout = QVBoxLayout()
        layout.addWidget(self.input_label)
        layout.addWidget(self.input_field)
        layout.addLayout(button_layout)
        layout.addWidget(self.result_label)
        layout.addWidget(self.result_output)

        self.setLayout(layout)

    def generate_prolink_config_file(self):
        resource_data = self.input_field.toPlainText().strip()

        try:
            parts = resource_data.split(',', 2)
            if len(parts) != 3:
                raise ValueError("输入数据格式错误，请按照 'remark,md5,url' 格式传参！")

            remark_raw, md5_raw, url_raw = parts
            remark = remark_raw.strip().replace('-', '')
            md5_hash = md5_raw.strip()
            url = url_raw.strip()

            if len(md5_hash) != 32 or not re.fullmatch(r"[a-fA-F0-9]{32}", md5_hash):
                raise ValueError("MD5 哈希值格式不正确，必须是32位十六进制字符串！")

            data = [
                {
                    "md5": md5_hash,
                    "url": url,
                    "remark": remark
                }
            ]

            json_output = json.dumps(data, indent=2, ensure_ascii=False)
            self.result_output.setPlainText(json_output)

        except ValueError as e:
            QMessageBox.warning(self, "错误", str(e))

    def copy_to_clipboard(self):
        clipboard = QApplication.clipboard()
        clipboard.setText(self.result_output.toPlainText())
        QMessageBox.information(self, "成功", "JSON 数据已复制到剪贴板！")


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = ProlinkConfigGenerator()
    window.show()
    sys.exit(app.exec())
