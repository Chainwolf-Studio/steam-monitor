import unittest
from datetime import timezone

from steam_monitor import (
    clean_steam_content,
    extract_appid,
    extract_rss_item_id,
    infer_name_column,
    parse_rss_date,
)


class SteamMonitorTests(unittest.TestCase):
    def test_extract_plain_appid(self):
        self.assertEqual(extract_appid("1363080"), 1363080)

    def test_extract_spreadsheet_float_appid(self):
        self.assertEqual(extract_appid("1363080.0"), 1363080)

    def test_extract_appid_from_url(self):
        self.assertEqual(
            extract_appid("https://store.steampowered.com/app/1363080/Manor_Lords/"),
            1363080,
        )

    def test_invalid_appid(self):
        self.assertIsNone(extract_appid("AppID"))
        self.assertIsNone(extract_appid(""))

    def test_name_column_detection(self):
        header = ["AppID", "Developer", "Game Name", "Release Date"]
        self.assertEqual(infer_name_column(header, ["game", "game name", "name"]), 2)

    def test_clean_content(self):
        source = "<b>Hello</b> [url=https://example.com]world[/url] [img]x.png[/img]"
        cleaned = clean_steam_content(source, 5000)
        self.assertIn("Hello", cleaned)
        self.assertIn("world", cleaned)
        self.assertNotIn("x.png", cleaned)

    def test_parse_rss_date(self):
        parsed = parse_rss_date("Thu, 24 Sep 2026 15:30:00 +0000")
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed.tzinfo, timezone.utc)
        self.assertEqual(parsed.year, 2026)
        self.assertEqual(parsed.day, 24)

    def test_rss_item_id_from_store_news_link(self):
        self.assertEqual(
            extract_rss_item_id(
                1401630,
                "",
                "https://store.steampowered.com/news/app/1401630/view/4691152537223626228",
                0,
                "Example",
            ),
            "4691152537223626228",
        )

    def test_rss_item_id_from_community_link(self):
        self.assertEqual(
            extract_rss_item_id(
                1401630,
                "",
                "https://steamcommunity.com/games/1401630/announcements/detail/4691152537223626228",
                0,
                "Example",
            ),
            "4691152537223626228",
        )


if __name__ == "__main__":
    unittest.main()
