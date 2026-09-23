from __future__ import annotations

from datetime import datetime, time as dt_time, timedelta, timezone
from io import BytesIO
import json
from pathlib import Path
import sys
import time

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from xiaomi_pictorial import XiaomiPictorialClient, extract_morning_records, _as_dict, _https

TARGET_DATE = "2026-09-23"
CST = timezone(timedelta(hours=8))
PROBE_WIDTHS = (7680, 6000, 5120, 4320, 3840, 3240, 2880, 2560, 2160, 1440, 1080)


def cst_midnight_timestamp(date_text: str) -> int:
    d = datetime.strptime(date_text, "%Y-%m-%d").date()
    return int(datetime.combine(d, dt_time.min, tzinfo=CST).timestamp())


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


client = XiaomiPictorialClient(width=2160, time_offset=28800)
cursor = 0
seen_cursors = set()
all_dates = []
target_record = None

print("PROBE_BEGIN")
for page in range(1, 500):
    if cursor in seen_cursors:
        print("STOP repeated_cursor", cursor)
        break
    seen_cursors.add(cursor)

    payload = client.morning_history(start_time=cursor, delta=6, page_size=30)
    records = extract_morning_records(payload, PROBE_WIDTHS)
    if not records:
        print("STOP empty_page", page)
        break

    dates = [r.morning_date for r in records]
    all_dates.extend(dates)
    print(f"PAGE {page} count={len(records)} newest={max(dates)} oldest={min(dates)} cursor={cursor}")

    for r in records:
        if r.morning_date == TARGET_DATE:
            target_record = r

    oldest = min(dates)
    next_cursor = cst_midnight_timestamp(oldest)
    if next_cursor == cursor:
        print("STOP no_cursor_progress", cursor)
        break
    cursor = next_cursor
    time.sleep(0.08)
else:
    print("STOP page_limit")

unique_dates = sorted(set(all_dates))
print("DATE_SUMMARY", json.dumps({
    "count": len(unique_dates),
    "earliest": unique_dates[0] if unique_dates else None,
    "latest": unique_dates[-1] if unique_dates else None,
}, ensure_ascii=False))

if target_record is None:
    print("TODAY_NOT_FOUND", TARGET_DATE)
    raise SystemExit(0)

print("TODAY_RECORD", json.dumps({
    "date": target_record.morning_date,
    "id": target_record.item_id,
    "title": target_record.title,
}, ensure_ascii=False))

# Build a richer set than the app currently exposes so we can find the actual ceiling.
urls = []
for cl in cl_blocks(target_record.raw):
    for key in ("url_full", "url_h", "url_m", "url_l", "url_r"):
        value = str(cl.get(key) or "").strip()
        if value:
            urls.append((key, _https(value)))
    root = str(cl.get("url_root") or "").strip()
    locator = str(cl.get("locator") or "").strip().lstrip("/")
    if root and locator:
        root = _https(root).rstrip("/")
        for width in PROBE_WIDTHS:
            urls.append((f"cdn_w{width}", f"{root}/webp/w{width}/{locator}"))

seen = set()
results = []
for label, url in urls:
    if url in seen:
        continue
    seen.add(url)
    try:
        response = client.session.get(url, timeout=45)
        status = response.status_code
        ctype = response.headers.get("Content-Type", "")
        dims = None
        error = None
        if response.ok:
            try:
                img = Image.open(BytesIO(response.content))
                dims = [img.width, img.height]
            except Exception as exc:
                error = f"image_parse: {exc}"
        else:
            error = response.text[:100].replace("\n", " ")
        row = {
            "label": label,
            "status": status,
            "dimensions": dims,
            "bytes": len(response.content),
            "content_type": ctype,
            "url": url,
            "error": error,
        }
        results.append(row)
        print("IMAGE_PROBE", json.dumps(row, ensure_ascii=False))
    except Exception as exc:
        row = {"label": label, "status": None, "dimensions": None, "url": url, "error": str(exc)}
        results.append(row)
        print("IMAGE_PROBE", json.dumps(row, ensure_ascii=False))
    time.sleep(0.05)

valid = [r for r in results if r.get("dimensions")]
if valid:
    best = max(valid, key=lambda r: r["dimensions"][0] * r["dimensions"][1])
    print("MAX_IMAGE", json.dumps(best, ensure_ascii=False))
else:
    print("MAX_IMAGE", "none")
print("PROBE_END")
