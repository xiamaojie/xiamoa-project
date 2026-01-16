import csv
import subprocess
import sys
import threading
from datetime import datetime

import matplotlib.pyplot as plt
from PySide6.QtWidgets import QApplication
from PySide6.QtWidgets import (
    QWidget, QPushButton, QTextEdit, QVBoxLayout, QLabel,
    QLineEdit, QHBoxLayout, QFileDialog, QComboBox, QProgressBar, QCheckBox
)


class MonkeyTester(QWidget):
    def __init__(self):
        super().__init__()

        self.setWindowTitle("ADB Monkey 测试工具")
        self.setGeometry(100, 100, 700, 700)

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
        self.retry_on_crash = QCheckBox("崩溃后自动重试", self)
        self.restart_on_crash = QCheckBox("崩溃后自动重启应用", self)

        self.search_label = QLabel("日志关键字过滤:")
        self.search_input = QLineEdit(self)
        self.search_input.setPlaceholderText("输入关键字，例如 CRASH 或 ERROR")

        self.start_button = QPushButton("开始 Monkey 测试", self)
        self.start_button.clicked.connect(self.run_monkey)

        self.export_log_button = QPushButton("导出日志", self)
        self.export_log_button.clicked.connect(self.export_log)

        self.show_chart_button = QPushButton("查看崩溃统计图", self)
        self.show_chart_button.clicked.connect(self.show_crash_chart)

        self.export_results_button = QPushButton("导出测试结果", self)
        self.export_results_button.clicked.connect(self.export_results)

        self.log_output = QTextEdit(self)
        self.log_output.setReadOnly(True)

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
        option_layout.addWidget(self.retry_on_crash)
        option_layout.addWidget(self.restart_on_crash)

        search_layout = QHBoxLayout()
        search_layout.addWidget(self.search_label)
        search_layout.addWidget(self.search_input)

        button_layout = QHBoxLayout()
        button_layout.addWidget(self.start_button)
        button_layout.addWidget(self.export_log_button)
        button_layout.addWidget(self.show_chart_button)
        button_layout.addWidget(self.export_results_button)

        layout = QVBoxLayout()
        layout.addLayout(device_layout)
        layout.addLayout(input_layout)
        layout.addLayout(option_layout)
        layout.addLayout(search_layout)
        layout.addWidget(self.log_output)
        layout.addWidget(self.progress_bar)
        layout.addLayout(button_layout)

        self.setLayout(layout)

        # 统计信息
        self.crash_count = 0
        self.test_start_time = None
        self.test_end_time = None

    def refresh_devices(self):
        """ 获取当前连接的 ADB 设备 """
        self.device_selector.clear()
        result = subprocess.run("adb devices", shell=True, capture_output=True, text=True)
        devices = result.stdout.splitlines()[1:-1]
        for device in devices:
            if "device" in device:
                self.device_selector.addItem(device.split("\t")[0])

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
        self.crash_count = 0  # 重置崩溃计数
        self.test_start_time = datetime.now()

        def run():
            monkey_cmd = f"adb -s {device} shell monkey -p {package_name} --throttle {throttle} -v {event_count}"
            process = subprocess.Popen(monkey_cmd, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                       text=True)

            for line in process.stdout:
                self.log_output.append(line.strip())
                self.log_output.verticalScrollBar().setValue(self.log_output.verticalScrollBar().maximum())

                if "CRASH" in line:
                    self.crash_count += 1

            self.test_end_time = datetime.now()
            self.progress_bar.setValue(100)
            self.log_output.append("✅ Monkey 测试完成")
            self.start_button.setEnabled(True)

        thread = threading.Thread(target=run)
        thread.start()

    def show_crash_chart(self):
        """ 显示崩溃统计图 """
        plt.figure(figsize=(6, 4))
        plt.bar(["崩溃次数"], [self.crash_count], color="red")
        plt.xlabel("事件")
        plt.ylabel("次数")
        plt.title("Monkey 测试崩溃统计")
        plt.show()

    def export_results(self):
        """ 导出测试结果（崩溃率、测试时间） """
        if self.test_start_time and self.test_end_time:
            duration = (self.test_end_time - self.test_start_time).total_seconds()
            crash_rate = self.crash_count / max(1, int(self.event_input.text().strip())) * 100

            file_path, _ = QFileDialog.getSaveFileName(self, "保存测试结果", "", "CSV 文件 (*.csv)")
            if file_path:
                with open(file_path, mode="w", newline="") as file:
                    writer = csv.writer(file)
                    writer.writerow(["测试开始时间", "测试结束时间", "测试时长（秒）", "崩溃次数", "崩溃率 (%)"])
                    writer.writerow(
                        [self.test_start_time, self.test_end_time, duration, self.crash_count, f"{crash_rate:.2f}"])
                self.log_output.append(f"📄 测试结果已保存到 {file_path}")

    def export_log(self):
        """ 导出日志 """
        log_text = self.log_output.toPlainText()
        file_path, _ = QFileDialog.getSaveFileName(self, "保存日志", "", "文本文件 (*.txt)")
        if file_path:
            with open(file_path, mode="w") as file:
                file.write(log_text)
            self.log_output.append(f"📄 日志已保存到 {file_path}")


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MonkeyTester()
    window.show()
    sys.exit(app.exec())
