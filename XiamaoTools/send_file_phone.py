"""模拟买量，测试手机上没有安装飞书的时候，可以用"""
import os
import subprocess


def push_file_to_device(local_file_path, remote_dir="/sdcard/Download/"):
    """
        将电脑文件推送到连接的 Android 设备上，并刷新媒体库以使文件可见。
        参数:
            file_path (str): 要推送的本地文件路径
            remote_dir (str): 文件在设备上的目标目录，默认为 /sdcard/Download/
        """
    if not os.path.isfile(local_file_path):
        print(f"❌ 本地文件不存在: {local_file_path}")
        return

    filename = os.path.basename(local_file_path)
    remote_path = os.path.join(remote_dir, filename)

    # 执行 adb push
    print(f"📤 正在推送文件到手机: {remote_path}")
    result = subprocess.run(["adb", "push", local_file_path, remote_path], capture_output=True, text=True)
    print(result.stdout)
    if result.returncode != 0:
        print(f"❌ adb push 失败: {result.stderr}")
        return

    # 发送媒体库刷新广播
    print("🔄 正在刷新媒体库...")
    broadcast_cmd = [
        "adb", "shell", "am", "broadcast",
        "-a", "android.intent.action.MEDIA_SCANNER_SCAN_FILE",
        "-d", f"file://{remote_path}"
    ]
    result = subprocess.run(broadcast_cmd, capture_output=True, text=True)
    print(result.stdout)
    if result.returncode == 0:
        print("✅ 文件推送并刷新媒体库成功！")
        print(f"✅ 手机存放文件路径: {remote_path}")
    else:
        print(f"❌ 广播发送失败: {result.stderr}")


if __name__ == "__main__":
    # pc_file_path = "/Users/admin/Downloads/配置文件.yaml"
    pc_file_path = "/Users/admin/Downloads/MyOdoSdk 音频广告接入文档.pdf"
    push_file_to_device(pc_file_path)
