from __future__ import annotations

import csv
import hashlib
import html
import json
import os
import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from io import StringIO
from pathlib import Path
from typing import Any
import xml.etree.ElementTree as ET

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


CONFIG_PATH = Path(os.environ.get("STEAM_MONITOR_CONFIG", "config.json"))
STEAM_RSS_URL_TEMPLATE = "https://store.steampowered.com/feeds/news/app/{appid}/?l=english"
STEAM_APPDETAILS_URL = "https://store.steampowered.com/api/appdetails"
USER_AGENT = (
    "SteamAnnouncementMonitor/1.0 "
    "(+https://github.com/; weekly personal research monitor)"
)

_thread_local = threading.local()


@dataclass(frozen=True)
class Game:
    appid: int
    name: str | None = None


class MonitorError(RuntimeError):
    pass


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_utc(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_iso_utc(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except (ValueError, TypeError):
        return None


def load_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except (json.JSONDecodeError, OSError):
        return default


def save_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def load_config() -> dict[str, Any]:
    config = load_json(CONFIG_PATH, None)
    if not isinstance(config, dict):
        raise MonitorError(f"Could not load configuration from {CONFIG_PATH}")
    return config


def build_session() -> requests.Session:
    retry = Retry(
        total=4,
        connect=4,
        read=4,
        status=4,
        backoff_factor=1.0,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=frozenset({"GET"}),
        respect_retry_after_header=True,
    )
    adapter = HTTPAdapter(max_retries=retry, pool_connections=20, pool_maxsize=20)
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT, "Accept": "application/rss+xml,application/xml,text/xml,text/html,*/*"})
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


def get_thread_session() -> requests.Session:
    session = getattr(_thread_local, "session", None)
    if session is None:
        session = build_session()
        _thread_local.session = session
    return session


def extract_appid(value: str) -> int | None:
    text = (value or "").strip()
    if not text:
        return None

    # Handles plain IDs, spreadsheet values such as 123456.0, and Steam URLs.
    plain = re.fullmatch(r"(\d+)(?:\.0+)?", text)
    if plain:
        appid = int(plain.group(1))
        return appid if 0 < appid <= 4_294_967_295 else None

    url_match = re.search(r"(?:/app/|appid[=/])(\d+)", text, flags=re.IGNORECASE)
    if url_match:
        appid = int(url_match.group(1))
        return appid if 0 < appid <= 4_294_967_295 else None

    return None


def normalize_header(value: str) -> str:
    return re.sub(r"\s+", " ", (value or "").strip().lower())


def infer_name_column(header: list[str], candidates: list[str]) -> int | None:
    normalized = [normalize_header(cell) for cell in header]
    candidate_set = {normalize_header(item) for item in candidates}
    for index, value in enumerate(normalized):
        if value in candidate_set:
            return index
    return None


def fetch_games(config: dict[str, Any]) -> tuple[list[Game], dict[str, Any]]:
    session = build_session()
    timeout = int(config["steam"].get("timeout_seconds", 30))
    response = session.get(config["sheet_url"], timeout=timeout)
    response.raise_for_status()

    # utf-8-sig safely strips a BOM if Google includes one.
    text = response.content.decode("utf-8-sig", errors="replace")
    rows = [row for row in csv.reader(StringIO(text)) if any(cell.strip() for cell in row)]
    if not rows:
        raise MonitorError("The Google Sheet CSV returned no rows.")

    appid_index = int(config.get("appid_column_index", 0))
    configured_name_index = config.get("name_column_index")
    name_index = int(configured_name_index) if configured_name_index is not None else None

    first_appid = extract_appid(rows[0][appid_index] if len(rows[0]) > appid_index else "")
    has_header = first_appid is None

    if has_header and name_index is None:
        name_index = infer_name_column(rows[0], config.get("name_header_candidates", []))

    data_rows = rows[1:] if has_header else rows
    by_appid: dict[int, Game] = {}
    invalid_rows = 0

    for row in data_rows:
        if len(row) <= appid_index:
            invalid_rows += 1
            continue
        appid = extract_appid(row[appid_index])
        if appid is None:
            invalid_rows += 1
            continue

        name: str | None = None
        if name_index is not None and len(row) > name_index:
            candidate_name = row[name_index].strip()
            if candidate_name:
                name = candidate_name

        existing = by_appid.get(appid)
        if existing is None or (not existing.name and name):
            by_appid[appid] = Game(appid=appid, name=name)

    games = sorted(by_appid.values(), key=lambda game: game.appid)
    if not games:
        raise MonitorError("No valid Steam AppIDs were found in the configured spreadsheet column.")

    sheet_info = {
        "rows_read": len(data_rows),
        "unique_appids": len(games),
        "invalid_or_blank_rows": invalid_rows,
        "header_detected": has_header,
        "appid_column_index": appid_index,
        "name_column_index": name_index,
    }
    return games, sheet_info


def clean_steam_content(raw: str, max_chars: int) -> str:
    if not raw:
        return ""

    text = html.unescape(raw)
    soup = BeautifulSoup(text, "html.parser")
    text = soup.get_text("\n")

    # Remove Steam image/localization macros and BBCode media while retaining readable text.
    text = re.sub(r"\{STEAM_[^}]+\}", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"\[img\].*?\[/img\]", " ", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"\[url=[^\]]+\](.*?)\[/url\]", r"\1", text, flags=re.IGNORECASE | re.DOTALL)
    text = re.sub(r"\[/?(?:b|i|u|h\d|list|olist|quote|code|spoiler|table|tr|td|th)[^\]]*\]", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"\[[^\]]+\]", " ", text)
    text = text.replace("\r", "")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n[ \t]+", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()

    if max_chars > 0 and len(text) > max_chars:
        text = text[:max_chars].rstrip() + "\n\n[Content truncated by collector]"
    return text


def parse_rss_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = parsedate_to_datetime(value.strip())
    except (TypeError, ValueError, OverflowError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def extract_rss_item_id(appid: int, guid: str, link: str, published: int, title: str) -> str:
    # Steam News Hub links normally contain the same numeric announcement ID used
    # by GetNewsForApp, so this preserves duplicate state when migrating from API -> RSS.
    for candidate in (link, guid):
        match = re.search(r"/(?:view|detail)/(\d+)(?:[/?#]|$)", candidate or "", flags=re.IGNORECASE)
        if match:
            return match.group(1)
    guid_text = (guid or "").strip()
    if re.fullmatch(r"\d+", guid_text):
        return guid_text
    if guid_text:
        return f"rss:{appid}:{guid_text}"
    digest = hashlib.sha256(f"{appid}|{published}|{title}|{link}".encode("utf-8")).hexdigest()[:24]
    return f"rss:{appid}:{digest}"


def fetch_news_for_game(
    game: Game,
    since_epoch: int,
    now_epoch: int,
    config: dict[str, Any],
) -> tuple[list[dict[str, Any]], str | None]:
    steam_cfg = config["steam"]
    session = get_thread_session()
    timeout = int(steam_cfg.get("timeout_seconds", 30))
    max_chars = int(steam_cfg.get("max_content_chars", 5000))
    template = steam_cfg.get("rss_url_template", STEAM_RSS_URL_TEMPLATE)
    rss_url = str(template).format(appid=game.appid)

    try:
        response = session.get(rss_url, timeout=timeout)
        response.raise_for_status()
        root = ET.fromstring(response.content)

        collected: dict[str, dict[str, Any]] = {}
        for item in root.findall(".//item"):
            title = (item.findtext("title") or "").strip()
            link = (item.findtext("link") or "").strip()
            guid = (item.findtext("guid") or "").strip()
            description = item.findtext("description") or ""
            pub_date_raw = item.findtext("pubDate") or ""
            published_dt = parse_rss_date(pub_date_raw)
            if published_dt is None:
                continue
            published = int(published_dt.timestamp())
            if published < since_epoch or published > now_epoch + 300:
                continue

            # Keep Steam-hosted News Hub/community announcement entries only. This
            # avoids passing unrelated external press links to the weekly digest.
            steam_news_link = bool(
                re.search(r"https?://(?:store\.steampowered\.com/news/app/|steamcommunity\.com/(?:games/\d+/announcements/detail/|gid/\d+))", link, flags=re.IGNORECASE)
            )
            if link and not steam_news_link:
                continue

            author = (item.findtext("author") or "").strip()
            if not author:
                author = (item.findtext("{http://purl.org/dc/elements/1.1/}creator") or "").strip()

            gid = extract_rss_item_id(game.appid, guid, link, published, title)
            collected[gid] = {
                "gid": gid,
                "appid": game.appid,
                "game_name": game.name,
                "title": title,
                "author": author,
                "url": link or guid,
                "published_unix": published,
                "published_utc": iso_utc(published_dt),
                "source": "steam_rss",
                "guid": guid,
                "content": clean_steam_content(description, max_chars),
            }

        result = sorted(collected.values(), key=lambda item: item["published_unix"], reverse=True)
        return result, None
    except (requests.RequestException, ET.ParseError, ValueError, TypeError) as exc:
        return [], f"{type(exc).__name__}: {exc}"


def resolve_game_name(appid: int, session: requests.Session, timeout: int) -> str | None:
    try:
        response = session.get(
            STEAM_APPDETAILS_URL,
            params={"appids": appid, "filters": "basic", "l": "english", "cc": "us"},
            timeout=timeout,
        )
        response.raise_for_status()
        payload = response.json()
        entry = payload.get(str(appid), {})
        if entry.get("success") and isinstance(entry.get("data"), dict):
            name = entry["data"].get("name")
            if isinstance(name, str) and name.strip():
                return name.strip()
    except (requests.RequestException, ValueError, TypeError):
        return None
    return None


def determine_since(config: dict[str, Any], state: dict[str, Any], now: datetime) -> datetime:
    force_days = os.environ.get("FORCE_LOOKBACK_DAYS", "").strip()
    if force_days:
        try:
            days = max(1, int(force_days))
            return now - timedelta(days=days)
        except ValueError:
            print(f"Warning: ignoring invalid FORCE_LOOKBACK_DAYS={force_days!r}")

    last_success = parse_iso_utc(state.get("last_success_utc"))
    if last_success is None:
        days = int(config.get("first_run_lookback_days", 8))
    else:
        # Re-scan a wider rolling window every week. Processed GIDs prevent duplicates,
        # while the overlap lets a failed/skipped prior run recover automatically.
        days = int(config.get("regular_lookback_days", 15))
    return now - timedelta(days=max(1, days))


def prune_processed(processed: dict[str, Any], cutoff_epoch: int) -> dict[str, int]:
    pruned: dict[str, int] = {}
    for gid, value in processed.items():
        try:
            timestamp = int(value)
        except (TypeError, ValueError):
            continue
        if timestamp >= cutoff_epoch:
            pruned[str(gid)] = timestamp
    return pruned


def write_markdown(path: Path, metadata: dict[str, Any], announcements: list[dict[str, Any]]) -> None:
    lines: list[str] = [
        "# Steam announcements collected",
        "",
        f"Generated: **{metadata['generated_utc']}**",
        f"Collection window starts: **{metadata['since_utc']}**",
        f"Games checked: **{metadata['games_checked']}**",
        f"New announcements: **{metadata['new_announcements']}**",
        f"Games with request errors: **{metadata['games_with_errors']}**",
        "",
        "> This file is the raw weekly input for ChatGPT. It has not been AI-classified yet.",
        "> Items are collected from each game's Steam News RSS feed and restricted to Steam-hosted News Hub/community-announcement links.",
        "",
    ]

    if not announcements:
        lines.extend(["## No new announcements", "", "No unprocessed announcements were collected in this run.", ""])
    else:
        for index, item in enumerate(announcements, start=1):
            game_name = item.get("game_name") or f"Steam App {item['appid']}"
            lines.extend(
                [
                    f"## {index}. {game_name}",
                    "",
                    f"- **AppID:** {item['appid']}",
                    f"- **Title:** {item.get('title') or '(untitled)'}",
                    f"- **Published:** {item['published_utc']}",
                    f"- **Author:** {item.get('author') or '(not provided)'}",
                    f"- **URL:** {item.get('url') or '(not provided)'}",
                    f"- **GID:** {item['gid']}",
                    "",
                    "### Announcement text",
                    "",
                    item.get("content") or "(No text returned by Steam.)",
                    "",
                    "---",
                    "",
                ]
            )

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    config = load_config()
    state_path = Path(config["state"]["path"])
    name_cache_path = Path(config["state"]["name_cache_path"])
    output_dir = Path(config["output"]["directory"])
    output_dir.mkdir(parents=True, exist_ok=True)

    state = load_json(state_path, {"version": 1, "last_success_utc": None, "processed": {}})
    if not isinstance(state, dict):
        state = {"version": 1, "last_success_utc": None, "processed": {}}
    processed = state.get("processed", {})
    if not isinstance(processed, dict):
        processed = {}

    name_cache = load_json(name_cache_path, {})
    if not isinstance(name_cache, dict):
        name_cache = {}

    now = utc_now()
    since = determine_since(config, state, now)
    since_epoch = int(since.timestamp())
    now_epoch = int(now.timestamp())

    print(f"Collection window: {iso_utc(since)} -> {iso_utc(now)}")
    games, sheet_info = fetch_games(config)
    print(f"Loaded {len(games)} unique AppIDs from the Google Sheet.")

    max_workers = max(1, int(config["steam"].get("max_workers", 6)))
    all_candidates: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_map = {
            executor.submit(fetch_news_for_game, game, since_epoch, now_epoch, config): game
            for game in games
        }
        completed = 0
        for future in as_completed(future_map):
            game = future_map[future]
            completed += 1
            try:
                items, error = future.result()
            except Exception as exc:  # Defensive: keep one unexpected game failure from aborting the run.
                items, error = [], f"Unexpected {type(exc).__name__}: {exc}"
            if error:
                errors.append({"appid": game.appid, "game_name": game.name, "error": error})
            all_candidates.extend(items)
            if completed % 50 == 0 or completed == len(games):
                print(f"Checked {completed}/{len(games)} games...")

    # Deduplicate across games/items and ignore announcements already emitted on a previous run.
    candidate_by_gid: dict[str, dict[str, Any]] = {}
    for item in all_candidates:
        candidate_by_gid[item["gid"]] = item
    new_items = [item for gid, item in candidate_by_gid.items() if gid not in processed]
    new_items.sort(key=lambda item: item["published_unix"], reverse=True)

    # Fill missing game names only for games that actually produced new announcements.
    if config["steam"].get("resolve_missing_names_via_store", True):
        timeout = int(config["steam"].get("timeout_seconds", 30))
        main_session = build_session()
        missing_appids = sorted({item["appid"] for item in new_items if not item.get("game_name")})
        for appid in missing_appids:
            cached = name_cache.get(str(appid))
            if isinstance(cached, str) and cached.strip():
                resolved = cached.strip()
            else:
                resolved = resolve_game_name(appid, main_session, timeout)
                if resolved:
                    name_cache[str(appid)] = resolved
            if resolved:
                for item in new_items:
                    if item["appid"] == appid and not item.get("game_name"):
                        item["game_name"] = resolved

    # Keep a bounded amount of processed state. The lookback window is much shorter than this retention.
    retention_days = int(config["state"].get("processed_retention_days", 90))
    processed_cutoff = int((now - timedelta(days=retention_days)).timestamp())
    processed = prune_processed(processed, processed_cutoff)
    for item in new_items:
        processed[item["gid"]] = int(item["published_unix"])

    metadata = {
        "generated_utc": iso_utc(now),
        "since_utc": iso_utc(since),
        "games_checked": len(games),
        "new_announcements": len(new_items),
        "games_with_errors": len(errors),
        "sheet": sheet_info,
        "source": "steam_rss",
        "errors": errors,
    }

    json_payload = {"metadata": metadata, "announcements": new_items}
    json_path = output_dir / config["output"]["json_file"]
    markdown_path = output_dir / config["output"]["markdown_file"]
    run_path = output_dir / config["output"]["run_file"]

    save_json(json_path, json_payload)
    write_markdown(markdown_path, metadata, new_items)
    save_json(run_path, metadata)
    save_json(name_cache_path, name_cache)

    state = {
        "version": 1,
        "last_success_utc": iso_utc(now),
        "processed": processed,
    }
    save_json(state_path, state)

    print(f"New announcements written: {len(new_items)}")
    print(f"Request errors: {len(errors)}")
    print(f"JSON: {json_path}")
    print(f"Markdown: {markdown_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
