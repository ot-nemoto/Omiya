import io
import json
import sys
import tempfile
import unittest
import urllib.error
from contextlib import redirect_stderr
from unittest import mock
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import history  # noqa: E402
import ranking  # noqa: E402

NOW = datetime(2026, 9, 29, tzinfo=timezone.utc)
SAMPLE = json.loads((ROOT / "tests" / "sample_repos.json").read_text(encoding="utf-8"))
CONFIG = json.loads(ranking.CONFIG.read_text(encoding="utf-8"))


def setUpModule():
    # ::warning:: 出力が CI のテストステップで注釈として出ないように黙らせる
    patcher = mock.patch.object(ranking, "warn")
    patcher.start()
    unittest.addModuleCleanup(patcher.stop)


class RankingTest(unittest.TestCase):
    def test_config_has_no_duplicates(self):
        repos = [r["repo"].lower() for c in CONFIG.values() for r in c["repos"]]
        self.assertEqual(len(repos), len(set(repos)))

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
        entries = [ranking.Entry("React", "a/b", 232_100, "JavaScript"),
                   ranking.Entry("Lit", "c/d", 116_000, "TypeScript"),
                   ranking.Entry("Tiny", "e/f", 950, "Go")]
        text = ranking.build_text("Frontend Framework", entries, NOW)
        self.assertEqual(text,
                         "🏆 Frontend Framework ★ Ranking (2026-09-29 00:00)\n"
                         "1. React JavaScript ██████████████ 232.1k\n"
                         "2. Lit   TypeScript ███████        116.0k\n"
                         "3. Tiny  Go         █                 950\n")

    def test_rows_fit_line_max_with_real_config(self):
        for key, cat in CONFIG.items():
            entries = ranking.build_entries(cat["repos"], SAMPLE, NOW, 0)
            for line in ranking.build_text(cat["title"], entries, NOW).splitlines()[1:]:
                self.assertLessEqual(ranking.width(line), ranking.LINE_MAX, f"{key}: {line}")

    def test_long_names_shrink_bar_and_truncate_language(self):
        entries = [ranking.Entry("A Very Long Framework", "a/b", 100_000, "Jupyter Notebook"),
                   ranking.Entry("B", "c/d", 50_000, "Go")]
        lines = ranking.build_text("X", entries, NOW).splitlines()[1:]
        self.assertTrue(all(ranking.width(line) <= ranking.LINE_MAX for line in lines))
        self.assertIn("Jupyter No ", lines[0])
        self.assertEqual(len({ranking.width(line) for line in lines}), 1)

    def test_bar_zero_stars(self):
        self.assertEqual(ranking.bar(0, 100, 4), "    ")
        self.assertEqual(ranking.bar(0, 0, 4), "    ")
        self.assertEqual(ranking.bar(1, 100, 4), "█   ")

    def test_language_from_config_overrides_api(self):
        info = {"a/b": {"stargazers_count": 1, "language": "JavaScript", "pushed_at": None}}
        repos = [{"name": "A", "repo": "a/b", "language": "TypeScript"}]
        self.assertEqual(ranking.build_entries(repos, info, NOW, 365)[0].language, "TypeScript")
        self.assertEqual(ranking.build_entries([{"name": "A", "repo": "a/b"}], info, NOW, 365)[0].language,
                         "JavaScript")
        info["a/b"]["language"] = None
        self.assertEqual(ranking.build_entries([{"name": "A", "repo": "a/b"}], info, NOW, 365)[0].language, "-")

    def test_text_aligns_two_digit_ranks(self):
        entries = [ranking.Entry(f"F{i}", f"o/{i}", 1000 * (20 - i)) for i in range(10)]
        lines = ranking.build_text("X", entries, NOW).splitlines()[1:]
        self.assertTrue(lines[0].startswith(" 1. "))
        self.assertTrue(lines[9].startswith("10. "))
        self.assertEqual(len({len(line) for line in lines}), 1)

    def test_missing_pushed_at_is_not_stale(self):
        info = {"a/b": {"stargazers_count": 10, "archived": False, "pushed_at": None}}
        entries = ranking.build_entries([{"name": "A", "repo": "a/b"}], info, NOW, 365)
        self.assertEqual([e.name for e in entries], ["A"])


def http_error(code):
    return urllib.error.HTTPError("u", code, "err", {}, io.BytesIO(b"{}"))


class FetchRepoTest(unittest.TestCase):
    def test_404_returns_none(self):
        with mock.patch.object(ranking, "api", side_effect=http_error(404)):
            self.assertIsNone(ranking.fetch_repo("a/b", None, sleep=lambda s: None))

    def test_retries_transient_errors_then_succeeds(self):
        calls = [http_error(502), urllib.error.URLError("timeout"), {"stargazers_count": 1}]
        with mock.patch.object(ranking, "api", side_effect=calls) as api:
            self.assertEqual(ranking.fetch_repo("a/b", None, sleep=lambda s: None), {"stargazers_count": 1})
        self.assertEqual(api.call_count, 3)

    def test_gives_up_after_retries(self):
        with mock.patch.object(ranking, "api", side_effect=http_error(503)) as api:
            with self.assertRaises(ranking.FetchError):
                ranking.fetch_repo("a/b", None, sleep=lambda s: None)
        self.assertEqual(api.call_count, len(ranking.RETRY_WAITS) + 1)

    def test_client_error_is_not_retried(self):
        with mock.patch.object(ranking, "api", side_effect=http_error(401)) as api:
            with self.assertRaises(ranking.FetchError):
                ranking.fetch_repo("a/b", None, sleep=lambda s: None)
        self.assertEqual(api.call_count, 1)


class MainTest(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.history_path = Path(tmp.name) / "stars.json"
        patcher = mock.patch.object(history, "PATH", self.history_path)
        patcher.start()
        self.addCleanup(patcher.stop)

    def run_main(self, fetch, argv=(), update_error=None):
        env = {"GIST_PAT": "t", "GIST_ID_FRONTEND": "g1", "GIST_ID_BACKEND": "g2"}
        with mock.patch.dict("os.environ", env), \
             mock.patch.object(sys, "argv", ["ranking.py", *argv]), \
             mock.patch.object(ranking, "fetch_repo", side_effect=fetch), \
             mock.patch.object(ranking, "update_gist", side_effect=update_error) as update, \
             redirect_stderr(io.StringIO()), mock.patch("sys.stdout", io.StringIO()):
            self.assertEqual(ranking.main(), 0)
        return [c.args[0] for c in update.call_args_list]

    def test_records_today_stars(self):
        self.run_main(lambda repo, token: SAMPLE.get(repo))
        h = history.load()
        (day,) = h
        self.assertEqual(h[day]["facebook/react"], SAMPLE["facebook/react"]["stargazers_count"])
        self.assertNotIn("emberjs/ember.js", h[day])  # 除外したもの（アーカイブ済み）は記録しない

    def test_records_even_if_gist_update_fails(self):
        with self.assertRaises(SystemExit):
            self.run_main(lambda repo, token: SAMPLE.get(repo), update_error=SystemExit("gist error"))
        self.assertTrue(history.load())

    def test_gist_error_does_not_lose_other_categories(self):
        with self.assertRaises(SystemExit):
            self.run_main(lambda repo, token: SAMPLE.get(repo), update_error=SystemExit("gist error"))
        (day,) = history.load().values()
        self.assertIn("django/django", day)      # backend も記録済み
        self.assertIn("facebook/react", day)

    def test_dry_run_does_not_record(self):
        self.run_main(lambda repo, token: SAMPLE.get(repo), argv=["--dry-run"])
        self.assertFalse(self.history_path.exists())

    def test_fetch_error_skips_only_that_category(self):
        def fetch(repo, token):
            if repo == "django/django":
                raise ranking.FetchError("boom")
            return SAMPLE.get(repo)
        self.assertEqual(self.run_main(fetch), ["g1"])

    def test_empty_ranking_is_not_written(self):
        self.assertEqual(self.run_main(lambda repo, token: None), [])


class UpdateGistTest(unittest.TestCase):
    def test_renames_single_placeholder_file(self):
        with mock.patch.object(ranking, "api", side_effect=[{"files": {"gistfile1.txt": {"content": "x"}}}, {}]) as api, \
             mock.patch("sys.stdout", io.StringIO()):
            ranking.update_gist("g", "t", "rank.txt", "new")
        self.assertEqual(api.call_args.args[3],
                         {"files": {"gistfile1.txt": {"filename": "rank.txt", "content": "new"}}})

    def test_skips_when_unchanged(self):
        with mock.patch.object(ranking, "api", return_value={"files": {"rank.txt": {"content": "same"}}}) as api, \
             mock.patch("sys.stdout", io.StringIO()):
            ranking.update_gist("g", "t", "rank.txt", "same")
        self.assertEqual(api.call_count, 1)


if __name__ == "__main__":
    unittest.main()
