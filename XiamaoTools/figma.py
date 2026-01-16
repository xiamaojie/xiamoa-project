import requests
import os
import json
import re
import hashlib
from unidecode import unidecode  # pip install unidecode
from concurrent.futures import ThreadPoolExecutor, as_completed

# ========== 配置 ==========
FIGMA_API_TOKEN = os.getenv("FIGMA_API_TOKEN") or "YOUR_FIGMA_API_TOKEN" #Figma账户，Account Settings -》Security-》Personal access tokens
FILE_KEY = "KZGIpqs69rIdFxpjCJQjPu"   # 你的 Figma 文件 KEY 例如：https://www.figma.com/design/KZGIpqs69rIdFxpjCJQjPu/Lunar?node-id=1092-13108&t=Ve4bm3QIu8NHc9t2-0 中的 KZGIpqs69rIdFxpjCJQjPu
NODE_IDS = ["1092-13108"]             # 可以直接粘贴 URL 里的参数 node-id 参数值
ASSETS_DIR = "figma_assets"
ASSETS_INDEX_FILE = "assets_index.json"
EXCLUDE_KEYWORDS = ["status", "状态栏", "statusbar"]
MAX_WORKERS = 8  # 并发线程数
# ==========================

# 🔧 自动修正 node-id 格式（支持 1074-7183 -> 1074:7183）
NODE_IDS = [nid.replace("-", ":") for nid in NODE_IDS]

BASE_URL = "https://api.figma.com/v1/files"
HEADERS = {"X-Figma-Token": FIGMA_API_TOKEN}


def fetch_nodes(file_key: str, node_ids: list):
    url = f"{BASE_URL}/{file_key}/nodes?ids={','.join(node_ids)}"
    resp = requests.get(url, headers=HEADERS)
    resp.raise_for_status()
    return resp.json()


def fetch_images(file_key: str, node_ids: list, fmt="png", scale=2):
    """获取 node_id 对应的图片 URL"""
    url = f"https://api.figma.com/v1/images/{file_key}"
    params = {"ids": ",".join(node_ids), "format": fmt, "scale": scale}
    resp = requests.get(url, headers=HEADERS, params=params)
    resp.raise_for_status()
    return resp.json()["images"]


def download_image_task(args):
    url, filename = args
    if os.path.exists(filename):
        return f"⚡ 已存在 {filename}"
    try:
        resp = requests.get(url)
        resp.raise_for_status()
        with open(filename, "wb") as f:
            f.write(resp.content)
        return f"✅ 已保存 {filename}"
    except Exception as e:
        return f"❌ 下载失败 {filename}: {e}"


def sanitize_name(name: str) -> str:
    safe_name = unidecode(name)
    safe_name = re.sub(r"[^A-Za-z0-9]", "_", safe_name)
    if not safe_name:
        safe_name = "asset"
    if len(safe_name) > 10:
        safe_name = safe_name[:10]
    return safe_name.lower()


def figma_color_to_hex(color: dict) -> str:
    r = int(color.get("r", 0) * 255)
    g = int(color.get("g", 0) * 255)
    b = int(color.get("b", 0) * 255)
    return "#{:02X}{:02X}{:02X}".format(r, g, b)


def collect_assets(n, assets_index, node_assets, node_image_map):
    name = n.get("name", "").lower()

    if any(k in name for k in EXCLUDE_KEYWORDS):
        return

    node_id = n.get("id")
    node_type = n.get("type")

    if node_type == "TEXT":
        style = n.get("style", {})
        fills = n.get("fills", [])
        text_color = None
        opacity = 1.0
        for fill in fills:
            if fill.get("type") == "SOLID" and "color" in fill:
                text_color = figma_color_to_hex(fill["color"])
                opacity = fill.get("opacity", 1.0)

        node_assets[node_id] = {
            "safe_name": sanitize_name(n.get("name", f"text_{node_id}")),
            "text": n.get("characters", ""),
            "fontFamily": style.get("fontFamily"),
            "fontSize": style.get("fontSize"),
            "color": text_color,
            "opacity": opacity
        }

    else:
        if "fills" in n:
            for fill in n["fills"]:
                if fill.get("type") == "IMAGE" and "imageRef" in fill:
                    image_ref = fill["imageRef"]
                    node_image_map[node_id] = image_ref  # 保存映射

                    uniq_name = hashlib.md5(image_ref.encode("utf-8")).hexdigest()[:10]
                    asset_path = f"assets/{uniq_name}.png"

                    if image_ref not in assets_index:
                        assets_index[image_ref] = asset_path

                    node_assets[node_id] = {
                        "safe_name": sanitize_name(n.get("name", f"node_{node_id}")),
                        "assetPath": assets_index[image_ref]
                    }

    if "children" in n:
        for c in n["children"]:
            collect_assets(c, assets_index, node_assets, node_image_map)


def update_names(n, node_assets):
    name = n.get("name", "").lower()

    if any(k in name for k in EXCLUDE_KEYWORDS):
        return None

    node_id = n.get("id")
    if node_id in node_assets:
        asset = node_assets[node_id]
        n["name"] = asset["safe_name"]
        if "assetPath" in asset:
            n["assetPath"] = asset["assetPath"]
        if "text" in asset:
            n["text"] = asset["text"]
            n["fontFamily"] = asset.get("fontFamily")
            n["fontSize"] = asset.get("fontSize")
            n["color"] = asset.get("color")
            n["opacity"] = asset.get("opacity")

    if "children" in n:
        new_children = []
        for c in n["children"]:
            updated = update_names(c, node_assets)
            if updated:
                new_children.append(updated)
        n["children"] = new_children

    return n


if __name__ == "__main__":
    if FIGMA_API_TOKEN == "YOUR_FIGMA_API_TOKEN":
        print("⚠️ 请先设置 FIGMA_API_TOKEN")
        exit(1)

    # 0. 加载全局 index
    if os.path.exists(ASSETS_INDEX_FILE):
        with open(ASSETS_INDEX_FILE, "r", encoding="utf-8") as f:
            assets_index = json.load(f)
    else:
        assets_index = {}

    # 1. 获取 node JSON
    data = fetch_nodes(FILE_KEY, NODE_IDS)

    node_assets = {}
    node_image_map = {}  # node_id -> imageRef
    results = {}

    for node_id in NODE_IDS:
        node = data["nodes"][node_id]
        collect_assets(node["document"], assets_index, node_assets, node_image_map)
        results[node_id] = node

    # 2. 下载图片（并发）
    os.makedirs(ASSETS_DIR, exist_ok=True)
    if node_image_map:
        image_map = fetch_images(FILE_KEY, list(node_image_map.keys()), fmt="png", scale=2)

        tasks = []
        for node_id, url in image_map.items():
            if not url:
                continue
            image_ref = node_image_map[node_id]
            filename = os.path.join(ASSETS_DIR, os.path.basename(assets_index[image_ref]))
            tasks.append((url, filename))

        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futures = [executor.submit(download_image_task, t) for t in tasks]
            for future in as_completed(futures):
                print(future.result())

    # 3. 更新 JSON
    cleaned = {}
    for node_id, node in results.items():
        cleaned[node_id] = update_names(node["document"], node_assets)

    with open("figma_nodes_cleaned.json", "w", encoding="utf-8") as f:
        json.dump(cleaned, f, ensure_ascii=False, indent=2)

    # 4. 保存全局 index
    with open(ASSETS_INDEX_FILE, "w", encoding="utf-8") as f:
        json.dump(assets_index, f, ensure_ascii=False, indent=2)

    print("🎉 完成：图片用 node-id 下载，imageRef 去重，本地并发下载，全局复用")
