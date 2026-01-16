import subprocess

def test_bundletool_with_zsh():
    cmd = 'bundletool version'
    result = subprocess.run(
        ['zsh', '-i', '-c', cmd],  # 用-zsh -i加载 .zshrc
        capture_output=True,
        text=True
    )
    print("stdout:", result.stdout)
    print("stderr:", result.stderr)
    print("returncode:", result.returncode)

if __name__ == "__main__":
    test_bundletool_with_zsh()