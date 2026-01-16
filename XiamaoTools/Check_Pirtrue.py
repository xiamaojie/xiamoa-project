#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
页面单词拼写检查工具，通过OpenAi识别 - 输出单词检查结果，固定等宽表格版查看

"""

import os
import base64
from pathlib import Path
from PIL import Image
from io import BytesIO
from openai import OpenAI
from concurrent.futures import ThreadPoolExecutor, as_completed
import sys
from datetime import datetime
import openai as openai_module
# import os
#
# os.environ["HTTPS_PROXY"] = "http://127.0.0.1:7897"

def encode_image(image_path):
    """编码图片为base64"""
    try:
        with Image.open(image_path) as image:
            if max(image.size) > 1024:
                image.thumbnail((1024, 1024), Image.Resampling.LANCZOS)

            if image.mode != 'RGB':
                rgb_image = Image.new('RGB', image.size, (255, 255, 255))
                if image.mode == 'RGBA':
                    rgb_image.paste(image, mask=image.split()[-1])
                else:
                    rgb_image.paste(image)
                image = rgb_image

            buffered = BytesIO()
            image.save(buffered, format="JPEG", quality=85, optimize=True)
            return base64.b64encode(buffered.getvalue()).decode()
    except Exception as e:
        print(f"编码失败 {os.path.basename(image_path)}: {e}")
        return None


def check_spelling_single(client, image_path):
    """单个图片拼写检查 - 保留句子完整性"""
    filename = os.path.basename(image_path)
    print(f"🔍 检查 {filename}...")

    base64_image = encode_image(image_path)
    if not base64_image:
        print(f"⚠  {filename} 图像编码失败，跳过")
        return None

    prompt = """请分析图片中的所有英文文本，完成以下任务：

1. 保持句子完整性：不要拆分句子，保留原始的句子或短语结构
2. 检查拼写错误：找出句子中的英文单词拼写错误
3. 提供中文翻译：给出整个句子或短语的中文含义
4. 标记错误位置：在错误单词后添加 [修正建议]

请按照以下表格格式输出，不要拆分句子：

英文文本 | 拼写状态 | 中文含义
---|---|---
[完整句子1] | ✅ | [中文翻译1]
[完整句子2中的错误单词] | ❌ [建议：正确拼写] | [中文翻译2]
[完整句子3] | ✅ | [中文翻译3]

重要要求：
- 保持句子完整，不要把一句话拆成多个单词行
- 只有拼写错误的句子才需要标注修正建议
- 正确句子的状态标记为 ✅
- 使用Markdown表格格式，只输出表格内容
"""

    messages = [{
        "role": "user",
        "content": [
            {"type": "text", "text": prompt},
            {
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}
            }
        ]
    }]

    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=messages,
            max_tokens=1000,
            temperature=0.1
        )

        content = response.choices[0].message.content.strip()
        tokens_used = getattr(response.usage, 'total_tokens', 0)

        print(f"✓ {filename} 处理完成（{tokens_used} tokens）")

        correct_count = content.count('✅')
        error_count = content.count('❌')

        return {
            "filename": filename,
            "status": "success",
            "table_content": content,
            "total_sentences": correct_count + error_count,
            "correct_sentences": correct_count,
            "error_sentences": error_count,
            "error_rate": round(error_count / max(correct_count + error_count, 1), 4),
            "tokens_used": tokens_used,
            "timestamp": datetime.now().isoformat()
        }

    except Exception as e:
        error_msg = str(e)
        print(f"❌ API调用失败 {filename}: {error_msg}")
        return {
            "filename": filename,
            "status": "error",
            "error": error_msg,
            "timestamp": datetime.now().isoformat()
        }


def format_table_fixed_width(table_content, filename):
    """格式化为动态列宽表格，保证长句子不被截断"""
    # 拆分有效行
    lines = [
        line.strip()
        for line in table_content.split('\n')
        if line.strip() and '|' in line and not line.startswith('---')
    ]
    if not lines:
        return f"⚠ {filename}: 无法解析表格内容"

    # 拆分成二维数组
    rows = [[part.strip() for part in line.split('|')] for line in lines]

    # 确保每行至少有 3 列
    rows = [row[:3] + [''] * (3 - len(row)) for row in rows]

    # 计算每列最大宽度
    col_widths = [max(len(row[i]) for row in rows) for i in range(3)]

    # 构建表头
    headers = ["英文文本", "拼写状态", "中文含义"]
    header = " │ ".join(h.ljust(col_widths[i]) for i, h in enumerate(headers))
    separator = "─" * len(header)

    # 构建内容行
    content_lines = []
    for row in rows:
        english_text = row[0].ljust(col_widths[0])
        status = row[1].center(col_widths[1])
        chinese_meaning = row[2].ljust(col_widths[2])

        prefix = "❌ " if "❌" in status else "  "
        content_lines.append(f"{prefix}{english_text} │ {status} │ {chinese_meaning}")

    # 组装完整表格
    table = f"""
{'=' * len(header)}
📄 {filename} ({len(content_lines)} 行内容)
{'=' * len(header)}
{header}
{separator}
""" + "\n".join(content_lines) + f"""
{separator}
{'=' * len(header)}
"""
    return table



def process_directory_batch(directory_path, max_workers=3):
    """批量处理目录中的图片"""
    directory = Path(directory_path)

    if not directory.exists():
        print(f"❌ 目录不存在: {directory_path}")
        return None

    image_extensions = {'.png', '.jpg', '.jpeg', '.bmp', '.tiff', '.webp'}
    image_files = [
        f for f in directory.iterdir()
        if f.is_file() and f.suffix.lower() in image_extensions
    ]

    if not image_files:
        print(f"❌ 目录中没有找到图片文件: {directory_path}")
        print(f"支持格式: {', '.join(image_extensions)}")
        return None

    num_images = len(image_files)
    print(f"📸 发现 {num_images} 张图片")
    print(f"📂 目录: {directory_path}")

    try:
        client = OpenAI()
        print("✅ OpenAI客户端初始化成功")
    except Exception as e:
        print(f"❌ OpenAI初始化失败: {e}")
        return None

    results = []
    print(f"🔄 开始并行处理（{max_workers}线程）...")

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_file = {
            executor.submit(check_spelling_single, client, str(image_file)): image_file
            for image_file in image_files
        }

        completed = 0
        for future in as_completed(future_to_file):
            completed += 1
            result = future.result()
            if result:
                results.append(result)

            status_emoji = "✅" if result and result.get("status") == "success" else "❌"
            error_count = result.get("error_sentences", 0) if result else 0
            filename = result.get("filename", "unknown") if result else "unknown"
            print(f"[{completed}/{num_images}] {status_emoji} {filename} - 句子错误: {error_count}")

    successful = sum(1 for r in results if r.get("status") == "success")
    failed = len(results) - successful

    total_sentences = sum(r.get("total_sentences", 0) for r in results if r.get("status") == "success")
    total_errors = sum(r.get("error_sentences", 0) for r in results if r.get("status") == "success")

    print("\n" + "=" * 60)
    print("📊 处理完成统计")
    print("=" * 60)
    print(f"总图片数: {num_images}")
    print(f"成功处理: {successful}")
    print(f"处理失败: {failed}")
    print(f"总句子数: {total_sentences}")
    print(f"拼写错误句子: {total_errors}")
    if total_sentences > 0:
        print(f"错误率: {total_errors / total_sentences:.1%}")
    else:
        print("错误率: 无英文文本")

    return {
        "timestamp": datetime.now().isoformat(),
        "directory": str(directory_path),
        "total_images": num_images,
        "successful": successful,
        "failed": failed,
        "total_sentences": total_sentences,
        "total_errors": total_errors,
        "error_rate": round(total_errors / max(total_sentences, 1), 4),
        "results": results
    }


def print_detailed_results(results):
    """打印详细结果（固定宽度美观表格）"""
    print("\n" + "=" * 80)
    print("📋 详细检查结果")
    print("=" * 80)

    for result in results:
        if result.get("status") != "success":
            continue

        filename = result["filename"]
        error_sentences = result.get("error_sentences", 0)
        total_sentences = result.get("total_sentences", 0)

        print(f"\n📄 {filename}")
        print(f"状态: 成功 | 句子总数: {total_sentences} | 错误句子: {error_sentences}")
        print(f"错误率: {result.get('error_rate', 0):.1%}")

        # 格式化输出固定宽度表格
        formatted_table = format_table_fixed_width(result.get("table_content", ""), filename)
        print(formatted_table)

        # 错误摘要
        if error_sentences > 0:
            print(f"\n❌ 发现 {error_sentences} 个句子包含拼写错误:")
            error_lines = [line for line in result.get("table_content", "").split('\n')
                           if '❌' in line and '|' in line]
            for line in error_lines[:3]:  # 显示前3个错误
                parts = [part.strip() for part in line.split('|') if part.strip()]
                if len(parts) >= 3:
                    text = parts[0]
                    status = parts[1]
                    meaning = parts[2]
                    print(f"   • {text[:50]}... | {status} | {meaning[:30]}...")
            if len(error_lines) > 3:
                print(f"   ... 还有 {len(error_lines) - 3} 个错误")
        else:
            print("\n✅ 所有句子拼写正确")

    print("\n" + "=" * 80)


def get_latest_subdirectory(parent_dir):
    """获取parent_dir下创建时间最新的子目录路径"""
    parent = Path(parent_dir)
    subdirs = [d for d in parent.iterdir() if d.is_dir()]
    if not subdirs:
        return None
    # 按创建时间排序（新 -> 旧），取第一个
    latest_dir = max(subdirs, key=lambda d: d.stat().st_ctime)
    return str(latest_dir)


def main():
    """主函数"""
    parent_directory = "/Users/admin/TestLog/img_upload"
    print("🔍 APP页面拼写检查工具（固定宽度表格版）")
    print(f"📂 父目录: {parent_directory}")
    print("=" * 50)

    latest_directory = get_latest_subdirectory(parent_directory)
    if not latest_directory:
        print(f"❌ 错误: 目录 {parent_directory} 下没有子目录")
        return 1

    print(f"✅ 最新子目录: {latest_directory}")

    if not os.environ.get('OPENAI_API_KEY'):
        print("❌ 错误: 未设置 OPENAI_API_KEY 环境变量")
        print("💡 解决: export OPENAI_API_KEY='sk-your-key'")
        return 1

    print("✅ API密钥已设置")

    results_summary = process_directory_batch(latest_directory, max_workers=3)

    if results_summary is None:
        print("💥 处理失败")
        return 1

    print_detailed_results(results_summary["results"])

    print(f"\n🎉 检查完成！")
    return 0


if __name__ == "__main__":
    try:
        print(f"📦 OpenAI库版本: {openai_module.__version__}")
        print(f"🐍 Python版本: {sys.version.split()[0]}")
        print(f"🖼️  Pillow版本: {Image.__version__}")

        exit_code = main()
        sys.exit(exit_code)

    except KeyboardInterrupt:
        print("\n⚠  用户中断")
        sys.exit(130)
    except Exception as exc:
        print(f"\n💥 致命错误: {type(exc).__name__}: {exc}")
        import traceback

        traceback.print_exc()
        sys.exit(1)