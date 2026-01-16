import json
import os
import re
from datetime import datetime

# 指定目录
log_dir = '/Users/admin/TestLog/log_analysis/'

# 需求中的埋点事件名称和属性
product_requirement_event_name = [
    "Loading_Page_Show",
    "JesusHug_Page_Show",
    {"Upload_Page_Show": ["Type"]},
    {"Loading_Page_Show": ["Type"]},
    {"Make_Page_Success": ["time"]},
    {"Make_Page_Fail": ["Reason"]},
    {"Result_Page_Show": ["Type"]},
    "AI_Page_Show",
    "Pixar_Page_Show",
    "Ghibli_Page_Show",
    "IV_Show",
    "RV_Popup_Show",
    "RV_Show",
    "Report_Page_Show",
    {"Report_Success": ["Reason"]}
]


def get_latest_file(directory):
    """获取目录下修改时间最新的 .logcat 文件"""
    log_files = [f for f in os.listdir(directory) if f.endswith('.logcat')]
    if not log_files:
        raise FileNotFoundError("目录中未找到 .logcat 文件")
    latest_file = max(log_files, key=lambda f: os.path.getmtime(os.path.join(directory, f)))
    return os.path.join(directory, latest_file)


def process_log(content):
    """处理日志内容，过滤无关行"""
    lines = content.split('\n')
    filtered_lines = [line for line in lines if 'V/FA-SVC' in line and 'origin=app,name=' in line]
    return '\n'.join(filtered_lines)


def parse_log_file(txt_file):
    """解析生成的 .txt 文件并提取事件信息并对比"""
    with open(txt_file, 'r', encoding='utf-8') as input_file:
        raw_text = input_file.read()

    # 按行分割日志
    lines = raw_text.split('\n')
    reported_events = []  # 存储实际上报的事件
    event_data = {}  # 存储事件及其属性值

    # 初始化 event_data
    for event in product_requirement_event_name:
        if isinstance(event, str):
            event_data[event] = []
        elif isinstance(event, dict):
            event_name = list(event.keys())[0]
            event_data[event_name] = []

    # 解析日志并提取事件
    for line in lines:
        for event_config in product_requirement_event_name:
            if isinstance(event_config, str):
                pattern = r'origin=app,name=' + re.escape(event_config) + r'[, ]'
                if re.search(pattern, line, re.IGNORECASE) and event_config not in reported_events:
                    reported_events.append(event_config)
            elif isinstance(event_config, dict):
                event_name = list(event_config.keys())[0]
                attributes = event_config[event_name]
                pattern = r'origin=app,name=' + re.escape(event_name) + r'[, ]'
                if re.search(pattern, line, re.IGNORECASE):
                    if event_name not in [e for e in reported_events if isinstance(e, str)]:
                        reported_events.append(event_name)
                    params_match = re.search(r'params=Bundle\[\{(.+?)\}\]', line)
                    if params_match:
                        params_str = params_match.group(1)
                        event_values = {}
                        for attr in attributes:
                            attr_pattern = r'' + re.escape(attr) + r'=([^,}]+?)(?=[,}])'
                            attr_match = re.search(attr_pattern, params_str, re.IGNORECASE)
                            event_values[attr] = attr_match.group(1).strip() if attr_match else "null"
                        if event_values:
                            event_data[event_name].append(event_values)

    # 对比需求与实际结果
    reported_set = set()
    attribute_null_set = set()
    for item in reported_events:
        reported_set.add(item)
    for event_name, values in event_data.items():
        if values and any(isinstance(v, dict) for v in values):
            # 检查属性是否全为 null
            all_null = all(all(val.get(attr, "null") == "null" for attr in values[0].keys()) for val in values)
            if all_null:
                attribute_null_set.add(event_name)
            elif not all_null:
                reported_set.add(event_name)

    # 统计需求中的所有事件
    required_events = set()
    for event in product_requirement_event_name:
        if isinstance(event, str):
            required_events.add(event)
        elif isinstance(event, dict):
            required_events.add(list(event.keys())[0])

    # 分类
    reported_events_list = sorted(list(reported_set - attribute_null_set))
    unreported_events = sorted(list(required_events - reported_set - attribute_null_set))
    attribute_null_events = sorted(list(attribute_null_set))

    # 构建最终结果并去重属性值
    result = reported_events_list.copy()
    for event_name, values in event_data.items():
        if values and any(isinstance(v, dict) for v in values):
            attr_list = list(values[0].keys()) if values else []
            if attr_list and event_name in reported_set:
                # 去重属性值
                unique_values = {}
                for attr in attr_list:
                    unique_vals = list({d.get(attr, "null") for d in values if d.get(attr, "null") != "null"})
                    if unique_vals:
                        unique_values[attr] = unique_vals
                    else:
                        unique_values[attr] = ["null"]
                # 构建去重后的格式化值
                max_len = max(len(v) for v in unique_values.values()) if unique_values else 0
                formatted_values = [
                    {attr: unique_values[attr][i] if i < len(unique_values[attr]) else "null" for attr in attr_list} for
                    i in range(max_len)]
                result.append({event_name: formatted_values})

    # 检查是否所有事件都上报且属性无 null
    all_events_reported = len(unreported_events) == 0 and len(attribute_null_events) == 0
    if all_events_reported:
        print("✅ 测试通过，埋点已全部上报")

    # 输出结果
    print("✅ 最终输出结果:")
    print(json.dumps(result, indent=2, ensure_ascii=False))
    print("\n✅ 已上报的事件:")
    print(json.dumps(reported_events_list, indent=2, ensure_ascii=False))
    print("\n✅ 未上报的事件:")
    print(json.dumps(unreported_events, indent=2, ensure_ascii=False))
    print("\n✅ 有埋点属性未上报的事件:")
    print(json.dumps([{event: product_requirement_event_name[
        [i for i, e in enumerate(product_requirement_event_name) if isinstance(e, dict) and list(e.keys())[0] == event][
            0]][event]} for event in attribute_null_events], indent=2, ensure_ascii=False))


# 主流程
if __name__ == "__main__":
    # 获取最新文件
    input_file = get_latest_file(log_dir)
    print(f"✅ 找到最新文件：{input_file}")

    # 生成输出文件路径（使用当前日期时间命名）
    current_time = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    output_file = os.path.join(log_dir, f"{current_time}.txt")

    # 处理日志文件
    with open(input_file, 'r', encoding='utf-8') as input_file_obj:
        raw = input_file_obj.read()

    processed = process_log(raw)

    with open(output_file, 'w', encoding='utf-8') as output_file_obj:
        output_file_obj.write(processed)

    print(f"✅ 日志时间转换已完成，生成文件：{output_file}")

    # 确保 .txt 文件生成完成后再解析
    import time

    time.sleep(1)  # 短暂等待，确保文件写入完成
    while not os.path.exists(output_file) or os.path.getsize(output_file) == 0:
        time.sleep(0.1)  # 等待直到文件存在且非空
    print(f"✅ 确认 {output_file} 已生成，准备解析")

    # 解析生成的 .txt 文件
    parse_log_file(output_file)
