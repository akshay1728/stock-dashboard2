import os
import sys
import subprocess
import site

def get_lib_path():
    """Find the pyoauthbridge path using multiple methods."""
    # Method 1: pip show
    try:
        output = subprocess.check_output([sys.executable, "-m", "pip", "show", "pyoauthbridge"]).decode()
        for line in output.splitlines():
            if line.startswith("Location:"):
                loc = line.split(":", 1)[1].strip()
                path = os.path.join(loc, "pyoauthbridge")
                if os.path.exists(path): return path
    except: pass

    # Method 2: site packages
    for p in site.getsitepackages() + [site.getusersitepackages()]:
        path = os.path.join(p, "pyoauthbridge")
        if os.path.exists(path): return path

    # Method 3: sys.path
    for p in sys.path:
        path = os.path.join(p, "pyoauthbridge")
        if os.path.exists(path) and os.path.isdir(path): return path

    return None

def patch_file(file_path, replacements):
    if not os.path.exists(file_path):
        print(f"File not found: {file_path}")
        return False

    print(f"Patching {file_path}...")
    with open(file_path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    modified = False
    new_lines = []
    for line in lines:
        new_line = line
        for old, new in replacements:
            if old in new_line and new not in new_line:
                new_line = new_line.replace(old, new)
                modified = True
        new_lines.append(new_line)

    if modified:
        with open(file_path, "w", encoding="utf-8") as f:
            f.writelines(new_lines)
        print(f"  Successfully applied patches to {os.path.basename(file_path)}")
        return True
    else:
        print(f"  No patches needed for {os.path.basename(file_path)}")
        return False

def run():
    print("=== PyOAuthBridge Robust Patcher v2 ===")
    path = get_lib_path()
    if not path:
        print("CRITICAL: Could not locate pyoauthbridge installation.")
        sys.exit(1)

    print(f"Target Path: {path}")

    # connect.py
    patch_file(os.path.join(path, "connect.py"), [
        ("from server import Server", "from .server import Server"),
        ("from wsclient import", "from .wsclient import")
    ])

    # wsclient.py
    patch_file(os.path.join(path, "wsclient.py"), [
        ("from packetDecoder import", "from .packetDecoder import")
    ])

    # __init__.py check
    patch_file(os.path.join(path, "__init__.py"), [
        ("from pyoauthbridge.connect import Connect", "from .connect import Connect")
    ])

    print("Patching process complete.")

if __name__ == "__main__":
    run()
