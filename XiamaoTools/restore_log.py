
import re
from datetime import datetime, timedelta

# ✅ 使用你的路径
input_file = '/Users/admin/TestLog/log_analysis/Google-Pixel-6a-Android-13_2025-06-20_154639.logcat'
output_file = '/Users/admin/TestLog/log_analysis/Google-Pixel-6a-Android-13_2025-06-20_154639.txt'

def restore_unicode_escapes(content):
    return (content
        .replace(r'\u003d', '=')
        .replace(r'\u0026', '&')
        .replace(r'\u003c', '<')
        .replace(r'\u003e', '>')
        .replace(r'\u0022', '"')
    )

def convert_timestamp_block(match):
    seconds = int(match.group(1))
    nanos = int(match.group(2))

    # 转换为北京时间（+8 时区）+ 纳秒精度
    dt = datetime.utcfromtimestamp(seconds) + timedelta(hours=8, milliseconds=nanos / 1_000_000)
    dt_str = dt.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]  # 保留到毫秒

    return f'"timestamp": {{\n  "seconds": "{dt_str}"\n}}'

def process_log(content):
    content = restore_unicode_escapes(content)

    # 匹配 timestamp 对象并格式化输出
    content = re.sub(
        r'"timestamp":\s*\{\s*"seconds":\s*(\d+),\s*"nanos":\s*(\d+)\s*\}',
        convert_timestamp_block,
        content
    )
    return content

# 主流程
if __name__ == "__main__":
    with open(input_file, 'r', encoding='utf-8') as f:
        raw = f.read()

    processed = process_log(raw)

    with open(output_file, 'w', encoding='utf-8') as f:
        f.write(processed)

    print(f"✅ 日志时间转换已完成，文件已更新：{output_file}")
