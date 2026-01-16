
import re
import json
from datetime import datetime

# 日志文件路径
log_file = '/Users/admin/TestLog/log_analysis/Google-Pixel-6a-Android-13_2025-06-20_154639.txt'

# 整个文件读取为文本
with open(log_file, 'r', encoding='utf-8') as f:
    raw_text = f.read()

# 切分为每个日志块（以 `},\n{` 为边界）
raw_entries = re.split(r'\},\s*\{', raw_text)

# 添加前后大括号修复每个块的边界（保持结构完整）
entries = [('{'+entry+'}' if not entry.startswith('{') else entry) for entry in raw_entries]
entries = [(entry+'}' if not entry.endswith('}') else entry) for entry in entries]

event_pattern = re.compile(r'Logging event: origin=app,name=([\w\d_]+),')
timestamp_pattern = re.compile(r'"timestamp"\s*:\s*{\s*"seconds"\s*:\s*"?(.*?)"?\s*}')

event_list = []
event_time_map = []

for i, block in enumerate(entries):
    # 提取事件名
    event_match = event_pattern.search(block)
    if event_match:
        event_name = event_match.group(1)

        # 提取 timestamp
        ts_match = timestamp_pattern.search(block)
        if ts_match:
            ts_raw = ts_match.group(1).strip()
            # 格式化 timestamp，包含毫秒
            if ts_raw.isdigit():
                timestamp = datetime.fromtimestamp(int(ts_raw)).strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]  # 保留毫秒
            else:
                timestamp = ts_raw
            event_list.append(event_name)
            event_time_map.append({f"上报时间：{timestamp}": f"埋点名称：{event_name}"})

# 去重事件名（保持顺序）
event_list = list(dict.fromkeys(event_list))

# ✅ 输出
print("✅ 事件名列表:")
print(event_list)
print("\n✅ 统计下每个事件上报的次数")
print(json.dumps(dict(zip(event_list, [event_time_map.count(event) for event in event_list])), indent=2, ensure_ascii=False))

print("\n✅ 事件时间映射列表:")
print(json.dumps(event_time_map, indent=2, ensure_ascii=False))


