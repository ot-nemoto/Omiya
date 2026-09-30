import io
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import history  # noqa: E402
import ranking  # noqa: E402
import rising  # noqa: E402

NOW = datetime(2026, 9, 30, tzinfo=timezone.utc)
CONFIG = {
    "frontend": {"repos": [{"name": "React", "repo": "facebook/react"}],
                 "discover_topics": ["frontend-framework", "ssr"]},
    "backend": {"repos": [{"name": "Django", "repo": "django/django"}],
                "discover_topics": ["web-framework", "ssr"]},
}


def setUpModule():
    patcher = mock.patch.object(ranking, "warn")
    patcher.start()
    unittest.addModuleCleanup(patcher.stop)


def item(name, stars=2_000, **kw):
    return {"full_name": name, "stargazers_count": stars, "description": "A new framework",
            "language": "Rust", "created_at": "2026-01-01T00:00:00Z", "topics": ["web"],
            "archived": False, "fork": False, **kw}


class FilterTest(unittest.TestCase):
    def test_is_rising(self):
        known = {"facebook/react"}
        self.assertTrue(rising.is_rising(item("new/fw"), known))
        self.assertFalse(rising.is_rising(item("Facebook/React"), known))
        self.assertFalse(rising.is_rising(item("x/y", archived=True), known))
        self.assertFalse(rising.is_rising(item("x/y", fork=True), known))
        self.assertFalse(rising.is_rising(item("x/awesome-y"), known))
        self.assertFalse(rising.is_rising(item("x/y", topics=["ssr", "v2ray"]), known))

    def test_topics_are_deduplicated_in_order(self):
        self.assertEqual(rising.topics(CONFIG), ["frontend-framework", "ssr", "web-framework"])


class CollectTest(unittest.TestCase):
    def test_queries_paginates_and_merges(self):
        calls = []

        def search(topic, min_stars, token, sleep, qualifiers="", page=1):
            calls.append((topic, min_stars, qualifiers, page))
            if topic == "frontend-framework" and page == 1:
                return [item(f"a/r{i}") for i in range(100)]   # 満杯なので 2 ページ目も取る
            if topic == "frontend-framework" and page == 2:
                return [item("b/new"), item("facebook/react")]
            if topic == "ssr":
                return [item("b/new"), item("x/vpn", topics=["clash"])]
            return []

        sleeps = []
        with mock.patch.object(rising.discover, "search", side_effect=search):
            found = rising.collect(CONFIG, None, NOW, sleep=sleeps.append)
        self.assertEqual([(c[0], c[3]) for c in calls],
                         [("frontend-framework", 1), ("frontend-framework", 2), ("ssr", 1), ("web-framework", 1)])
        self.assertEqual(calls[0][1], rising.MIN_STARS)
        self.assertEqual(calls[0][2], "created:>=2024-09-30 pushed:>=2026-07-02")
        self.assertEqual(len(sleeps), len(calls) - 1)  # リクエストの間隔を空ける
        self.assertEqual(len(found), 101)
        self.assertNotIn("facebook/react", found)
        self.assertNotIn("x/vpn", found)
        self.assertEqual(found["b/new"]["found_via"], {"frontend-framework", "ssr"})

    def test_search_failure_skips_only_that_topic(self):
        def search(topic, *a, **kw):
            if topic == "ssr":
                raise ranking.FetchError("down")
            return [item(f"o/{topic}")]

        with mock.patch.object(rising.discover, "search", side_effect=search):
            found = rising.collect(CONFIG, None, NOW, sleep=lambda s: None)
        self.assertEqual(set(found), {"o/frontend-framework", "o/web-framework"})


class RepoMetaTest(unittest.TestCase):
    def test_update_repos_keeps_first_seen_and_merges_topics(self):
        repos = {"a/b": {"first_seen": "2026-09-01", "found_via": ["ssr"]}}
        found = {"a/b": {"item": item("a/b", description="x"), "found_via": {"web-framework"}},
                 "c/d": {"item": item("c/d", language=None), "found_via": {"ssr"}}}
        rising.update_repos(repos, found, "2026-09-30")
        self.assertEqual(repos["a/b"]["first_seen"], "2026-09-01")
        self.assertEqual(repos["a/b"]["last_seen"], "2026-09-30")
        self.assertEqual(repos["a/b"]["found_via"], ["ssr", "web-framework"])
        self.assertEqual(repos["c/d"]["first_seen"], "2026-09-30")
        self.assertEqual(repos["c/d"]["created_at"], "2026-01-01")

    def test_save_load_roundtrip_and_broken_file(self):
        with tempfile.TemporaryDirectory() as d:
            path = Path(d) / "rising-repos.json"
            self.assertEqual(rising.load_repos(path), {})
            repos = {"z/z": {"language": "Go"}, "a/a": {"description": "日本語"}}
            rising.save_repos(repos, path)
            self.assertEqual(rising.load_repos(path), repos)
            self.assertTrue(path.read_text().splitlines()[1].startswith('  "a/a"'))
            path.write_text("<<<<<<< HEAD")
            with self.assertRaises(SystemExit):
                rising.load_repos(path)


class MainTest(unittest.TestCase):
    def run_main(self, found, argv=()):
        with tempfile.TemporaryDirectory() as d:
            stars, repos = Path(d) / "rising.json", Path(d) / "rising-repos.json"
            with mock.patch.object(rising, "STARS_PATH", stars), mock.patch.object(rising, "REPOS_PATH", repos), \
                 mock.patch.object(rising, "collect", return_value=found), \
                 mock.patch.object(sys, "argv", ["rising.py", *argv]), mock.patch("sys.stdout", io.StringIO()):
                self.assertEqual(rising.main(sleep=lambda s: None), 0)
            return (history.load(stars) if stars.exists() else None,
                    rising.load_repos(repos) if repos.exists() else None)

    def test_records_stars_and_meta(self):
        found = {"a/b": {"item": item("a/b", stars=1_500), "found_via": {"ssr"}}}
        stars, repos = self.run_main(found)
        (day,) = stars
        self.assertEqual(stars[day], {"a/b": 1_500})
        self.assertEqual(repos["a/b"]["first_seen"], day)

    def test_dry_run_and_empty_write_nothing(self):
        found = {"a/b": {"item": item("a/b"), "found_via": {"ssr"}}}
        self.assertEqual(self.run_main(found, argv=["--dry-run"]), (None, None))
        self.assertEqual(self.run_main({}), (None, None))


if __name__ == "__main__":
    unittest.main()
