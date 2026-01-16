import os
import subprocess
import datetime

# 是否视频压缩开关，默认为true，压缩视频
# 设置为 true ：下载后自动压缩视频
# 设置为 false：下载后不压缩视频
is_compress = True

# 要搜索的目录
dirs = [
    "/storage/emulated/O/Movies",
    "/storage/emulated/0/Movies/Screenrecord",
    "/storage/emulated/0/Movies",
    "/storage/emulated/0/Pictures/Screenshots"

]

latest_file = ""
latest_time = 0

def adb_shell(cmd):
    """运行 adb shell 命令并返回输出"""
    try:
        output = subprocess.check_output(['adb', 'shell'] + cmd, stderr=subprocess.DEVNULL)
        return output.decode().strip().replace('\r', '')
    except subprocess.CalledProcessError:
        return ""

def get_latest_file_in_dir(directory):
    """获取指定目录下最新的 .mp4 文件路径"""
    cmd = [f'ls -t {directory}/*.mp4']
    output = adb_shell(cmd)
    if output:
        return output.splitlines()[0]
    return ""

# 遍历每个目录，查找最新的 mp4 文件
for search_dir in dirs:
    newest_in_dir = get_latest_file_in_dir(search_dir)
    if newest_in_dir:
        file_time_str = adb_shell([f'stat -c %Y "{newest_in_dir}"'])
        if file_time_str.isdigit():
            file_time = int(file_time_str)
            if file_time > latest_time:
                latest_time = file_time
                latest_file = newest_in_dir

if latest_file:
    print(f"找到最新的 .mp4 文件: {latest_file}")
    download_dir = "/Users/admin/Downloads"
    os.makedirs(download_dir, exist_ok=True)

    # 拉取文件到本地
    subprocess.run(['adb', 'pull', latest_file, download_dir])

    # 加时间戳重命名
    filename_only = os.path.basename(latest_file)
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    downloaded_file = os.path.join(download_dir, f"{timestamp}_{filename_only}")
    original_path = os.path.join(download_dir, filename_only)
    os.rename(original_path, downloaded_file)

    print(f"下载完成，原文件保存到：{downloaded_file}")

    if is_compress:
        # 压缩视频
        compressed_file = downloaded_file.rsplit('.', 1)[0] + "_compressed.mp4"
        print("正在压缩视频，请稍等...")

        compress_cmd = [
            "ffmpeg", "-i", downloaded_file, "-vcodec", "libx264", "-crf", "28", compressed_file
        ]
        result = subprocess.run(compress_cmd)

        if os.path.exists(compressed_file):
            print(f"压缩完成，保存到：{compressed_file}")
            os.remove(downloaded_file)
            print(f"已删除原始未压缩的视频文件：{downloaded_file}")
            subprocess.run(["open", "-R", compressed_file])
        else:
            print("压缩失败，请检查ffmpeg是否正常安装。")
            subprocess.run(["open", "-R", downloaded_file])
    else:
        print("跳过压缩。")
        subprocess.run(["open", "-R", downloaded_file])
else:
    print("没有找到任何 .mp4 文件。")
