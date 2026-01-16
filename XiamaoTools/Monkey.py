from PySide6.QtWidgets import (
    QApplication, QWidget, QPushButton, QTextEdit, QVBoxLayout, QLabel,
    QLineEdit, QHBoxLayout, QFileDialog, QComboBox, QProgressBar, QCheckBox
)
from PySide6.QtGui import QPixmap
import subprocess
import threading
import os
import time

class MonkeyTester(QWidget):
    def __init__(self):
        super().__init__()

        self.export_log = None
        self.setWindowTitle("ADB Monkey 测试工具")
        self.setGeometry(100, 100, 700, 600)

        # UI 组件
        self.device_label = QLabel("设备选择:")
        self.device_selector = QComboBox(self)
        self.refresh_devices()

        self.package_label = QLabel("应用包名:")
        self.package_input = QLineEdit(self)
        self.package_input.setText("com.hotpotgames.happysave.global")

        self.event_label = QLabel("事件数量:")
        self.event_input = QLineEdit(self)
        self.event_input.setText("1000")

        self.throttle_label = QLabel("间隔时间 (ms):")
        self.throttle_input = QLineEdit(self)
        self.throttle_input.setText("500")

        self.ignore_crashes = QCheckBox("忽略崩溃 (--ignore-crashes)", self)
        self.ignore_timeouts = QCheckBox("忽略超时 (--ignore-timeouts)", self)
        self.ignore_security_exceptions = QCheckBox("忽略安全异常 (--ignore-security-exceptions)", self)

        self.retry_on_crash = QCheckBox("崩溃后自动重试", self)

        self.search_label = QLabel("日志关键字过滤:")
        self.search_input = QLineEdit(self)
        self.search_input.setPlaceholderText("输入关键字，例如 CRASH 或 ERROR")

        self.start_button = QPushButton("开始 Monkey 测试", self)
        self.start_button.clicked.connect(self.run_monkey)

        self.screenshot_button = QPushButton("截图", self)
        self.screenshot_button.clicked.connect(self.take_screenshot)

        self.export_log_button = QPushButton("导出日志", self)
        self.export_log_button.clicked.connect(self.export_log)

        self.log_output = QTextEdit(self)
        self.log_output.setReadOnly(True)

        self.screenshot_label = QLabel("截图预览:")
        self.screenshot_display = QLabel(self)
        self.screenshot_display.setFixedSize(300, 500)

        self.progress_bar = QProgressBar(self)
        self.progress_bar.setValue(0)

        # 布局
        device_layout = QHBoxLayout()
        device_layout.addWidget(self.device_label)
        device_layout.addWidget(self.device_selector)

        input_layout = QHBoxLayout()
        input_layout.addWidget(self.package_label)
        input_layout.addWidget(self.package_input)
        input_layout.addWidget(self.event_label)
        input_layout.addWidget(self.event_input)
        input_layout.addWidget(self.throttle_label)
        input_layout.addWidget(self.throttle_input)

        option_layout = QHBoxLayout()
        option_layout.addWidget(self.ignore_crashes)
        option_layout.addWidget(self.ignore_timeouts)
        option_layout.addWidget(self.ignore_security_exceptions)
        option_layout.addWidget(self.retry_on_crash)

        search_layout = QHBoxLayout()
        search_layout.addWidget(self.search_label)
        search_layout.addWidget(self.search_input)

        button_layout = QHBoxLayout()
        button_layout.addWidget(self.start_button)
        button_layout.addWidget(self.screenshot_button)
        button_layout.addWidget(self.export_log_button)

        layout = QVBoxLayout()
        layout.addLayout(device_layout)
        layout.addLayout(input_layout)
        layout.addLayout(option_layout)
        layout.addLayout(search_layout)
        layout.addWidget(self.log_output)
        layout.addWidget(self.progress_bar)
        layout.addLayout(button_layout)
        layout.addWidget(self.screenshot_label)
        layout.addWidget(self.screenshot_display)

        self.setLayout(layout)

    def refresh_devices(self):
        """ 获取当前连接的 ADB 设备 """
        self.device_selector.clear()
        result = subprocess.run("adb devices", shell=True, capture_output=True, text=True)
        devices = result.stdout.splitlines()[1:-1]
        for device in devices:
            if "device" in device:
                self.device_selector.addItem(device.split("\t")[0])

    def build_monkey_command(self, device, package_name, event_count, throttle):
        """ 生成 Monkey 命令 """
        cmd = f"adb -s {device} shell monkey -p {package_name} --throttle {throttle} -v {event_count}"
        if self.ignore_crashes.isChecked():
            cmd += " --ignore-crashes"
        if self.ignore_timeouts.isChecked():
            cmd += " --ignore-timeouts"
        if self.ignore_security_exceptions.isChecked():
            cmd += " --ignore-security-exceptions"
        return cmd

    def run_monkey(self):
        """ 启动 ADB Monkey 测试 """
        device = self.device_selector.currentText()
        package_name = self.package_input.text().strip()
        event_count = int(self.event_input.text().strip())
        throttle = int(self.throttle_input.text().strip())

        if not package_name or not device:
            self.log_output.append("⚠️ 请选择设备并填写应用包名！")
            return

        self.log_output.append(f"🚀 启动 Monkey 测试: {package_name} ({event_count} events, {throttle}ms) on {device}")
        self.start_button.setEnabled(False)
        self.progress_bar.setValue(0)

        def run():
            retry = True
            while retry:
                monkey_cmd = self.build_monkey_command(device, package_name, event_count, throttle)
                process = subprocess.Popen(monkey_cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

                event_step = max(1, event_count // 100)
                current_event = 0
                detected_crash = False

                for line in process.stdout:
                    if self.search_input.text().strip() in line or self.search_input.text().strip() == "":
                        self.log_output.append(line.strip())

                    if "Events injected:" in line:
                        current_event += event_step
                        progress = min(100, int((current_event / event_count) * 100))
                        self.progress_bar.setValue(progress)

                    if "CRASH" in line:
                        self.log_output.append("❌ 检测到应用崩溃！")
                        detected_crash = True

                self.progress_bar.setValue(100)
                self.log_output.append("✅ Monkey 测试完成")

                if detected_crash and self.retry_on_crash.isChecked():
                    self.log_output.append("🔄 发现崩溃，自动重试中...")
                    time.sleep(2)
                else:
                    retry = False

            self.start_button.setEnabled(True)

        thread = threading.Thread(target=run)
        thread.start()

    def take_screenshot(self):
        """ 截图并显示 """
        device = self.device_selector.currentText()
        if not device:
            self.log_output.append("⚠️ 请先选择设备！")
            return

        self.log_output.append("📸 正在截图...")

        def run():
            screenshot_path = "/sdcard/screenshot.png"
            local_path = "screenshot.png"

            subprocess.run(f"adb -s {device} shell screencap -p {screenshot_path}", shell=True)
            subprocess.run(f"adb -s {device} pull {screenshot_path} {local_path}", shell=True)

            if os.path.exists(local_path):
                self.log_output.append("✅ 截图成功！")
                self.screenshot_display.setPixmap(QPixmap(local_path).scaled(300, 500))
            else:
                self.log_output.append("❌ 截图失败！")

        thread = threading.Thread(target=run)
        thread.start()

if __name__ == "__main__":
    app = QApplication([])
    window = MonkeyTester()
    window.show()
    app.exec()
