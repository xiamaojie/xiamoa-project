#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
极简图片内容识别脚本
功能：传入图片路径，直接返回content字符串
使用：content = get_image_content(image_path); print(content)
"""

import base64
from PIL import Image
from io import BytesIO
from openai import OpenAI
import os


def get_image_content(image_path):
    """
    极简图片内容识别

    Args:
        image_path: 图片文件路径

    Returns:
        str: 识别的完整内容，或None（失败）
    """
    # 检查文件是否存在
    if not os.path.exists(image_path):
        return None

    # 初始化客户端
    client = OpenAI()

    # 编码图像
    with Image.open(image_path) as image:
        buffered = BytesIO()
        image.save(buffered, format="JPEG", quality=90)
        base64_image = base64.b64encode(buffered.getvalue()).decode()

    # 简洁的全面内容提取提示
    prompt = """提取图片中的所有可见内容，包括：
- 页面标题
- 表单字段名称和占位符
- 按钮文本
- 验证码数字
- 所有其他文本

格式：
标题: [标题]
表单: [字段1], [字段2], ...
按钮: [按钮1], [按钮2], ...
验证码: [4位数字]
其他: [其他文本]
"""

    messages = [{
        "role": "user",
        "content": [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}}
        ]
    }]

    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=messages,
            max_tokens=500,
            temperature=0.3
        )
        return response.choices[0].message.content.strip()
    except:
        return None


# 主函数：传入路径，打印content
def main(image_path):
    """主函数：传入图片路径，打印识别内容"""
    content = get_image_content(image_path)
    if content:
        print(content)
        return content
    else:
        print("识别失败")
        return None


# 使用示例
if __name__ == "__main__":
    # 直接使用您的示例路径
    image_path = "/Users/admin/Downloads/Snipaste_2025-09-22_16-59-15.png"
    main(image_path)