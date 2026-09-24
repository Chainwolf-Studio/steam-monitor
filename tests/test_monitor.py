import unittest

from steam_monitor import clean_steam_content, extract_appid, infer_name_column


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


if __name__ == "__main__":
    unittest.main()
