# openai循环问答工具
import os
import sys
import threading
import time
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout,
    QTextEdit, QPushButton, QLabel, QComboBox, QCheckBox, QSpinBox
)
from PySide6.QtCore import Qt, Signal, QObject
from PySide6.QtGui import QTextCursor
from openai import OpenAI

# OpenAI 客户端，自动读取环境变量 OPENAI_API_KEY
client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

# 支持的模型列表
MODEL_OPTIONS = [
    "gpt-4o-mini",
    "gpt-4o",
    "gpt-4.1",
    "gpt-4.1-mini",
    "gpt-3.5-turbo"
]


class WorkerSignals(QObject):
    partial = Signal(str)
    finished = Signal(str)
    error = Signal(str)


class AskWorker(threading.Thread):
    def __init__(self, question, model, keep_running, interval, signals):
        super().__init__()
        self.question = question
        self.model = model
        self.keep_running = keep_running
        self.interval = interval
        self.signals = signals
        self._stop_flag = False

    def stop(self):
        self._stop_flag = True

    def run(self):
        while not self._stop_flag:
            try:
                response_text = ""
                stream = client.chat.completions.create(
                    model=self.model,
                    messages=[{"role": "user", "content": self.question}],
                    stream=True
                )
                for chunk in stream:
                    if self._stop_flag:
                        break
                    delta = chunk.choices[0].delta.content
                    if delta:
                        response_text += delta
                        self.signals.partial.emit(delta)
                self.signals.finished.emit("--- 回答完成 ---\n")
            except Exception as e:
                self.signals.error.emit(f"[错误] 请求失败：{e}\n")

            if not self.keep_running or self._stop_flag:
                break
            time.sleep(self.interval)


class OpenAIGui(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("OpenAI 循环问答工具")
        self.resize(800, 600)

        layout = QVBoxLayout()

        # 模型选择
        model_layout = QHBoxLayout()
        model_layout.addWidget(QLabel("选择模型:"))
        self.model_combo = QComboBox()
        self.model_combo.addItems(MODEL_OPTIONS)
        self.model_combo.setCurrentText("gpt-4o-mini")
        model_layout.addWidget(self.model_combo)
        layout.addLayout(model_layout)

        # 输入框 + 清空按钮
        input_layout = QHBoxLayout()
        self.input_edit = QTextEdit()
        self.input_edit.setPlaceholderText("在这里输入你的问题")
        input_layout.addWidget(self.input_edit)

        self.clear_button = QPushButton("清空")
        self.clear_button.clicked.connect(self.clear_all)
        input_layout.addWidget(self.clear_button)
        layout.addLayout(input_layout)

        # 输出框
        self.output_edit = QTextEdit()
        self.output_edit.setReadOnly(True)
        layout.addWidget(self.output_edit)

        # 控制按钮
        control_layout = QHBoxLayout()
        self.loop_checkbox = QCheckBox("循环询问")
        control_layout.addWidget(self.loop_checkbox)

        control_layout.addWidget(QLabel("间隔(s):"))
        self.interval_spin = QSpinBox()
        self.interval_spin.setRange(1, 3600)
        self.interval_spin.setValue(5)
        control_layout.addWidget(self.interval_spin)

        self.start_button = QPushButton("开始")
        self.start_button.clicked.connect(self.on_start)
        control_layout.addWidget(self.start_button)

        self.stop_button = QPushButton("停止")
        self.stop_button.clicked.connect(self.on_stop)
        control_layout.addWidget(self.stop_button)

        layout.addLayout(control_layout)

        self.setLayout(layout)

        self.worker = None

    def clear_all(self):
        self.input_edit.clear()
        self.output_edit.clear()

    def on_start(self):
        question = self.input_edit.toPlainText().strip()
        if not question:
            self.output_edit.append("[提示] 问题不能为空\n")
            return

        model = self.model_combo.currentText()
        keep_running = self.loop_checkbox.isChecked()
        interval = self.interval_spin.value()

        signals = WorkerSignals()
        signals.partial.connect(self.append_partial)
        signals.finished.connect(self.append_output)
        signals.error.connect(self.append_output)

        self.worker = AskWorker(question, model, keep_running, interval, signals)
        self.worker.start()

    def on_stop(self):
        if self.worker:
            self.worker.stop()
            self.worker = None
            self.output_edit.append("--- 已停止 ---\n")

    def append_partial(self, text):
        cursor = self.output_edit.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        cursor.insertText(text)
        self.output_edit.setTextCursor(cursor)
        self.output_edit.ensureCursorVisible()

    def append_output(self, text):
        self.output_edit.append(text)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    win = OpenAIGui()
    win.show()
    sys.exit(app.exec())