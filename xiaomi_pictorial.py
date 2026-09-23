from __future__ import annotations

import argparse
import json
import os
import queue
import random
import re
import sys
import threading
import time
import uuid
from dataclasses import asdict, dataclass
from datetime import date, datetime, time as dt_time
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

APP_NAME = "Xiaomi Pictorial"
APP_VERSION = "0.2.0"

API_HOST = "https://w.pandora.xiaomi.com"
API_PREFIX = "/api/a1"
MORNING_HISTORY_PATH = "/gallery/gallery_morning_history"
MORNING_LIST_PATH = "/gallery/gallery_morning_list"

DEFAULT_VERSION_NAME = "25200033-CAROUSEL"
DEFAULT_VERSION_CODE = 2025200033
DEFAULT_FEATURE_VERSION = "20160831"
DEFAULT_PAGE_SIZE = 30
DEFAULT_DELTA = 6
DEFAULT_WIDTH = 2160

FILENAME_FORMATS = {
    "date": "日期",
    "title": "标题",
    "date_title": "日期+标题",
}
QUALITY_OPTIONS = {
    "best": "最高可用",
    "2160": "2160 优先",
    "1440": "1440 优先",
    "1080": "1080 优先",
}

IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".avif"}


class XiaomiPictorialError(RuntimeError):
    pass


class ApiError(XiaomiPictorialError):
    pass


@dataclass
class MorningRecord:
    morning_date: str
    item_id: str
    title: str
    description: str
    image_url: str
    image_candidates: list[str]
    raw: dict[str, Any]


@dataclass
class DownloadStats:
    pages: int = 0
    discovered: int = 0
    matched: int = 0
    downloaded: int = 0
    skipped: int = 0
    failed: int = 0


def _app_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


CONFIG_PATH = _app_dir() / "xiaomi-pictorial.json"


def load_config() -> dict[str, Any]:
    try:
        if CONFIG_PATH.exists():
            data = json.loads(CONFIG_PATH.read_text("utf-8"))
            if isinstance(data, dict):
                return data
    except Exception:
        pass
    return {}


def save_config(data: dict[str, Any]) -> None:
    try:
        CONFIG_PATH.write_text(
            json.dumps(data, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception:
        # 配置保存失败不影响下载。
        pass


def persistent_device_id() -> str:
    config = load_config()
    value = str(config.get("device_id") or "").strip()
    if value:
        return value
    value = uuid.uuid4().hex
    config["device_id"] = value
    save_config(config)
    return value


def local_time_offset_seconds() -> int:
    offset = datetime.now().astimezone().utcoffset()
    return int(offset.total_seconds()) if offset else 0


def parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.strptime(value.strip(), "%Y-%m-%d").date()
    except ValueError as exc:
        raise ValueError(f"日期格式必须为 YYYY-MM-DD：{value}") from exc


def midnight_timestamp(value: date) -> int:
    local_dt = datetime.combine(value, dt_time.min).astimezone()
    return int(local_dt.timestamp())


def sanitize_filename(value: str, limit: int = 80) -> str:
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", value or "")
    value = re.sub(r"\s+", " ", value).strip(" .")
    return value[:limit].strip() or "untitled"


def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        text = value.strip()
        if text.startswith("{") and text.endswith("}"):
            try:
                parsed = json.loads(text)
                if isinstance(parsed, dict):
                    return parsed
            except Exception:
                pass
    return {}


def dedupe_keep_order(items: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        item = (item or "").strip()
        if not item or item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def width_from_url(url: str) -> int:
    match = re.search(r"/w(\d{3,5})/", url)
    return int(match.group(1)) if match else 0


def reorder_candidates(candidates: list[str], quality_mode: str) -> list[str]:
    if quality_mode == "best":
        # url_full/url_h remain first; generated CDN widths are then ordered high -> low.
        fixed = [u for u in candidates if width_from_url(u) == 0]
        resized = sorted(
            [u for u in candidates if width_from_url(u) > 0],
            key=width_from_url,
            reverse=True,
        )
        return fixed + resized
    try:
        target = int(quality_mode)
    except ValueError:
        return candidates
    fixed = [u for u in candidates if width_from_url(u) == 0]
    resized = sorted(
        [u for u in candidates if width_from_url(u) > 0],
        key=lambda u: (abs(width_from_url(u) - target), -width_from_url(u)),
    )
    return fixed + resized


def make_base_name(record: MorningRecord, mode: str) -> str:
    title = sanitize_filename(record.title)
    if mode == "title" and title != "untitled":
        return title
    if mode == "date_title" and title != "untitled":
        return sanitize_filename(f"{record.morning_date} {title}")
    return record.morning_date


def _date_from_item(item: dict[str, Any]) -> str:
    direct = item.get("morning_date") or item.get("morningDate")
    if direct:
        return str(direct)
    exparam = _as_dict(item.get("exparam") or item.get("ex_param"))
    value = exparam.get("morning_date") or exparam.get("morningDate")
    return str(value or "")


def _find_item_list(payload: Any) -> list[dict[str, Any]]:
    candidates: list[tuple[int, list[dict[str, Any]]]] = []

    def walk(node: Any) -> None:
        if isinstance(node, list):
            dicts = [x for x in node if isinstance(x, dict)]
            if dicts:
                score = sum(1 for x in dicts if _date_from_item(x))
                if score:
                    candidates.append((score, dicts))
            for child in node:
                if isinstance(child, (dict, list)):
                    walk(child)
        elif isinstance(node, dict):
            for child in node.values():
                if isinstance(child, (dict, list)):
                    walk(child)

    walk(payload)
    if not candidates:
        return []
    candidates.sort(key=lambda pair: (pair[0], len(pair[1])), reverse=True)
    return candidates[0][1]


def _https(url: str) -> str:
    if url.startswith("http://"):
        return "https://" + url[len("http://") :]
    return url


def _image_candidates(
    item: dict[str, Any],
    widths: Iterable[int] = (2160, 1440, 1080),
) -> list[str]:
    images = item.get("images")
    if not isinstance(images, list):
        images = []

    cl_urls: list[dict[str, Any]] = []
    for image in images:
        if not isinstance(image, dict):
            continue
        cl = _as_dict(image.get("cl_url") or image.get("clUrl") or image)
        if cl:
            cl_urls.append(cl)

    top_cl = _as_dict(item.get("cl_url") or item.get("clUrl"))
    if top_cl:
        cl_urls.append(top_cl)

    result: list[str] = []
    for cl in cl_urls:
        # 25200033 中能看到 url_full/url_h/url_m/url_l/url_r。
        # 先尝试服务端直接给出的完整/高清地址，再尝试 CDN 动态宽度。
        for key in ("url_full", "url_h", "url_m", "url_l", "url_r"):
            value = str(cl.get(key) or "").strip()
            if value:
                result.append(_https(value))

        root = str(cl.get("url_root") or "").strip()
        locator = str(cl.get("locator") or "").strip().lstrip("/")
        if root and locator:
            root = _https(root).rstrip("/")
            for width in widths:
                result.append(f"{root}/webp/w{int(width)}/{locator}")

    return dedupe_keep_order(result)


def extract_morning_records(
    payload: Any,
    widths: Iterable[int] = (2160, 1440, 1080),
) -> list[MorningRecord]:
    result: list[MorningRecord] = []
    seen: set[tuple[str, str]] = set()

    for item in _find_item_list(payload):
        morning_date = _date_from_item(item)
        if not morning_date or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", morning_date):
            continue

        meta = _as_dict(item.get("meta"))
        item_id = str(item.get("id") or item.get("item_id") or "").strip()
        title = str(meta.get("title") or item.get("title") or "").strip()
        description = str(
            meta.get("desc")
            or meta.get("description")
            or item.get("desc")
            or item.get("description")
            or ""
        ).strip()
        image_candidates = _image_candidates(item, widths)
        image_url = image_candidates[0] if image_candidates else ""

        key = (morning_date, item_id or image_url)
        if key in seen:
            continue
        seen.add(key)
        result.append(
            MorningRecord(
                morning_date=morning_date,
                item_id=item_id,
                title=title,
                description=description,
                image_url=image_url,
                image_candidates=image_candidates,
                raw=item,
            )
        )

    result.sort(key=lambda x: x.morning_date, reverse=True)
    return result


class XiaomiPictorialClient:
    def __init__(
        self,
        *,
        width: int = DEFAULT_WIDTH,
        locale: str = "zh_CN",
        version_name: str = DEFAULT_VERSION_NAME,
        version_code: int = DEFAULT_VERSION_CODE,
        feature_version: str = DEFAULT_FEATURE_VERSION,
        device_id: str | None = None,
        time_offset: int | None = None,
        timeout: int = 25,
    ) -> None:
        self.width = int(width)
        self.locale = locale
        self.version_name = version_name
        self.version_code = int(version_code)
        self.feature_version = feature_version
        self.device_id = device_id or persistent_device_id()
        self.time_offset = (
            int(time_offset) if time_offset is not None else local_time_offset_seconds()
        )
        self.timeout = timeout

        retries = Retry(
            total=3,
            connect=3,
            read=3,
            backoff_factor=0.8,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset({"GET"}),
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retries)
        self.session = requests.Session()
        self.session.mount("https://", adapter)
        self.session.headers.update(
            {
                "Accept": "application/json",
                "User-Agent": (
                    "Xiaomi-Pictorial/0.1 "
                    "(Android compatible; https://github.com/Kesuy/Xiaomi-Pictorial)"
                ),
            }
        )

    def _common_params(self) -> dict[str, str]:
        return {
            "_vcode": str(self.version_code),
            "_vname": self.version_name,
            "_fver": self.feature_version,
            "_locale": self.locale,
            "_res": str(self.width),
            "_devid": self.device_id,
            "_nonce": str(random.randint(-(2**31), 2**31 - 1)),
            "_ts": str(int(time.time())),
        }

    @staticmethod
    def _check_api_error(payload: Any) -> None:
        if not isinstance(payload, dict):
            return

        code = payload.get("code")
        if code is not None and str(code).lower() not in {"0", "200", "ok", "success"}:
            message = (
                payload.get("message")
                or payload.get("msg")
                or payload.get("reason")
                or "未知接口错误"
            )
            raise ApiError(f"接口返回 code={code}: {message}")

        status = payload.get("status")
        if isinstance(status, str) and status.lower() in {"error", "failed", "fail"}:
            raise ApiError(str(payload.get("message") or payload.get("msg") or status))

    def _get(self, path: str, params: dict[str, Any]) -> Any:
        merged = self._common_params()
        merged.update({k: str(v) for k, v in params.items()})
        url = API_HOST + API_PREFIX + path

        try:
            response = self.session.get(url, params=merged, timeout=self.timeout)
        except requests.RequestException as exc:
            raise ApiError(f"无法连接小米画报接口：{exc}") from exc

        if not response.ok:
            preview = response.text[:300].replace("\n", " ")
            raise ApiError(f"HTTP {response.status_code}: {preview}")

        try:
            payload = response.json()
        except ValueError as exc:
            preview = response.text[:300].replace("\n", " ")
            raise ApiError(f"接口未返回 JSON：{preview}") from exc

        self._check_api_error(payload)
        return payload

    def morning_history(
        self,
        *,
        start_time: int = 0,
        delta: int = DEFAULT_DELTA,
        page_size: int = DEFAULT_PAGE_SIZE,
    ) -> Any:
        return self._get(
            MORNING_HISTORY_PATH,
            {
                "time_offset": self.time_offset,
                "start_time": int(start_time),
                "delta": int(delta),
                "page_size": int(page_size),
            },
        )

    def morning_list(
        self,
        *,
        start_time: int = 0,
        delta: int = DEFAULT_DELTA,
        page_size: int = DEFAULT_PAGE_SIZE,
    ) -> Any:
        return self._get(
            MORNING_LIST_PATH,
            {
                "time_offset": self.time_offset,
                "start_time": int(start_time),
                "delta": int(delta),
                "page_size": int(page_size),
            },
        )

    def iter_history(
        self,
        *,
        start_date: date | None = None,
        end_date: date | None = None,
        delta: int = DEFAULT_DELTA,
        page_size: int = DEFAULT_PAGE_SIZE,
        max_pages: int | None = None,
        on_page: Callable[[int, list[MorningRecord]], None] | None = None,
        should_stop: Callable[[], bool] | None = None,
        debug_dir: Path | None = None,
    ) -> Iterator[MorningRecord]:
        cursor = 0
        previous_cursor: int | None = None
        seen_records: set[tuple[str, str]] = set()
        page_no = 0

        while True:
            if should_stop and should_stop():
                return
            if max_pages is not None and page_no >= max_pages:
                return

            payload = self.morning_history(
                start_time=cursor,
                delta=delta,
                page_size=page_size,
            )
            page_no += 1

            if debug_dir:
                debug_dir.mkdir(parents=True, exist_ok=True)
                (debug_dir / f"page-{page_no:04d}.json").write_text(
                    json.dumps(payload, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )

            records = extract_morning_records(
                payload,
                (2160, 1440, 1080, self.width),
            )
            if on_page:
                on_page(page_no, records)
            if not records:
                return

            new_count = 0
            for record in records:
                key = (record.morning_date, record.item_id or record.image_url)
                if key in seen_records:
                    continue
                seen_records.add(key)
                new_count += 1

                record_date = parse_date(record.morning_date)
                if record_date is None:
                    continue
                if end_date and record_date > end_date:
                    continue
                if start_date and record_date < start_date:
                    continue
                yield record

            oldest = min(parse_date(x.morning_date) for x in records)
            if oldest is None:
                return
            if start_date and oldest < start_date:
                return

            next_cursor = midnight_timestamp(oldest)
            if next_cursor == cursor or next_cursor == previous_cursor or new_count == 0:
                return

            previous_cursor = cursor
            cursor = next_cursor
            time.sleep(0.15)

    def download_image(
        self,
        record: MorningRecord,
        destination_base: Path,
        quality_mode: str = "best",
    ) -> tuple[Path, str]:
        candidates = record.image_candidates or ([record.image_url] if record.image_url else [])
        candidates = reorder_candidates(candidates, quality_mode)
        if not candidates:
            raise XiaomiPictorialError("该条早安画报没有可用的图片地址")

        last_error = "未知错误"
        for url in candidates:
            try:
                response = self.session.get(url, stream=True, timeout=45)
            except requests.RequestException as exc:
                last_error = str(exc)
                continue

            if not response.ok:
                last_error = f"HTTP {response.status_code}: {url}"
                response.close()
                continue

            content_type = response.headers.get("Content-Type", "").split(";")[0].lower()
            suffix = {
                "image/jpeg": ".jpg",
                "image/png": ".png",
                "image/webp": ".webp",
                "image/avif": ".avif",
            }.get(content_type)

            if not suffix:
                suffix = Path(requests.utils.urlparse(url).path).suffix.lower()
                if suffix not in IMAGE_SUFFIXES:
                    suffix = ".jpg"

            destination = destination_base.with_suffix(suffix)
            tmp = destination.with_suffix(destination.suffix + ".part")
            destination.parent.mkdir(parents=True, exist_ok=True)

            try:
                with tmp.open("wb") as handle:
                    for chunk in response.iter_content(chunk_size=256 * 1024):
                        if chunk:
                            handle.write(chunk)
                tmp.replace(destination)
                return destination, url
            finally:
                response.close()

        raise XiaomiPictorialError(f"图片下载失败：{last_error}")


class MorningDownloader:
    def __init__(
        self,
        client: XiaomiPictorialClient,
        *,
        output_dir: Path,
        organize_by_month: bool = True,
        save_text: bool = True,
        save_json: bool = True,
        skip_existing: bool = True,
        dry_run: bool = False,
        quality_mode: str = "best",
        filename_mode: str = "date",
    ) -> None:
        self.client = client
        self.output_dir = output_dir
        self.organize_by_month = organize_by_month
        self.save_text = save_text
        self.save_json = save_json
        self.skip_existing = skip_existing
        self.dry_run = dry_run
        self.quality_mode = quality_mode
        self.filename_mode = filename_mode

    def _folder_for(self, record: MorningRecord) -> Path:
        if not self.organize_by_month:
            return self.output_dir
        year, month, _ = record.morning_date.split("-")
        return self.output_dir / year / month

    @staticmethod
    def _has_existing_image(folder: Path, stem: str) -> bool:
        for path in folder.glob(stem + ".*"):
            if path.suffix.lower() in IMAGE_SUFFIXES and path.is_file():
                return True
        return False

    def run(
        self,
        *,
        start_date: date | None = None,
        end_date: date | None = None,
        page_size: int = DEFAULT_PAGE_SIZE,
        delta: int = DEFAULT_DELTA,
        max_pages: int | None = None,
        debug_json: bool = False,
        on_log: Callable[[str], None] | None = None,
        on_progress: Callable[[DownloadStats], None] | None = None,
        should_stop: Callable[[], bool] | None = None,
    ) -> DownloadStats:
        stats = DownloadStats()
        self.output_dir.mkdir(parents=True, exist_ok=True)
        debug_dir = self.output_dir / "_debug" if debug_json else None

        def log(message: str) -> None:
            if on_log:
                on_log(message)

        def page_callback(page_no: int, records: list[MorningRecord]) -> None:
            stats.pages = page_no
            stats.discovered += len(records)
            log(f"第 {page_no} 页：接口返回 {len(records)} 条")
            if on_progress:
                on_progress(stats)

        for record in self.client.iter_history(
            start_date=start_date,
            end_date=end_date,
            delta=delta,
            page_size=page_size,
            max_pages=max_pages,
            on_page=page_callback,
            should_stop=should_stop,
            debug_dir=debug_dir,
        ):
            if should_stop and should_stop():
                log("已停止")
                break

            stats.matched += 1
            folder = self._folder_for(record)
            folder.mkdir(parents=True, exist_ok=True)

            stem = make_base_name(record, self.filename_mode)
            if self.skip_existing and self._has_existing_image(folder, stem):
                stats.skipped += 1
                log(f"[跳过] {record.morning_date} 已存在")
                if on_progress:
                    on_progress(stats)
                continue

            if self.dry_run:
                log(
                    f"[发现] {record.morning_date} "
                    f"{record.title or '(无标题)'} -> {record.image_url or '(无图片)'}"
                )
                if on_progress:
                    on_progress(stats)
                continue

            try:
                saved_image, selected_url = self.client.download_image(
                    record,
                    folder / stem,
                    self.quality_mode,
                )

                if self.save_text:
                    text = (
                        f"日期：{record.morning_date}\n"
                        f"标题：{record.title}\n"
                        f"文案：{record.description}\n"
                        f"图片：{selected_url}\n"
                        f"ID：{record.item_id}\n"
                    )
                    (folder / f"{stem}.txt").write_text(text, encoding="utf-8")

                if self.save_json:
                    metadata = asdict(record)
                    metadata["selected_image_url"] = selected_url
                    metadata["saved_image"] = saved_image.name
                    (folder / f"{stem}.json").write_text(
                        json.dumps(metadata, ensure_ascii=False, indent=2),
                        encoding="utf-8",
                    )

                stats.downloaded += 1
                log(
                    f"[完成] {record.morning_date} "
                    f"{record.title or ''} -> {saved_image.name}"
                )
            except Exception as exc:
                stats.failed += 1
                log(f"[失败] {record.morning_date}: {exc}")

            if on_progress:
                on_progress(stats)
            time.sleep(0.1)

        return stats


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="批量下载小米画报的早安画报历史内容"
    )
    parser.add_argument("--start", help="开始日期 YYYY-MM-DD；不填则尽量向前扫描")
    parser.add_argument("--end", help="结束日期 YYYY-MM-DD；不填则不限")
    parser.add_argument(
        "-o",
        "--output",
        default="downloads",
        help="下载目录，默认 downloads",
    )
    parser.add_argument("--width", type=int, default=DEFAULT_WIDTH, help="CDN 回退宽度")
    parser.add_argument("--page-size", type=int, default=DEFAULT_PAGE_SIZE)
    parser.add_argument("--delta", type=int, default=DEFAULT_DELTA)
    parser.add_argument("--max-pages", type=int, help="最多扫描多少页，调试用")
    parser.add_argument("--flat", action="store_true", help="不按 年/月 创建目录")
    parser.add_argument("--no-text", action="store_true", help="不保存 TXT 文案")
    parser.add_argument("--no-json", action="store_true", help="不保存 JSON 元数据")
    parser.add_argument("--overwrite", action="store_true", help="覆盖/重新下载已存在日期")
    parser.add_argument("--dry-run", action="store_true", help="只扫描，不下载图片")
    parser.add_argument("--debug-json", action="store_true", help="保存接口原始 JSON")
    parser.add_argument(
        "--time-offset",
        type=int,
        help="覆盖 time_offset（默认使用本机 UTC 偏移秒数）",
    )
    parser.add_argument(
        "--quality",
        choices=list(QUALITY_OPTIONS),
        default="best",
        help="图片质量策略",
    )
    parser.add_argument(
        "--name-format",
        choices=list(FILENAME_FORMATS),
        default="date",
        help="图片命名格式",
    )
    parser.add_argument("--gui", action="store_true", help="打开图形界面")
    return parser


def run_cli(args: argparse.Namespace) -> int:
    start = parse_date(args.start)
    end = parse_date(args.end)
    if start and end and start > end:
        raise ValueError("开始日期不能晚于结束日期")

    client = XiaomiPictorialClient(
        width=args.width,
        time_offset=args.time_offset,
    )
    downloader = MorningDownloader(
        client,
        output_dir=Path(args.output),
        organize_by_month=not args.flat,
        save_text=not args.no_text,
        save_json=not args.no_json,
        skip_existing=not args.overwrite,
        dry_run=args.dry_run,
        quality_mode=args.quality,
        filename_mode=args.name_format,
    )

    print(
        f"{APP_NAME} v{APP_VERSION} | "
        f"time_offset={client.time_offset} | device_id={client.device_id[:8]}..."
    )
    stats = downloader.run(
        start_date=start,
        end_date=end,
        page_size=args.page_size,
        delta=args.delta,
        max_pages=args.max_pages,
        debug_json=args.debug_json,
        on_log=print,
    )
    print(
        "完成："
        f"页数={stats.pages}, "
        f"匹配={stats.matched}, "
        f"下载={stats.downloaded}, "
        f"跳过={stats.skipped}, "
        f"失败={stats.failed}"
    )
    return 0 if stats.failed == 0 else 2


class App:
    def __init__(self) -> None:
        import tkinter as tk
        from tkinter import filedialog, messagebox, scrolledtext, ttk

        self.tk = tk
        self.ttk = ttk
        self.filedialog = filedialog
        self.messagebox = messagebox
        self.scrolledtext = scrolledtext

        try:
            import ttkbootstrap as tb
            self.tb = tb
            self.root = tb.Window(themename="flatly")
            self.use_bootstrap = True
        except Exception:
            self.tb = None
            self.root = tk.Tk()
            self.use_bootstrap = False

        self.root.title(f"{APP_NAME} v{APP_VERSION}")
        self.root.geometry("980x760")
        self.root.minsize(920, 700)
        self._set_icon()

        self.start_var = tk.StringVar(value="")
        self.end_var = tk.StringVar(value=date.today().isoformat())
        self.output_var = tk.StringVar(value=str((_app_dir() / "downloads").resolve()))
        self.quality_var = tk.StringVar(value="best")
        self.filename_var = tk.StringVar(value="date")
        self.organize_var = tk.BooleanVar(value=True)
        self.text_var = tk.BooleanVar(value=True)
        self.json_var = tk.BooleanVar(value=True)
        self.skip_var = tk.BooleanVar(value=True)
        self.debug_var = tk.BooleanVar(value=False)
        self.status_var = tk.StringVar(value="就绪")
        self.progress_var = tk.DoubleVar(value=0)

        self.stop_event = threading.Event()
        self.worker: threading.Thread | None = None
        self.log_queue: queue.Queue[str] = queue.Queue()

        self._build()
        self.root.after(100, self._flush_log_queue)

    def _resource_path(self, *parts: str) -> Path:
        base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
        return base.joinpath(*parts)

    def _set_icon(self) -> None:
        try:
            ico = self._resource_path("assets", "app_icon.ico")
            if ico.exists():
                self.root.iconbitmap(default=str(ico))
        except Exception:
            pass
        try:
            png = self._resource_path("assets", "app_icon.png")
            if png.exists():
                self._icon_ref = self.tk.PhotoImage(file=str(png))
                self.root.iconphoto(True, self._icon_ref)
        except Exception:
            pass

    def _frame(self, parent, **kwargs):
        return self.tb.Frame(parent, **kwargs) if self.use_bootstrap else self.ttk.Frame(parent, **kwargs)

    def _labelframe(self, parent, text: str, **kwargs):
        if self.use_bootstrap:
            return self.tb.Labelframe(parent, text=text, **kwargs)
        return self.ttk.LabelFrame(parent, text=text, **kwargs)

    def _button(self, parent, text: str, command, bootstyle: str = "", **kwargs):
        if self.use_bootstrap:
            return self.tb.Button(parent, text=text, command=command, bootstyle=bootstyle, **kwargs)
        return self.ttk.Button(parent, text=text, command=command, **kwargs)

    def _check(self, parent, text: str, variable):
        if self.use_bootstrap:
            return self.tb.Checkbutton(
                parent,
                text=text,
                variable=variable,
                bootstyle="round-toggle",
            )
        return self.ttk.Checkbutton(parent, text=text, variable=variable)

    def _combo(self, parent, variable, values):
        widget = self.ttk.Combobox(
            parent,
            textvariable=variable,
            values=values,
            state="readonly",
        )
        return widget

    def _build(self) -> None:
        ttk = self.ttk
        container = self._frame(self.root, padding=20)
        container.pack(fill="both", expand=True)

        ttk.Label(
            container,
            text="小米早安画报下载器",
            font=("Microsoft YaHei UI", 21, "bold"),
        ).pack(anchor="w")
        ttk.Label(
            container,
            text="历史画报批量下载 · 高清地址自动尝试 · 日期/标题自定义命名",
        ).pack(anchor="w", pady=(3, 16))

        cards = self._frame(container)
        cards.pack(fill="x")
        cards.columnconfigure(0, weight=1)
        cards.columnconfigure(1, weight=1)

        range_card = self._labelframe(cards, text="下载范围", padding=16)
        range_card.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        save_card = self._labelframe(cards, text="保存设置", padding=16)
        save_card.grid(row=0, column=1, sticky="nsew", padx=(8, 0))

        ttk.Label(range_card, text="开始日期（可留空）").grid(row=0, column=0, sticky="w")
        ttk.Label(range_card, text="结束日期").grid(row=0, column=1, sticky="w", padx=(12, 0))
        ttk.Entry(range_card, textvariable=self.start_var).grid(row=1, column=0, sticky="ew")
        ttk.Entry(range_card, textvariable=self.end_var).grid(row=1, column=1, sticky="ew", padx=(12, 0))
        ttk.Label(range_card, text="图片质量").grid(row=2, column=0, sticky="w", pady=(14, 0))
        self._combo(range_card, self.quality_var, list(QUALITY_OPTIONS)).grid(
            row=3, column=0, sticky="ew"
        )
        ttk.Label(
            range_card,
            text="best 会依次尝试完整/高清地址和 2160/1440/1080 CDN 地址",
        ).grid(row=4, column=0, columnspan=2, sticky="w", pady=(6, 0))
        range_card.columnconfigure(0, weight=1)
        range_card.columnconfigure(1, weight=1)

        ttk.Label(save_card, text="保存目录").grid(row=0, column=0, columnspan=2, sticky="w")
        ttk.Entry(save_card, textvariable=self.output_var).grid(row=1, column=0, sticky="ew")
        self._button(
            save_card, "选择目录", self._browse, "secondary-outline"
        ).grid(row=1, column=1, padx=(10, 0))
        ttk.Label(save_card, text="图片名格式").grid(row=2, column=0, sticky="w", pady=(14, 0))
        self._combo(save_card, self.filename_var, list(FILENAME_FORMATS)).grid(
            row=3, column=0, sticky="ew"
        )
        ttk.Label(
            save_card,
            text="date=日期 · title=标题 · date_title=日期+标题",
        ).grid(row=4, column=0, columnspan=2, sticky="w", pady=(6, 0))
        save_card.columnconfigure(0, weight=1)

        opts = self._labelframe(container, text="其他选项", padding=14)
        opts.pack(fill="x", pady=(14, 0))
        row = self._frame(opts)
        row.pack(fill="x")
        for text, variable in (
            ("按 年/月 整理", self.organize_var),
            ("保存 TXT 文案", self.text_var),
            ("保存 JSON 元数据", self.json_var),
            ("跳过已下载", self.skip_var),
            ("保存接口原始 JSON", self.debug_var),
        ):
            self._check(row, text, variable).pack(side="left", padx=(0, 16))

        actions = self._frame(container)
        actions.pack(fill="x", pady=(14, 10))
        self.start_button = self._button(actions, "开始下载", self._start, "success", width=14)
        self.start_button.pack(side="left")
        self.stop_button = self._button(
            actions, "停止", self._stop, "danger-outline", width=10, state="disabled"
        )
        self.stop_button.pack(side="left", padx=(10, 0))
        self.scan_button = self._button(
            actions, "仅扫描 1 页", self._scan_one_page, "info-outline", width=12
        )
        self.scan_button.pack(side="left", padx=(10, 0))
        ttk.Label(actions, textvariable=self.status_var).pack(side="right")

        self.progressbar = ttk.Progressbar(
            container,
            variable=self.progress_var,
            maximum=100,
        )
        self.progressbar.pack(fill="x", pady=(0, 10))

        log_card = self._labelframe(container, text="运行日志", padding=10)
        log_card.pack(fill="both", expand=True)
        self.log = self.scrolledtext.ScrolledText(
            log_card,
            height=18,
            wrap="word",
            font=("Consolas", 10),
            relief="flat",
            bd=0,
        )
        self.log.pack(fill="both", expand=True)
        self.log.configure(state="disabled")

    def _browse(self) -> None:
        selected = self.filedialog.askdirectory(initialdir=self.output_var.get())
        if selected:
            self.output_var.set(selected)

    def _append_log(self, message: str) -> None:
        self.log_queue.put(message)

    def _flush_log_queue(self) -> None:
        while True:
            try:
                message = self.log_queue.get_nowait()
            except queue.Empty:
                break
            self.log.configure(state="normal")
            self.log.insert("end", message + "\n")
            self.log.see("end")
            self.log.configure(state="disabled")
        self.root.after(100, self._flush_log_queue)

    def _collect_params(self) -> tuple[date | None, date | None, Path]:
        start = parse_date(self.start_var.get())
        end = parse_date(self.end_var.get())
        if start and end and start > end:
            raise ValueError("开始日期不能晚于结束日期")
        return start, end, Path(self.output_var.get()).expanduser()

    def _scan_one_page(self) -> None:
        if self.worker and self.worker.is_alive():
            return
        try:
            start, end, output = self._collect_params()
        except Exception as exc:
            self.messagebox.showerror("参数错误", str(exc))
            return

        self._append_log("=" * 60)
        self._append_log("仅扫描第一页，不下载图片。")

        def worker() -> None:
            try:
                client = XiaomiPictorialClient(width=DEFAULT_WIDTH)
                downloader = MorningDownloader(
                    client,
                    output_dir=output,
                    organize_by_month=self.organize_var.get(),
                    save_text=self.text_var.get(),
                    save_json=self.json_var.get(),
                    skip_existing=self.skip_var.get(),
                    dry_run=True,
                    quality_mode=self.quality_var.get(),
                    filename_mode=self.filename_var.get(),
                )
                downloader.run(
                    start_date=start,
                    end_date=end,
                    max_pages=1,
                    debug_json=self.debug_var.get(),
                    on_log=self._append_log,
                )
            except Exception as exc:
                self._append_log(f"[错误] {exc}")

        threading.Thread(target=worker, daemon=True).start()

    def _start(self) -> None:
        if self.worker and self.worker.is_alive():
            return

        try:
            start, end, output = self._collect_params()
        except Exception as exc:
            self.messagebox.showerror("参数错误", str(exc))
            return

        self.stop_event.clear()
        self.start_button.configure(state="disabled")
        self.stop_button.configure(state="normal")
        self.status_var.set("正在运行…")
        self.progress_var.set(5)
        self._append_log("=" * 60)
        self._append_log(
            f"范围：{start or '最早可获取'} ~ {end or '最新'} | "
            f"质量：{self.quality_var.get()} | 命名：{self.filename_var.get()}"
        )

        def worker() -> None:
            try:
                client = XiaomiPictorialClient(width=DEFAULT_WIDTH)
                downloader = MorningDownloader(
                    client,
                    output_dir=output,
                    organize_by_month=self.organize_var.get(),
                    save_text=self.text_var.get(),
                    save_json=self.json_var.get(),
                    skip_existing=self.skip_var.get(),
                    quality_mode=self.quality_var.get(),
                    filename_mode=self.filename_var.get(),
                )

                def progress(stats: DownloadStats) -> None:
                    done = stats.downloaded + stats.skipped + stats.failed
                    total = max(stats.matched, done, 1)
                    percent = 10 + min(85, done / total * 85)
                    self.root.after(0, lambda: self.progress_var.set(percent))
                    self.root.after(
                        0,
                        lambda: self.status_var.set(
                            f"页 {stats.pages} | 下载 {stats.downloaded} | "
                            f"跳过 {stats.skipped} | 失败 {stats.failed}"
                        ),
                    )

                stats = downloader.run(
                    start_date=start,
                    end_date=end,
                    debug_json=self.debug_var.get(),
                    on_log=self._append_log,
                    on_progress=progress,
                    should_stop=self.stop_event.is_set,
                )
                self._append_log(
                    f"任务结束：下载 {stats.downloaded}，"
                    f"跳过 {stats.skipped}，失败 {stats.failed}"
                )
            except Exception as exc:
                self._append_log(f"[错误] {exc}")
                self.root.after(
                    0,
                    lambda: self.messagebox.showerror("运行失败", str(exc)),
                )
            finally:
                self.root.after(0, self._finished)

        self.worker = threading.Thread(target=worker, daemon=True)
        self.worker.start()

    def _stop(self) -> None:
        self.stop_event.set()
        self.stop_button.configure(state="disabled")
        self.status_var.set("正在停止…")

    def _finished(self) -> None:
        self.start_button.configure(state="normal")
        self.stop_button.configure(state="disabled")
        self.progress_var.set(0 if self.stop_event.is_set() else 100)
        self.status_var.set("已停止" if self.stop_event.is_set() else "完成")

    def run(self) -> None:
        self.root.mainloop()


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if args.gui or len(sys.argv) == 1:
        App().run()
        return 0

    try:
        return run_cli(args)
    except KeyboardInterrupt:
        print("\n已取消")
        return 130
    except Exception as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
