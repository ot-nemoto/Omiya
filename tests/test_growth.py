import io
import json
import sys
import unittest
import urllib.error
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import growth  # noqa: E402
import ranking  # noqa: E402

NOW = datetime(2026, 9, 30, tzinfo=timezone.utc)
SINCE = NOW - timedelta(days=7)
CONFIG = json.loads(ranking.CONFIG.read_text(encoding="utf-8"))


def setUpModule():
    patcher = mock.patch.object(ranking, "warn")
    patcher.start()
    unittest.addModuleCleanup(patcher.stop)


def iso(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def page(times, has_next, cursor="c", stars=1000):
    return {"data": {"repository": {
        "nameWithOwner": "o/r", "stargazerCount": stars, "isArchived": False,
        "pushedAt": iso(NOW), "primaryLanguage": {"name": "Rust"},
        "stargazers": {"pageInfo": {"hasNextPage": has_next, "endCursor": cursor},
                       "edges": [{"starredAt": iso(t)} for t in times]},
    }}}


def http_error(code):
    return urllib.error.HTTPError("u", code, "err", {}, io.BytesIO(b"{}"))


class FetchGrowthTest(unittest.TestCase):
    def test_counts_until_older_than_since_across_pages(self):
        recent = [NOW - timedelta(hours=h) for h in range(100)]            # 100 件すべて期間内
        mixed = [NOW - timedelta(days=d) for d in (1, 2, 8, 9)]            # 2 件だけ期間内
        with mock.patch.object(ranking, "api", side_effect=[page(recent, True), page(mixed, True)]) as api:
            d = growth.fetch_growth("o/r", "t", SINCE, sleep=lambda s: None)
        self.assertEqual(d["added"], 102)
        self.assertEqual(api.call_count, 2)  # 期間外に達したら次のページは取らない
        self.assertEqual(api.call_args_list[1].args[3]["variables"]["after"], "c")
        self.assertEqual((d["stargazers_count"], d["language"]), (1000, "Rust"))

    def test_last_page_without_old_star(self):
        with mock.patch.object(ranking, "api", return_value=page([NOW], False)):
            self.assertEqual(growth.fetch_growth("o/r", "t", SINCE)["added"], 1)

    def test_not_found_returns_none(self):
        res = {"data": {"repository": None}, "errors": [{"type": "NOT_FOUND", "message": "x"}]}
        with mock.patch.object(ranking, "api", return_value=res):
            self.assertIsNone(growth.fetch_growth("o/r", "t", SINCE))

    def test_other_graphql_error_is_retried_then_fetch_error(self):
        res = {"errors": [{"type": "RATE_LIMITED", "message": "slow down"}]}
        with mock.patch.object(ranking, "api", return_value=res) as api:
            with self.assertRaises(ranking.FetchError):
                growth.fetch_growth("o/r", "t", SINCE, sleep=lambda s: None)
        self.assertEqual(api.call_count, len(ranking.RETRY_WAITS) + 1)

    def test_forbidden_is_not_retried(self):
        res = {"data": {"repository": None},
               "errors": [{"type": "FORBIDDEN", "message": "Resource not accessible by integration"}]}
        with mock.patch.object(ranking, "api", return_value=res) as api:
            with self.assertRaises(ranking.FetchError):
                growth.fetch_growth("o/r", "t", SINCE, sleep=lambda s: None)
        self.assertEqual(api.call_count, 1)

    def test_graphql_token_preferred(self):
        env = {"GRAPHQL_TOKEN": "pat", "GITHUB_TOKEN": "app"}
        seen = []
        with mock.patch.dict("os.environ", env), mock.patch.object(sys, "argv", ["growth.py", "--dry-run"]), \
             mock.patch.object(growth, "fetch_growth", side_effect=lambda r, tok, since: seen.append(tok)), \
             mock.patch("sys.stdout", io.StringIO()):
            growth.main()
        self.assertEqual(set(seen), {"pat"})

    def test_falls_back_to_github_token(self):
        env = {"GRAPHQL_TOKEN": "", "GITHUB_TOKEN": "app"}
        seen = []
        with mock.patch.dict("os.environ", env), mock.patch.object(sys, "argv", ["growth.py", "--dry-run"]), \
             mock.patch.object(growth, "fetch_growth", side_effect=lambda r, tok, since: seen.append(tok)), \
             mock.patch("sys.stdout", io.StringIO()):
            growth.main()
        self.assertEqual(set(seen), {"app"})

    def test_transient_graphql_error_recovers(self):
        bad = {"data": None, "errors": [{"message": "Something went wrong while executing your query."}]}
        with mock.patch.object(ranking, "api", side_effect=[bad, page([NOW], False)]):
            self.assertEqual(growth.fetch_growth("o/r", "t", SINCE, sleep=lambda s: None)["added"], 1)

    def test_retries_transient_http_errors(self):
        with mock.patch.object(ranking, "api", side_effect=[http_error(502), page([NOW], False)]):
            self.assertEqual(growth.fetch_growth("o/r", "t", SINCE, sleep=lambda s: None)["added"], 1)

    def test_page_cap(self):
        full = [NOW] * growth.PAGE_SIZE
        with mock.patch.object(ranking, "api", return_value=page(full, True)), \
             mock.patch.object(growth, "MAX_PAGES", 3), mock.patch.object(ranking, "warn") as warn:
            self.assertEqual(growth.fetch_growth("o/r", "t", SINCE)["added"], 3 * growth.PAGE_SIZE)
        warn.assert_called_once()


class BuildTest(unittest.TestCase):
    def info(self, stars, added, **kw):
        return {"stargazers_count": stars, "added": added, "archived": False,
                "pushed_at": iso(NOW), "language": "Go", **kw}

    def test_sorted_by_added_and_excludes_like_ranking(self):
        repos = [{"name": "A", "repo": "o/a"}, {"name": "B", "repo": "o/b"},
                 {"name": "C", "repo": "o/c"}, {"name": "D", "repo": "o/d"}]
        info = {"o/a": self.info(100_000, 300), "o/b": self.info(10_000, 900),
                "o/c": self.info(5_000, 50, archived=True), "o/d": None}
        gs = growth.build_growths(repos, info, NOW, 365)
        self.assertEqual([g.name for g in gs], ["B", "A"])
        self.assertAlmostEqual(gs[0].rate, 900 / 9_100 * 100)

    def test_rate_with_no_base(self):
        self.assertIsNone(growth.Growth("x", "o/x", 5, 5).rate)
        self.assertEqual(growth.fmt_rate(None), "new")

    def test_all_zero_growth(self):
        gs = [growth.Growth("A", "a", 0, 100, "Go"), growth.Growth("B", "b", 0, 50, "Go")]
        lines = growth.build_text("X", gs, 7, NOW).splitlines()[1:]
        self.assertNotIn("█", "".join(lines))
        self.assertEqual(len({ranking.width(l) for l in lines}), 1)

    def test_text_format(self):
        gs = [growth.Growth("React", "a", 1_234, 250_000, "JavaScript"),
              growth.Growth("Lit", "b", 56, 21_800, "TypeScript"),
              growth.Growth("Zero", "c", 0, 100, "Go")]
        text = growth.build_text("Frontend Framework", gs, 7, NOW)
        lines = text.splitlines()
        self.assertEqual(lines[0], "🚀 Frontend Framework ★ Growth 7d (2026-09-30 00:00)")
        self.assertTrue(lines[1].startswith("1. React JavaScript █"))
        self.assertTrue(lines[1].endswith("+1.2k +0.5%"))
        self.assertTrue(lines[2].endswith("  +56 +0.3%"))
        self.assertTrue(lines[3].endswith("   +0 +0.0%"))
        self.assertEqual(len({ranking.width(l) for l in lines[1:]}), 1)

    def test_rows_fit_line_max_with_real_config(self):
        for cat in CONFIG.values():
            gs = [growth.Growth(r["name"], r["repo"], 12_345, 123_456, "JavaScript") for r in cat["repos"]]
            for line in growth.build_text(cat["title"], gs, 7, NOW).splitlines()[1:]:
                self.assertLessEqual(ranking.width(line), ranking.LINE_MAX, line)

    def test_formatters(self):
        self.assertEqual(growth.fmt_added(999), "+999")
        self.assertEqual(growth.fmt_added(1_050), "+1.1k")
        self.assertEqual(growth.fmt_rate(123.4), "+123%")
        self.assertEqual(growth.fmt_rate(99.97), "+100%")
        self.assertEqual(growth.fmt_rate(12.34), "+12.3%")


class MainTest(unittest.TestCase):
    def test_fetch_error_skips_category_only(self):
        def fetch(repo, token, since):
            if repo == "django/django":
                raise ranking.FetchError("boom")
            return {"stargazers_count": 1000, "added": 10, "archived": False,
                    "pushed_at": iso(datetime.now(timezone.utc)), "language": "Go"}

        env = {"GITHUB_TOKEN": "t", "GIST_PAT": "p",
               "GIST_ID_FRONTEND_GROWTH": "g1", "GIST_ID_BACKEND_GROWTH": "g2"}
        with mock.patch.dict("os.environ", env), mock.patch.object(sys, "argv", ["growth.py"]), \
             mock.patch.object(growth, "fetch_growth", side_effect=fetch), \
             mock.patch.object(ranking, "update_gist") as update, mock.patch("sys.stdout", io.StringIO()):
            self.assertEqual(growth.main(), 0)
        self.assertEqual([(c.args[0], c.args[2]) for c in update.call_args_list],
                         [("g1", "frontend-framework-growth.txt")])

    def test_rejects_non_positive_days(self):
        env = {"GITHUB_TOKEN": "t", "GROWTH_DAYS": "0"}
        with mock.patch.dict("os.environ", env), mock.patch.object(sys, "argv", ["growth.py"]):
            with self.assertRaises(SystemExit):
                growth.main()

    def test_requires_token(self):
        with mock.patch.dict("os.environ", {}, clear=True), mock.patch.object(sys, "argv", ["growth.py"]):
            with self.assertRaises(SystemExit):
                growth.main()


if __name__ == "__main__":
    unittest.main()
