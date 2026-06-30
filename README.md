# XiamaoProject

Android 自动化测试与工具集合项目，基于 Python 3.12，包含 ADB / Appium / UIAutomator2 相关工具脚本。

## 目录结构

```text
XiamaoProject
├── XiamaoTools/        # 主工具集（安装、ADB、自动化脚本等）
├── XiaomaoNewTools/    # 新增的 Python 3.12 自动化工具
├── stability_runner/   # APK/AAB Android 稳定性回归测试 CLI
├── tests/              # 自动化测试用例
├── requirements.txt    # 项目依赖
└── README.md
```

## Android 稳定性测试工具

`stability_runner` 是一套面向 APK/AAB 的自动化稳定性回归工具，优先兼容 macOS + adb + Python 3.10+。工具默认读取 `~/Downloads` 下最新的 `.apk` 或 `.aab`，自动解析包名、安装应用、清理旧包和 logcat，运行 Monkey 或 Fastbot，并输出 JSON / Markdown / HTML 报告。

### 模块结构

```text
stability_runner/
├── config_loader.py      # CLI 参数与默认路径
├── installer.py          # APK/AAB 包名解析、卸载、安装
├── device_info.py        # adb 设备选择、设备信息采集、logcat 清理
├── logcat_collector.py   # 实时 logcat 采集
├── monkey_runner.py      # Monkey 命令构建与执行
├── fastbot_runner.py     # Fastbot 检测、执行与设备端日志拉取
├── perf_collector.py     # CPU / RSS / PSS / meminfo / gfxinfo 采样
├── crash_analyzer.py     # crash / tombstone / system_server 线索分析
├── anr_analyzer.py       # ANR 时间点和原因摘要
├── report_generator.py   # JSON / Markdown / HTML 报告
└── __main__.py           # python -m stability_runner 入口
```

### 依赖准备

```bash
python3 -m pip install -r requirements.txt
adb devices
```

AAB 安装需要 `bundletool.jar`。默认读取 `/Users/admin/bundletool.jar`，也可以通过参数或环境变量指定：

```bash
export BUNDLETOOL_JAR=/path/to/bundletool.jar
```

Fastbot 为可选能力。若设备端已存在 `/sdcard/monkeyq.jar`、`/sdcard/framework.jar`、`/sdcard/fastbot-thirdpart.jar`，工具会自动运行；否则跳过并在日志中提示原因。

### 使用方式

读取 `~/Downloads` 最新 APK/AAB，运行 5 分钟 Monkey：

```bash
python3 -m stability_runner --minutes 5 --mode monkey
```

指定 APK/AAB 和包名，运行 10 分钟：

```bash
python3 -m stability_runner --apk /path/app.apk --package-name com.example.app --minutes 10 --mode monkey
```

指定事件间隔、seed 和事件比例：

```bash
python3 -m stability_runner \
  --apk /path/app.aab \
  --minutes 20 \
  --throttle 500 \
  --seed 20260513 \
  --pct-touch 60 \
  --pct-motion 20 \
  --pct-appswitch 10
```

尝试 Monkey + Fastbot：

```bash
python3 -m stability_runner --apk /path/app.apk --minutes 10 --mode both
```

如果系统里 `python` 已指向 Python 3.10+，也可以按用户习惯运行：

```bash
python -m stability_runner --apk xxx.apk --minutes 10 --mode monkey
```

### 输出目录

所有产物保存到：

```text
~/TestLog/android_stability/YYYYMMDD_HHMMSS_<packageName>/
```

核心文件：

```text
runner.log
logs/logcat.txt
logs/monkey_output.txt
logs/crash_androidruntime.txt
logs/fastbot_output.txt
logs/fastbot_skipped.txt
perf/perf_samples.csv
perf/meminfo_*.txt
perf/gfxinfo_*.txt
device/device_info.txt
tombstones/before.txt
tombstones/after.txt
tombstones/new/
report.json
report.md
report.html
```

### 报告结论

报告会自动汇总 Crash、ANR、Crash 堆栈摘要、ANR 时间点和原因摘要、tombstone / system_server 线索、高 CPU / 高内存样本，以及关键异常关键词统计。

Crash / ANR 分析只统计本次测试运行窗口内的日志，并要求日志归属目标包。tombstone 不会仅凭 Monkey 输出里的 `New tombstone found` 判定为本次 crash；工具会在测试前后记录 `/data/tombstones` 快照，只拉取并分析本次新增或变化的 tombstone，且 tombstone 正文 `Cmdline` 必须匹配目标包才计为 crash。

如果发生 Java crash，工具会把本次运行窗口内目标包的完整 `AndroidRuntime FATAL EXCEPTION` block 额外保存到 `logs/crash_androidruntime.txt`，便于直接贴给研发。Native crash 详情优先查看 `tombstones/new/` 中对应文件。

默认阈值：CPU 单次采样 `>= 80%` 计为高 CPU；PSS `>= 800MB` 计为高内存。阈值当前在 `report_generator.py` 中集中定义，后续可以扩展为 CLI 参数。

### 最小验证

离线验证分析和报告链路：

```bash
python3 -m py_compile stability_runner/*.py
python3 -m stability_runner.self_check
```

真实设备最小验证：

```bash
adb devices
python3 -m stability_runner --apk /path/app.apk --minutes 1 --throttle 500 --mode monkey
```

### 常见问题

- `python: command not found`：使用 `python3 -m stability_runner ...`。
- `未发现在线 adb 设备`：确认 USB 调试已授权，执行 `adb devices` 应显示 `device`。
- `发现多个在线设备`：增加 `--serial <device_id>`。
- `无法解析 AAB 包名`：确认 `bundletool.jar` 可用，或通过 `--package-name` 显式传入包名。
- `AAB 安装需要 bundletool.jar`：通过 `--bundletool /path/bundletool.jar` 或 `BUNDLETOOL_JAR` 指定。
- `跳过 Fastbot`：说明设备端 Fastbot jar 未配置；Monkey 流程不受影响。
