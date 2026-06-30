"""检查应用是否支持16 KB内存分页大小"""
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile


def find_readelf():
    """自动查找 readelf 可执行文件"""
    candidates = [
        "/opt/homebrew/opt/binutils/bin/readelf",  # Homebrew
        "readelf"  # 系统 PATH
    ]
    for cmd in candidates:
        if shutil.which(cmd):
            return shutil.which(cmd)
    print("❌ 未找到 readelf，请先安装 binutils (brew install binutils)")
    sys.exit(1)


def check_elf_alignment(readelf_cmd, so_bytes, so_name):
    """用 readelf 检查 ELF 内部 LOAD 段对齐"""
    tmp_fd, tmp_path = tempfile.mkstemp(suffix=".so")
    os.write(tmp_fd, so_bytes)
    os.close(tmp_fd)

    try:
        output = subprocess.check_output([readelf_cmd, "-l", tmp_path], text=True)
        for line in output.splitlines():
            if "LOAD" in line and "Align" in line:
                parts = line.split()
                if "Align" in parts:
                    align_index = parts.index("Align")
                    align_value = parts[align_index + 1].strip()
                    if align_value == "0x1000":  # 4KB
                        return False
        return True
    except Exception as e:
        print(f"⚠️ ELF 检查失败 {so_name}: {e}")
        return True
    finally:
        os.remove(tmp_path)


def scan_apk(apk_path):
    readelf_cmd = find_readelf()

    if not os.path.exists(apk_path):
        print(f"❌ 文件不存在: {apk_path}")
        sys.exit(1)

    bad_files = []
    total_so = 0

    with zipfile.ZipFile(apk_path, "r") as z:
        for zipinfo in z.infolist():
            if zipinfo.filename.endswith(".so"):
                total_so += 1
                so_name = zipinfo.filename

                # 1. 检查 zip entry 对齐（local header 偏移）
                zip_offset = zipinfo.header_offset
                zip_aligned = (zip_offset % (16 * 1024) == 0)

                # 2. 取出 .so 内容，检查 ELF LOAD 段对齐
                so_bytes = z.read(zipinfo.filename)
                elf_aligned = check_elf_alignment(readelf_cmd, so_bytes, so_name)

                # 3. 汇总判断
                if not elf_aligned:
                    bad_files.append((so_name, "4 KB LOAD section alignment, but 16 KB is required"))
                elif not zip_aligned:
                    bad_files.append((so_name, "4 KB zip alignment, but 16 KB is required"))

    # === 输出结果 ===
    print("\n====== 检测结果 ======")
    if bad_files:
        print(f"❌ 共检测 {total_so} 个 .so 文件，其中 {len(bad_files)} 个不符合 16KB 要求：\n")
        for bf, reason in bad_files:
            print(f"   - {bf} -> ⚠️ {reason}")
    else:
        print(f"✅ 共检测 {total_so} 个 .so 文件，全部符合 16KB 对齐要求，测试通过！")


if __name__ == "__main__":
    # apk_file_path = r"/Users/admin/Downloads/Mixoo_v2.2.1.apk"
    apk_file_path = r"/Users/admin/Downloads/Track Phone By Clap -1.0.5.apk"
    scan_apk(apk_file_path)
