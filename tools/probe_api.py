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

client = XiaomiPictorialClient(width=1200, time_offset=28800)
locator = "ThemeMarket/0312f3e3d92524f0598f3a2b0a55020e4db505a2a"
base = "https://wallpaper.cdn.pandora.xiaomi.com"

urls = [
    f"{base}/{locator}",
    f"{base}/original/{locator}",
    f"{base}/origin/{locator}",
    f"{base}/full/{locator}",
    f"{base}/image/{locator}",
    f"{base}/thumbnail/{locator}",
    f"{base}/thumbnail/webp/w0/{locator}",
    f"{base}/webp/w1080/{locator}",
    f"{base}/thumbnail/webp/w1080/{locator}",
]

for url in urls:
    try:
        r = client.session.get(url, timeout=45)
        dims = None
        if r.ok:
            try:
                img = Image.open(BytesIO(r.content))
                dims = [img.width, img.height]
            except Exception:
                pass
        print("CANDIDATE", json.dumps({
            "url": url,
            "status": r.status_code,
            "bytes": len(r.content),
            "content_type": r.headers.get("Content-Type"),
            "dims": dims,
            "location": r.headers.get("Location"),
        }, ensure_ascii=False))
    except Exception as exc:
        print("CANDIDATE", json.dumps({
            "url": url,
            "error": repr(exc),
        }, ensure_ascii=False))
