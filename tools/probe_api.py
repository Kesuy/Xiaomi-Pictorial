from __future__ import annotations
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from xiaomi_pictorial import XiaomiPictorialClient, extract_morning_records, _as_dict, _https

TARGET_DATE = "2026-09-22"
client = XiaomiPictorialClient(width=1080, time_offset=28800)
payload = client.morning_history(start_time=0, delta=6, page_size=30)
records = extract_morning_records(payload, (1080,))
record = next((r for r in records if r.morning_date == TARGET_DATE), None)
if record is None:
    print("TARGET_NOT_FOUND")
    raise SystemExit(1)

print("TARGET_RECORD", json.dumps({
    "date": record.morning_date,
    "id": record.item_id,
    "title": record.title,
}, ensure_ascii=False))

images = record.raw.get("images") or []
for image in images:
    if not isinstance(image, dict):
        continue
    cl = _as_dict(image.get("cl_url") or image.get("clUrl") or image)
    if not cl:
        continue
    root = str(cl.get("url_root") or "").strip()
    locator = str(cl.get("locator") or "").strip().lstrip("/")
    print("CL_BLOCK", json.dumps(cl, ensure_ascii=False))
    if root and locator:
        root = _https(root).rstrip("/")
        for width in (1080, 1200, 2160):
            print("CDN_URL", width, f"{root}/webp/w{width}/{locator}")

# Save the 1080 CDN rendition as an artifact for offline comparison.
root = "https://wallpaper.cdn.pandora.xiaomi.com/thumbnail"
locator = "ThemeMarket/0312f3e3d92524f0598f3a2b0a55020e4db505a2a"
url = f"{root}/webp/w1080/{locator}"
response = client.session.get(url, timeout=45)
response.raise_for_status()
Path("server_2026-09-22_1080.webp").write_bytes(response.content)
print("SAVED_SERVER_IMAGE", len(response.content))
