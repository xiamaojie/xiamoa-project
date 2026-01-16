# 这里代码适用adb logcat命令行日志的情况
import json
import os
import re
from collections import Counter
from datetime import datetime

# 指定目录
log_dir = '/Users/admin/TestLog/log_analysis/'

# 需求中的埋点事件名称
product_requirement_event_name = [
    "access_permission_success",
    "access_permission_fail",
    "battery_page_show",
    "explore_page_show",
    "battery_subtab_click",
    "batteryicon_item_click",
    "customize_page_show",
    "apply_click",
    "apply_success",
    "apply_fail",
    "unlock_button_click",
    "explore_status_bar_click",
    "explore_notch_click",
    "explore_tutorial_click",
    "statusbar_page_show",
    "statusbar_colortemplate_click",
    "wifi_click",
    "signal_click",
    "airplane_click",
    "hotspot_click",
    "ringer_click",
    "data_click",
    "emotion_click",
    "animation_click",
    "charge_click",
    "rv_show",
    "iv_show_back_main",
    "iv_show_click_battery",
    "iv_show_enter_explore",
    "iv_show_status_bar",
    "iv_show_notch",
    "iv_show_tutorial",
    "iv_show_color_template",
    "iv_show_customize_icon"
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


def process_log(content):
    """处理日志内容（移除旧的 Unicode 和 timestamp 转换逻辑）"""
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

    # 按行分割日志
    lines = raw_text.split('\n')
    event_list = []
    event_time_map = []

    for i in range(len(lines)):
        # 匹配事件
        event_match = re.search(r'Logging event: origin=app,name=([\w\d_]+),', lines[i])
        if event_match:
            event_name = event_match.group(1)
            # 获取往上1行的日期字段作为键
            if i > 0:
                timestamp_line = lines[i - 1].strip()
                # 提取日期时间 (格式: MM-DD HH:MM:SS.SSS)
                timestamp_match = re.match(r'(\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3})', timestamp_line)
                if timestamp_match:
                    timestamp = timestamp_match.group(1)
                    event_list.append(event_name)
                    event_time_map.append({f"上报时间：{timestamp}": f"埋点名称：{event_name}"})
                else:
                    # 如果没有匹配到时间，使用当前行时间
                    timestamp_match = re.match(r'(\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3})', lines[i])
                    if timestamp_match:
                        timestamp = timestamp_match.group(1)
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
    print("\n✅ 根据日志对比需求文档，查询到已上报埋点事件是:")
    print(in_event_list)
    print("\n✅ 根据日志对比需求文档，查询到未上报埋点事件是:")
    print(missing_events)
    # 判断如果没有缺失的事件，则打印测试通过
    if not missing_events:
        print("测试通过，埋点已全部上报")


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