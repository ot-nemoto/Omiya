import io
import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import growth  # noqa: E402
import history  # noqa: E402
import ranking  # noqa: E402

NOW = datetime(2026, 9, 30, tzinfo=timezone.utc)
CONFIG = json.loads(ranking.CONFIG.read_text(encoding="utf-8"))


def setUpModule():
    patcher = mock.patch.object(ranking, "warn")
    patcher.start()
    unittest.addModuleCleanup(patcher.stop)


def info(stars, **kw):
    return {"stargazers_count": stars, "archived": False,
            "pushed_at": "2026-09-29T00:00:00Z", "language": "Go", **kw}


class BuildTest(unittest.TestCase):
    def test_diff_sorted_and_excludes_like_ranking(self):
        repos = [{"name": n, "repo": f"o/{n.lower()}"} for n in ("A", "B", "C", "D", "E")]
        infos = {"o/a": info(100_300), "o/b": info(10_900), "o/c": info(5_050, archived=True),
                 "o/d": None, "o/e": info(700)}
        base = {"o/a": 100_000, "o/b": 10_000, "o/c": 5_000, "o/d": 1}  # E は起点日の記録なし
        with mock.patch("sys.stderr", io.StringIO()):
            gs = growth.build_growths(repos, infos, base, NOW, 365)
        self.assertEqual([(g.name, g.added) for g in gs], [("B", 900), ("A", 300)])
        self.assertAlmostEqual(gs[0].rate, 9.0)

    def test_negative_growth(self):
        g = growth.Growth("x", "o/x", -12, 988)
        self.assertEqual(growth.fmt_added(g.added), "-12")
        self.assertEqual(growth.fmt_rate(g.rate), "-1.2%")

    def test_rate_with_no_base(self):
        self.assertIsNone(growth.Growth("x", "o/x", 5, 5).rate)
        self.assertEqual(growth.fmt_rate(None), "new")

    def test_formatters(self):
        self.assertEqual(growth.fmt_added(999), "+999")
        self.assertEqual(growth.fmt_added(1_050), "+1.1k")
        self.assertEqual(growth.fmt_added(-1_050), "-1.1k")
        self.assertEqual(growth.fmt_added(0), "+0")
        self.assertEqual(growth.fmt_rate(123.4), "+123%")
        self.assertEqual(growth.fmt_rate(99.97), "+100%")
        self.assertEqual(growth.fmt_rate(12.34), "+12.3%")

    def test_text_format(self):
        gs = [growth.Growth("React", "a", 1_234, 250_000, "JavaScript"),
              growth.Growth("Lit", "b", 56, 21_800, "TypeScript"),
              growth.Growth("Zero", "c", -3, 100, "Go")]
        lines = growth.build_text("Frontend Framework", gs, 7, NOW).splitlines()
        self.assertEqual(lines[0], "🚀 Frontend Framework ★ Growth 7d (2026-09-30 00:00)")
        self.assertTrue(lines[1].startswith("1. React JavaScript █"))
        self.assertTrue(lines[1].endswith("+1.2k +0.5%"))
        self.assertTrue(lines[2].endswith("  +56 +0.3%"))
        self.assertTrue(lines[3].endswith("   -3 -2.9%"))
        self.assertNotIn("█", lines[3])
        self.assertEqual(len({ranking.width(line) for line in lines[1:]}), 1)

    def test_rows_fit_line_max_with_real_config(self):
        for cat in CONFIG.values():
            gs = [growth.Growth(r["name"], r["repo"], -12_345, 123_456, "JavaScript") for r in cat["repos"]]
            for line in growth.build_text(cat["title"], gs, 7, NOW).splitlines()[1:]:
                self.assertLessEqual(ranking.width(line), ranking.LINE_MAX, line)


class MainTest(unittest.TestCase):
    def run_main(self, hist, env_extra=None, fetch=None, argv=()):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "stars.json"
            history.save(hist, path)
            env = {"GITHUB_TOKEN": "t", "GIST_PAT": "p",
                   "GIST_ID_FRONTEND_GROWTH": "g1", "GIST_ID_BACKEND_GROWTH": "g2", **(env_extra or {})}
            fetch = fetch or (lambda repo, token: info(1_000))
            with mock.patch.object(history, "PATH", path), mock.patch.dict("os.environ", env), \
                 mock.patch.object(sys, "argv", ["growth.py", *argv]), \
                 mock.patch.object(ranking, "fetch_repo", side_effect=fetch), \
                 mock.patch.object(ranking, "update_gist") as update, \
                 mock.patch("sys.stdout", io.StringIO()) as out, mock.patch("sys.stderr", io.StringIO()):
                self.assertEqual(growth.main(), 0)
            return update, out.getvalue()

    def all_repos(self, stars):
        return {r["repo"]: stars for c in CONFIG.values() for r in c["repos"]}

    def test_uses_record_days_ago_and_writes_both(self):
        today = datetime.now(timezone.utc).astimezone(ranking.JST).date()
        hist = {(today.fromordinal(today.toordinal() - 7)).isoformat(): self.all_repos(900),
                (today.fromordinal(today.toordinal() - 3)).isoformat(): self.all_repos(990)}
        update, out = self.run_main(hist)
        self.assertEqual([(c.args[0], c.args[2]) for c in update.call_args_list],
                         [("g1", "frontend-framework-growth.txt"), ("g2", "backend-framework-growth.txt")])
        self.assertIn("Growth 7d", out)
        self.assertIn("+100", out)

    def test_partial_period_shows_actual_days(self):
        today = datetime.now(timezone.utc).astimezone(ranking.JST).date()
        hist = {(today.fromordinal(today.toordinal() - 2)).isoformat(): self.all_repos(990)}
        _, out = self.run_main(hist, argv=["--dry-run"])
        self.assertIn("Growth 2d", out)
        self.assertIn("+10", out)

    def test_no_past_record_skips(self):
        today = datetime.now(timezone.utc).astimezone(ranking.JST).date()
        update, _ = self.run_main({today.isoformat(): self.all_repos(1)})
        update.assert_not_called()

    def test_fetch_error_skips_category_only(self):
        today = datetime.now(timezone.utc).astimezone(ranking.JST).date()
        hist = {(today.fromordinal(today.toordinal() - 7)).isoformat(): self.all_repos(900)}

        def fetch(repo, token):
            if repo == "django/django":
                raise ranking.FetchError("boom")
            return info(1_000)

        update, _ = self.run_main(hist, fetch=fetch)
        self.assertEqual([c.args[0] for c in update.call_args_list], ["g1"])

    def test_rejects_bad_days(self):
        for days in ("0", str(history.KEEP_DAYS)):
            with mock.patch.dict("os.environ", {"GROWTH_DAYS": days}), \
                 mock.patch.object(sys, "argv", ["growth.py"]):
                with self.assertRaises(SystemExit):
                    growth.main()


if __name__ == "__main__":
    unittest.main()
