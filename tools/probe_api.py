from __future__ import annotations

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from xiaomi_pictorial import XiaomiPictorialClient, _as_dict

client = XiaomiPictorialClient(width=1200, time_offset=28800)

CASES = [
    ("morning", "/gallery/gallery_morning", {"time_offset": 28800}),
    (
        "morning_list",
        "/gallery/gallery_morning_list",
        {"time_offset": 28800, "start_time": 0, "delta": 6, "page_size": 30},
    ),
    (
        "morning_history",
        "/gallery/gallery_morning_history",
        {"time_offset": 28800, "start_time": 0, "delta": 6, "page_size": 30},
    ),
]


def walk(node, found):
    if isinstance(node, dict):
        cl = _as_dict(node.get("cl_url") or node.get("clUrl"))
        if cl:
            found.append(cl)
        for value in node.values():
            walk(value, found)
    elif isinstance(node, list):
        for value in node:
            walk(value, found)


for name, path, params in CASES:
    print("CASE_BEGIN", name)
    try:
        payload = client._get(path, params)
    except Exception as exc:
        print("CASE_ERROR", name, repr(exc))
        continue

    blocks = []
    walk(payload, blocks)
    print("CL_COUNT", name, len(blocks))
    seen = set()
    for block in blocks:
        key = json.dumps(block, ensure_ascii=False, sort_keys=True)
        if key in seen:
            continue
        seen.add(key)
        print("CL_BLOCK", name, key)

    Path(f"probe_{name}.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print("CASE_END", name)
