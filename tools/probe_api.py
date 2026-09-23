from __future__ import annotations
from io import BytesIO
import json
from pathlib import Path
import sys

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from xiaomi_pictorial import XiaomiPictorialClient

locator = "ThemeMarket/0312f3e3d92524f0598f3a2b0a55020e4db505a2a"
hosts = [
    "wallpaper.cdn.pandora.xiaomi.com",
    "image.pandora.xiaomi.com",
    "gallery.cdn.pandora.xiaomi.com",
    "package.wallpaper.cdn.pandora.xiaomi.com",
]
paths = [
    "{locator}",
    "original/{locator}",
    "origin/{locator}",
    "raw/{locator}",
    "full/{locator}",
    "image/{locator}",
    "jpeg/{locator}",
    "webp/{locator}",
    "jpeg/w1200/{locator}",
    "webp/w1200/{locator}",
    "thumbnail/jpeg/w1200/{locator}",
    "thumbnail/webp/w1200/{locator}",
]

client = XiaomiPictorialClient(width=1200, time_offset=28800)
for host in hosts:
    for pat in paths:
        url = "https://" + host + "/" + pat.format(locator=locator)
        try:
            r = client.session.get(url, timeout=15)
            row = {
                "url": url,
                "status": r.status_code,
                "type": r.headers.get("Content-Type"),
                "bytes": len(r.content),
            }
            if r.ok and r.content:
                try:
                    im = Image.open(BytesIO(r.content))
                    row["dims"] = [im.width, im.height]
                    row["format"] = im.format
                except Exception:
                    pass
            if r.status_code != 404 or "dims" in row:
                print("CANDIDATE", json.dumps(row, ensure_ascii=False))
        except Exception as exc:
            print("ERROR", host, pat, type(exc).__name__, str(exc)[:160])
