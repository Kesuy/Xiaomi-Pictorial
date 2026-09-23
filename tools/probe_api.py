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

from xiaomi_pictorial import XiaomiPictorialClient, extract_morning_records, _as_dict, _https

TARGET_DATE = "2026-09-23"
RES_VALUES = (1080, 1200, 1440, 2160)


def cl_blocks(item):
    blocks = []
    images = item.get("images")
    if isinstance(images, list):
        for image in images:
            if isinstance(image, dict):
                cl = _as_dict(image.get("cl_url") or image.get("clUrl") or image)
                if cl:
                    blocks.append(cl)
    top = _as_dict(item.get("cl_url") or item.get("clUrl"))
    if top:
        blocks.append(top)
    return blocks


def image_dims(session, url):
    try:
        response = session.get(url, timeout=45)
        if not response.ok:
            return {"status": response.status_code, "dims": None, "bytes": len(response.content)}
        img = Image.open(BytesIO(response.content))
        return {
            "status": response.status_code,
            "dims": [img.width, img.height],
            "bytes": len(response.content),
            "type": response.headers.get("Content-Type"),
        }
    except Exception as exc:
        return {"status": None, "dims": None, "error": str(exc)}


print("RES_PROBE_BEGIN")
for res in RES_VALUES:
    client = XiaomiPictorialClient(width=res, time_offset=28800)
    payload = client.morning_history(start_time=0, delta=6, page_size=30)
    records = extract_morning_records(payload, (7680, 4320, 2608, 2160, 1440, 1200, 1080))
    record = next((r for r in records if r.morning_date == TARGET_DATE), None)
    if record is None:
        print("RES_RESULT", json.dumps({"res": res, "found": False}, ensure_ascii=False))
        continue

    blocks = cl_blocks(record.raw)
    print("RES_RESULT", json.dumps({
        "res": res,
        "found": True,
        "id": record.item_id,
        "title": record.title,
        "cl_blocks": blocks,
    }, ensure_ascii=False))

    seen = set()
    for cl in blocks:
        urls = []
        for key in ("url_full", "url_h", "url_m", "url_l", "url_r"):
            value = str(cl.get(key) or "").strip()
            if value:
                urls.append((key, _https(value)))
        root = str(cl.get("url_root") or "").strip()
        locator = str(cl.get("locator") or "").strip().lstrip("/")
        if root and locator:
            root = _https(root).rstrip("/")
            for width in (7680, 4320, 2608, 2160, 1440, 1200, 1080):
                urls.append((f"cdn_w{width}", f"{root}/webp/w{width}/{locator}"))
        for label, url in urls:
            if url in seen:
                continue
            seen.add(url)
            result = image_dims(client.session, url)
            print("URL_RESULT", json.dumps({
                "res": res,
                "label": label,
                "url": url,
                **result,
            }, ensure_ascii=False))

print("RES_PROBE_END")
