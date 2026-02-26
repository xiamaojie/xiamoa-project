import re
import subprocess
from typing import Optional, List, Dict, Any, Tuple

COMP_RE = re.compile(r"([a-zA-Z0-9_.]+)/(?:\.[a-zA-Z0-9_.]+|[a-zA-Z0-9_.]+)")
PKG_RE = re.compile(r"\bpackageName=([a-zA-Z0-9_.]+)")
NAME_RE = re.compile(r"\bname=([a-zA-Z0-9_.]+)")

def adb_shell(cmd: str, serial: Optional[str] = None) -> str:
    """
    Run adb shell and return combined stdout/stderr.
    Never calls cmd package query-intent-activities.
    """
    base = ["adb"]
    if serial:
        base += ["-s", serial]
    base += ["shell", cmd]
    p = subprocess.run(base, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    out = (p.stdout or "").strip()
    if p.returncode != 0:
        raise RuntimeError(out)
    return out

def uniq_keep_order(xs: List[str]) -> List[str]:
    seen = set()
    out = []
    for x in xs:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out

def normalize_component(pkg: str, name: str) -> str:
    # name can be ".MainActivity" or "com.pkg.MainActivity"
    if name.startswith("."):
        return f"{pkg}/{name}"
    return f"{pkg}/{name}"

def resolve_default_home(user: int = 0, serial: Optional[str] = None) -> Optional[str]:
    """
    Returns component like com.xxx/.Activity if default HOME exists, else None.
    """
    out = adb_shell(
        f"cmd package resolve-activity --brief --user {user} "
        f"-a android.intent.action.MAIN -c android.intent.category.HOME",
        serial
    )
    m = COMP_RE.search(out)
    if not m:
        return None
    comp = m.group(0)
    if comp == "android/com.android.internal.app.ResolverActivity":
        return None
    return comp

def list_home_candidates(user: int = 0, serial: Optional[str] = None) -> List[str]:
    """
    List all HOME candidates via pm query-intent-activities.
    Parses ActivityInfo blocks: packageName=... name=...
    """
    out = adb_shell(
        "pm query-intent-activities -a android.intent.action.MAIN -c android.intent.category.HOME",
        serial
    )

    # Split into blocks roughly by "ActivityInfo"
    # This is stable across many Android versions.
    blocks = re.split(r"\bActivityInfo\b", out)

    comps: List[str] = []

    for b in blocks:
        pkg_m = PKG_RE.search(b)
        name_m = NAME_RE.search(b)
        if pkg_m and name_m:
            pkg = pkg_m.group(1)
            name = name_m.group(1)
            comps.append(normalize_component(pkg, name))

    # Some ROMs omit ActivityInfo but still show components—grab them too
    comps.extend([m.group(0) for m in COMP_RE.finditer(out)])

    # Clean + filter
    comps = [c for c in comps if c != "android/com.android.internal.app.ResolverActivity"]
    return uniq_keep_order(comps)

def get_launcher_info(user: int = 0, serial: Optional[str] = None) -> Dict[str, Any]:
    default_home = resolve_default_home(user=user, serial=serial)
    candidates = list_home_candidates(user=user, serial=serial)
    return {"default": default_home, "candidates": candidates}

if __name__ == "__main__":
    info = get_launcher_info(user=0)
    print("Default:", info["default"])
    print("Candidates:")
    for c in info["candidates"]:
        print(" ", c)

    # Optional: pick Pixel Launcher if present
    pix = [x for x in info["candidates"] if x.startswith("com.google.android.apps.nexuslauncher/")]
    print("Pixel Launcher:", pix[0] if pix else "not found")
