# Steam Announcement Monitor

A free weekly collector for developer announcements from a list of Steam AppIDs stored in a published Google Sheet.

## What it does

1. Downloads the configured Google Sheets CSV.
2. Reads Steam AppIDs from column A (`appid_column_index: 0`).
3. Calls Steam's public `ISteamNews/GetNewsForApp/v2` endpoint.
4. Restricts results to `steam_community_announcements` so unrelated press/news feeds are excluded.
5. Re-scans a rolling recent window and emits only announcements not seen in previous runs.
6. Avoids emitting the same Steam announcement twice.
7. Writes both JSON and Markdown files for later analysis by ChatGPT.
8. Runs automatically every Sunday at 08:00 in `Europe/Bucharest` via GitHub Actions.

No Steam API key, Google API key, OpenAI API key, or paid server is required for the collector.

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
│   ├── latest_announcements.json   # generated
│   ├── latest_announcements.md     # generated; easiest file for ChatGPT
│   └── latest_run.json             # generated diagnostics
├── tests/
│   └── test_monitor.py
├── CHATGPT_TASK_PROMPT.md
├── config.json
├── requirements.txt
├── steam_monitor.py
└── README.md
```

## Current source spreadsheet

The configured source is:

```text
https://docs.google.com/spreadsheets/d/e/2PACX-1vSc9l_vwQZxYR39HSApnjUabezkO3bMMMWPfNoFqlG4FyfMsB-7rG4C3zZewSGgHrjDN-ilrB-g3Wtz/pub?gid=0&single=true&output=csv
```

Column A is read as the Steam AppID column.

The script auto-detects a game-name column if the CSV has a header named `game`, `game name`, `name`, `title`, or `steam name`. If no name column is found, it resolves names only for games that produced new announcements, using Steam Store metadata, and caches the result in `data/game_names.json`.

## GitHub setup

### 1. Create the repository

Create a **private** GitHub repository, for example:

```text
steam-monitor
```

Upload/commit all files in this project to the default branch (`main` is recommended).

### 2. Enable GitHub Actions

Open the repository's **Actions** tab and enable workflows if GitHub asks you to.

The included workflow supports:

- automatic weekly execution
- manual execution from the Actions tab
- a manual lookback override for testing/backfills

### 3. Ensure the workflow can commit generated files

The YAML requests:

```yaml
permissions:
  contents: write
```

For most personal repositories that is sufficient. If the final `git push` step receives a permissions/403 error, open:

```text
Repository → Settings → Actions → General → Workflow permissions
```

and allow **Read and write permissions** for the GitHub Actions token.

### 4. Run it manually first

Go to:

```text
Actions → Weekly Steam Monitor → Run workflow
```

For the first normal test, leave `lookback_days` blank. The first run uses the last 8 days.

For a controlled test, enter for example:

```text
2
```

That forces the collector to look back only two days for that manual run.

### 5. Check the generated output

After a successful run, inspect:

```text
output/latest_announcements.md
output/latest_announcements.json
output/latest_run.json
```

`latest_announcements.md` is the easiest file to feed into a ChatGPT scheduled task.

## Schedule

The workflow currently runs:

```yaml
cron: "0 8 * * 0"
timezone: "Europe/Bucharest"
```

This means **Sunday at 08:00 Romania time**, with daylight-saving changes handled by the timezone-aware GitHub schedule.

Change the hour/day in `.github/workflows/steam-monitor.yml` if desired.

## State and duplicate prevention

`data/state.json` stores:

- the timestamp of the last successful run
- Steam announcement GIDs that have already been emitted

The first run checks the previous 8 days. Normal weekly runs re-scan the previous 15 days. Because processed GIDs are stored, previously reported announcements are not emitted twice. The 15-day rolling window also allows the monitor to recover from a temporary API failure or one missed weekly run.

Processed IDs are retained for 90 days.

## Steam request behavior

The collector requests only:

```text
feeds=steam_community_announcements
```

It does not scan Steam event pages, sales, store promotions, or external gaming-news feeds.

The collector paginates when necessary, retrieving up to 4 pages × 50 announcements for an unusually active game during the relevant lookback window.

It uses six concurrent workers and retries HTTP 429/5xx errors with exponential backoff.

A failure for one AppID is logged in `output/latest_run.json` but does not abort the entire weekly run.

## Important limitation: unreleased games

Valve documents the public `GetNewsForApp` endpoint separately from the publisher-authenticated `GetNewsForAppAuthed` endpoint and explicitly notes that the publisher version can return information for unreleased games.

Therefore, test several unreleased games from your database after setup. If public API coverage is incomplete for those titles, add an announcement-page/RSS fallback later. The rest of this architecture does not need to change.

## Configuration reference

`config.json` contains the settings you are most likely to change.

### Spreadsheet

```json
"appid_column_index": 0
```

Columns are zero-based, so `0` means column A, `1` means B, etc.

If you know the exact game-name column, you can set it explicitly, for example:

```json
"name_column_index": 1
```

for column B. Otherwise leave it `null` for automatic detection/fallback name resolution.

### Lookback

```json
"first_run_lookback_days": 8,
"regular_lookback_days": 15
```

### Steam

```json
"page_size": 50,
"max_pages_per_game": 4,
"max_content_chars": 5000,
"max_workers": 6,
"timeout_seconds": 30
```

`max_content_chars` limits the text stored per announcement before ChatGPT sees it. This helps keep weekly AI context reasonable while preserving enough content for classification.

## Connecting the result to ChatGPT

Once the collector is producing `output/latest_announcements.md`, connect GitHub to ChatGPT and create a weekly scheduled task after the GitHub workflow has run.

A ready-to-use analysis prompt is included in:

```text
CHATGPT_TASK_PROMPT.md
```

A sensible sequence is:

```text
Sunday 08:00  GitHub collector runs
Sunday 09:00  ChatGPT scheduled task reads the generated file and creates the digest
```

Keep at least some buffer between the two jobs.

## Local/manual execution

If you want to test on a computer with Python installed:

```bash
python -m pip install -r requirements.txt
python steam_monitor.py
```

To force a custom lookback on macOS/Linux:

```bash
FORCE_LOOKBACK_DAYS=2 python steam_monitor.py
```

PowerShell:

```powershell
$env:FORCE_LOOKBACK_DAYS="2"
python steam_monitor.py
```

## Troubleshooting

### `No valid Steam AppIDs were found`

Check that column A really contains plain numeric AppIDs or Steam URLs containing `/app/<appid>/`.

### Google Sheet request fails

Open the configured CSV URL in a private/incognito browser window. Because this implementation uses a public CSV, it must be accessible without signing into Google.

### Some games show no news

Possible reasons include:

- no developer community announcement was published in the collection window
- the game uses another Steam news feed rather than `steam_community_announcements`
- public API coverage differs for an unreleased title

Check `output/latest_run.json` for request failures before concluding that a game had no announcements.

### Git push fails with 403

Allow read/write workflow permissions in the repository's Actions settings, as described above.
