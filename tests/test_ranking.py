import json
import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import ranking  # noqa: E402

NOW = datetime(2026, 9, 29, tzinfo=timezone.utc)
SAMPLE = json.loads((ROOT / "tests" / "sample_repos.json").read_text(encoding="utf-8"))
CONFIG = json.loads(ranking.CONFIG.read_text(encoding="utf-8"))


class RankingTest(unittest.TestCase):
    def test_sorted_by_stars_desc(self):
        entries = ranking.build_entries(CONFIG["frontend"]["repos"], SAMPLE, NOW, 365)
        stars = [e.stars for e in entries]
        self.assertEqual(stars, sorted(stars, reverse=True))
        self.assertEqual(entries[0].name, "React")

    def test_excludes_archived_stale_and_missing(self):
        names = {e.name for e in ranking.build_entries(CONFIG["backend"]["repos"], SAMPLE, NOW, 365)}
        self.assertNotIn("Axum", names)      # 365 日以上 push なし
        self.assertNotIn("Phoenix", names)   # 404
        front = {e.name for e in ranking.build_entries(CONFIG["frontend"]["repos"], SAMPLE, NOW, 365)}
        self.assertNotIn("Ember", front)     # アーカイブ済み

    def test_stale_check_can_be_disabled(self):
        names = {e.name for e in ranking.build_entries(CONFIG["backend"]["repos"], SAMPLE, NOW, 0)}
        self.assertIn("Axum", names)

    def test_text_format(self):
        entries = [ranking.Entry("React", "a/b", 232_100), ranking.Entry("Lit", "c/d", 950)]
        text = ranking.build_text("Frontend Framework", entries, NOW)
        self.assertEqual(text,
                         "🏆 Frontend Framework ★ Ranking (2026-09-29)\n"
                         "1. React  ★232.1k\n"
                         "2. Lit    ★   950\n")

    def test_config_has_no_duplicates(self):
        repos = [r["repo"].lower() for c in CONFIG.values() for r in c["repos"]]
        self.assertEqual(len(repos), len(set(repos)))


if __name__ == "__main__":
    unittest.main()
