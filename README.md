# Steam Announcement Monitor

A free weekly collector for developer/news-hub announcements from a list of Steam AppIDs stored in a published Google Sheet.

## What it does

1. Downloads the configured Google Sheets CSV.
2. Reads Steam AppIDs from column A (`appid_column_index: 0`).
3. Reads each game's Steam News RSS feed: `https://store.steampowered.com/feeds/news/app/APPID/?l=english`.
4. Keeps Steam-hosted News Hub/community-announcement items and ignores external press links.
5. Re-scans a rolling recent window and emits only announcements not seen in previous runs.
6. Avoids emitting the same Steam announcement twice.
7. Writes both JSON and Markdown files for later analysis by ChatGPT.
8. Runs automatically every Sunday at 08:00 in `Europe/Bucharest` via GitHub Actions.

No Steam API key, Google API key, OpenAI API key, or paid server is required for the collector.

## Why RSS is used

The first version used `ISteamNews/GetNewsForApp/v2`, but testing showed that recent announcements visible in a game's Steam News Hub could be missing from that API response. AppID `1401630` was used as a validation case: its current announcement appeared in the Steam RSS feed while the API-based monitor had no results newer than September 16, 2026.

For this monitor, the RSS feed is therefore the primary source because the goal is to follow what developers actually publish on their Steam game news pages.

## Repository structure

```text
steam-monitor/
├── .github/
│   └── workflows/
│       └── steam-monitor.yml
├── data/
│   ├── state.json
│   └── game_names.json
├── output/
│   ├── latest_announcements.json
│   ├── latest_announcements.md
│   └── latest_run.json
├── tests/
│   └── test_monitor.py
├── CHATGPT_TASK_PROMPT.md
├── config.json
├── requirements.txt
├── steam_monitor.py
└── README.md
```

## Source spreadsheet

The configured source is the published Google Sheets CSV in `config.json`. Column A is read as the Steam AppID column.

The script auto-detects a game-name column if the CSV header contains `game`, `game name`, `name`, `title`, or `steam name`. If needed, it resolves missing names only for games that produced new announcements and caches them in `data/game_names.json`.

## GitHub Actions

The workflow supports scheduled and manual execution. The runner is pinned to:

```yaml
runs-on: ubuntu-24.04
```

This deliberately avoids an unexpected environment change when GitHub migrates `ubuntu-latest` from Ubuntu 24.04 to Ubuntu 26.04.

The schedule is Sunday at 08:00 Romania time:

```yaml
cron: "0 8 * * 0"
timezone: "Europe/Bucharest"
```

To run manually:

```text
Actions → Weekly Steam Monitor → Run workflow
```

For a temporary backfill/test, set `lookback_days`, for example `30`. Leave it blank for normal runs.

## State and duplicate prevention

`data/state.json` stores the timestamp of the last successful run and processed announcement IDs.

The first run checks the previous 8 days. Normal weekly runs re-scan the previous 15 days. The overlap is intentional: if Steam exposes a feed item late or one scheduled run is missed, a later run can still recover it. Processed IDs prevent duplicates.

When possible, the script extracts the numeric Steam announcement ID from `/view/<id>` or `/detail/<id>` links. This also preserves compatibility with IDs already stored by the older API-based collector.

Processed IDs are retained for 90 days.

## Steam RSS behavior

Each game requires one RSS request per run. With roughly 436 games, that is roughly 436 Steam requests per weekly run.

The collector uses six concurrent workers and retries HTTP 429/5xx responses with exponential backoff. A failure for one AppID is logged in `output/latest_run.json` and does not abort the entire run.

The RSS feed itself has a finite number of recent entries. The weekly cadence plus 15-day overlap is designed for normal developer announcement frequency. If a particular game publishes an unusually large number of announcements in a short period, it is worth checking that title separately.

## Output

After a successful run, inspect:

```text
output/latest_announcements.md
output/latest_announcements.json
output/latest_run.json
```

`latest_announcements.md` is the easiest input for a ChatGPT scheduled task. A ready-to-use prompt is included in `CHATGPT_TASK_PROMPT.md`.

## Local/manual execution

```bash
python -m pip install -r requirements.txt
python steam_monitor.py
```

Temporary lookback override on macOS/Linux:

```bash
FORCE_LOOKBACK_DAYS=30 python steam_monitor.py
```

PowerShell:

```powershell
$env:FORCE_LOOKBACK_DAYS="30"
python steam_monitor.py
```

## Troubleshooting

### No announcements are returned

Open this URL for a known AppID and confirm the expected post is present:

```text
https://store.steampowered.com/feeds/news/app/APPID/?l=english
```

Then inspect `output/latest_run.json` for request or XML parsing errors.

### Git push fails with 403

Open:

```text
Repository → Settings → Actions → General → Workflow permissions
```

and allow read/write permissions for the GitHub Actions token.
