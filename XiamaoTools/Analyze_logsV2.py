# 这里代码的逻辑适用于从Android Studio里面导出.logcat文件的情况
import re
import json
import os
from datetime import datetime, timedelta
from collections import Counter

# 指定目录
log_dir = '/Users/admin/TestLog/log_analysis/'

# 需求中的埋点事件名称
product_requirement_event_name = [
    "Loading_Page_Show",
    "Main_Page_Show",
    "All_File_Request",
    "All_File_Success",
    "PDF_Read_Page_Show",
    "More_Popup_Show",
    "PDF_Create_Popup_Show",
    "Scan_Page_Show",
    "PDF_Image_Page_Show",
    "Image_PDF_Page_Show",
    "PDF_Image_Converting",
    "PDF_Image_Convert_Success",
    "Image_PDF_Converting",
    "Image_PDF_Convert_Success",
    "IV_Show",
    "RV_Show"
]


def get_latest_file(directory):
    """获取目录下修改时间最新的 .logcat 文件"""
    log_files = [f for f in os.listdir(directory) if f.endswith('.logcat')]
    if not log_files:
        raise FileNotFoundError("目录中未找到 .logcat 文件")

    latest_file = max(
        log_files,
        key=lambda f: os.path.getmtime(os.path.join(directory, f))
    )
    return os.path.join(directory, latest_file)


def restore_unicode_escapes(content):
    """还原 Unicode 转义字符"""
    return (content
            .replace(r'\u003d', '=')
            .replace(r'\u0026', '&')
            .replace(r'\u003c', '<')
            .replace(r'\u003e', '>')
            .replace(r'\u0022', '"')
            )


def convert_timestamp_block(match):
    """转换 timestamp 格式为北京时间"""
    seconds = int(match.group(1))
    nanos = int(match.group(2))
    dt = datetime.utcfromtimestamp(seconds) + timedelta(hours=8, milliseconds=nanos / 1_000_000)
    dt_str = dt.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]  # 保留到毫秒
    return f'"timestamp": {{\n  "seconds": "{dt_str}"\n}}'


def process_log(content):
    """处理日志内容"""
    content = restore_unicode_escapes(content)
    content = re.sub(
        r'"timestamp":\s*\{\s*"seconds":\s*(\d+),\s*"nanos":\s*(\d+)\s*\}',
        convert_timestamp_block,
        content
    )
    return content


def check_event_names(event_list):
    """判断事件名是否在需求列表中，统计在列表内和缺少的事件"""
    # 检查参数是否为列表且不为空
    if not isinstance(event_list, list) or not event_list:
        return [], [], []

    in_event_list = [event for event in event_list if event in product_requirement_event_name]
    missing_events = [event for event in product_requirement_event_name if event not in event_list]

    return in_event_list, missing_events


def parse_log_file(txt_file):
    """解析生成的 .txt 文件并提取事件信息"""
    with open(txt_file, 'r', encoding='utf-8') as f:
        raw_text = f.read()

    raw_entries = re.split(r'\},\s*\{', raw_text)
    entries = [('{' + entry + '}' if not entry.startswith('{') else entry) for entry in raw_entries]
    entries = [(entry + '}' if not entry.endswith('}') else entry) for entry in entries]

    event_pattern = re.compile(r'Logging event: origin=app,name=([\w\d_]+),')
    timestamp_pattern = re.compile(r'"timestamp"\s*:\s*{\s*"seconds"\s*:\s*"?(.*?)"?\s*}')

    event_list = []
    event_time_map = []

    for block in entries:
        event_match = event_pattern.search(block)
        if event_match:
            event_name = event_match.group(1)
            ts_match = timestamp_pattern.search(block)
            if ts_match:
                ts_raw = ts_match.group(1).strip()
                if ts_raw.isdigit():
                    timestamp = datetime.fromtimestamp(int(ts_raw)).strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
                else:
                    timestamp = ts_raw
                event_list.append(event_name)
                event_time_map.append({f"上报时间：{timestamp}": f"埋点名称：{event_name}"})

    # 使用 Counter 统计事件出现次数
    event_counts = Counter(event_list)

    # 检查事件名是否在需求列表中
    in_event_list, missing_events = check_event_names(list(event_counts.keys()))

    # 输出结果
    print("✅ 事件名列表(去重的):")
    print(list(event_counts.keys()))
    print("✅ 事件名列表(不去重的):")
    print(event_list)
    print("\n✅ 统计下每个事件上报的次数")
    print(json.dumps(dict(event_counts), indent=2, ensure_ascii=False))
    print("\n✅ 事件时间映射列表:")
    print(json.dumps(event_time_map, indent=2, ensure_ascii=False))
    print("\n✅ 日志里面查询到的已上报埋点事件是:")
    print(in_event_list)
    print("\n✅ 日志里面查询到的没有上报埋点事件是:")
    print(missing_events)


# 主流程
if __name__ == "__main__":
    # 获取最新文件
    input_file = get_latest_file(log_dir)
    print(f"✅ 找到最新文件：{input_file}")

    # 生成输出文件路径（使用当前日期时间命名）
    current_time = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    output_file = os.path.join(log_dir, f"{current_time}.txt")

    # 处理日志文件
    with open(input_file, 'r', encoding='utf-8') as f:
        raw = f.read()

    processed = process_log(raw)

    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(processed)

    print(f"✅ 日志时间转换已完成，生成文件：{output_file}")

    # 确保 .txt 文件生成完成后再解析
    import time

    time.sleep(1)  # 短暂等待，确保文件写入完成
    while not os.path.exists(output_file) or os.path.getsize(output_file) == 0:
        time.sleep(0.1)  # 等待直到文件存在且非空
    print(f"✅ 确认 {output_file} 已生成，准备解析")

    # 解析生成的 .txt 文件
    parse_log_file(output_file)