import os
import subprocess
from datetime import datetime

def compress_video(input_path):
    if not os.path.isfile(input_path):
        print(f"文件不存在: {input_path}")
        return

    # 目标目录
    output_dir = "/Users/admin/Downloads"
    os.makedirs(output_dir, exist_ok=True)

    # 生成时间戳文件名
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_path = os.path.join(output_dir, f"{timestamp}_compressed.mp4")

    print(f"正在压缩视频，请稍等...")
    cmd = [
        "ffmpeg",
        "-i", input_path,
        "-vcodec", "libx264",
        "-crf", "25",  # 数字越大压缩率越高，质量越低（建议范围 23-30）
        output_path
    ]

    result = subprocess.run(cmd)

    if result.returncode == 0 and os.path.exists(output_path):
        print(f"压缩完成：{output_path}")
    else:
        print("压缩失败，请检查 ffmpeg 是否正确安装或参数是否错误。")

if __name__ == "__main__":
    video_path = "/Users/admin/Downloads/IMG_1451.MOV"
    compress_video(video_path)
