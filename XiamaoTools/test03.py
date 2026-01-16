
import subprocess
import re


def check_network_and_vpn_status(verbose: bool = True) -> str:
    """
    系统级网络 & VPN 状态检测（只执行一次 dumpsys connectivity）

    返回值：
        - NO_NETWORK
        - NETWORK_OK_NO_VPN
        - VPN_ON_NOT_VALIDATED
        - VPN_ON_AND_VALIDATED

    行为：
        - 不抛异常
        - 统一打印：当前网络状态: <status>
        - 在 NO_NETWORK 时说明：飞行模式或无连接
    """

    try:
        output = subprocess.check_output(
            ["adb", "shell", "dumpsys", "connectivity"],
            text=True,
            stderr=subprocess.DEVNULL
        )
    except subprocess.CalledProcessError:
        status = "NO_NETWORK"
        if verbose:
            print(f"当前网络状态: {status}")
            print("❌ 当前设备无可用网络（飞行模式或无连接）")
        return status

    # ---------- 1️⃣ 判断是否存在 Active 网络 ----------
    active_match = re.search(r"Active default network:\s*(\S+)", output)
    if not active_match or active_match.group(1) == "none":
        status = "NO_NETWORK"
        if verbose:
            print(f"当前网络状态: {status}")
            print("❌ 当前设备无可用网络（飞行模式或无连接）")
        return status

    # ---------- 2️⃣ 核心信号 ----------
    has_vpn_connected = "VPN CONNECTED" in output
    has_is_vpn = "IS_VPN" in output
    has_validated = "IS_VALIDATED" in output

    # ---------- 3️⃣ VPN 场景 ----------
    if has_vpn_connected and has_is_vpn:
        if "IS_VPN&EVER_VALIDATED&IS_VALIDATED" in output or (
            "IS_VPN" in output and "IS_VALIDATED" in output
        ):
            status = "VPN_ON_AND_VALIDATED"
            if verbose:
                print(f"当前网络状态: {status}")
                print("🌍 VPN 正常，已验证可访问海外网络")
            return status

        status = "VPN_ON_NOT_VALIDATED"
        if verbose:
            print(f"当前网络状态: {status}")
            print("⚠️ VPN 已开启，但节点可能异常，尚未验证外网连通性")
        return status

    # ---------- 4️⃣ 非 VPN 但网络可用 ----------
    if has_validated:
        status = "NETWORK_OK_NO_VPN"
        if verbose:
            print(f"当前网络状态: {status}")
            print("⚠️ 当前为直连网络，未开启 VPN")
        return status

    # ---------- 5️⃣ 兜底 ----------
    status = "NO_NETWORK"
    if verbose:
        print(f"当前网络状态: {status}")
        print("❌ 当前设备无可用网络（未通过系统 VALIDATED 校验）")
    return status

if __name__ == '__main__':
    check_network_and_vpn_status()