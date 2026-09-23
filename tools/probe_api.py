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
payload = client._get("/gallery/gallery_morning", {"time_offset": 28800})

def walk(node, path="root"):
    if isinstance(node, dict):
        if "images" in node and ("id" in node or "item_type" in node):
            print("ITEM", json.dumps({
                "id": node.get("id"),
                "type": node.get("item_type"),
                "title": _as_dict(node.get("meta")).get("title"),
                "exparam": node.get("exparam"),
            }, ensure_ascii=False))
            images = node.get("images")
            if isinstance(images, list):
                for image in images:
                    if isinstance(image, dict):
                        cl = _as_dict(image.get("cl_url") or image.get("clUrl") or image)
                        if cl:
                            print("CL", json.dumps(cl, ensure_ascii=False))
        for k, v in node.items():
            p = path + "." + str(k)
            if isinstance(v, str) and (
                "url" in str(k).lower()
                or "http://" in v or "https://" in v
                or "thumbnail" in v or "ThemeMarket/" in v
            ):
                print("URL_FIELD", p, json.dumps(v, ensure_ascii=False))
            walk(v, p)
    elif isinstance(node, list):
        for i, v in enumerate(node):
            walk(v, f"{path}[{i}]")

walk(payload)
