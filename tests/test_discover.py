import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import discover  # noqa: E402
import ranking  # noqa: E402

NOW = datetime(2026, 9, 29, tzinfo=timezone.utc)
CONFIG = {
    "frontend": {"repos": [{"name": "React", "repo": "facebook/react"},
                           {"name": "Lit", "repo": "lit/lit"}],
                 "discover_topics": ["frontend-framework"]},
    "backend": {"repos": [{"name": "Django", "repo": "django/django"}],
                "discover_topics": ["web-framework"]},
}
STARS = {"facebook/react": 250_000, "lit/lit": 21_000, "django/django": 90_000}


def item(name, stars, desc="A fast framework", pushed="2026-09-01T00:00:00Z", **kw):
    return {"full_name": name, "name": name.split("/")[1], "stargazers_count": stars,
            "description": desc, "pushed_at": pushed, "archived": False, "fork": False, **kw}


def fetch(repo, token):
    return {"stargazers_count": STARS[repo]}


class IsCandidateTest(unittest.TestCase):
    def test_filters(self):
        known = {"facebook/react"}
        self.assertTrue(discover.is_candidate(item("new/fw", 30_000), known, NOW, 365))
        self.assertFalse(discover.is_candidate(item("Facebook/React", 1), known, NOW, 365))
        self.assertFalse(discover.is_candidate(item("x/awesome-react", 1), known, NOW, 365))
        self.assertFalse(discover.is_candidate(item("x/y", 1, desc="Next.js starter template"), known, NOW, 365))
        self.assertFalse(discover.is_candidate(item("x/y", 1, archived=True), known, NOW, 365))
        self.assertFalse(discover.is_candidate(item("x/y", 1, pushed="2024-01-01T00:00:00Z"), known, NOW, 365))
        self.assertTrue(discover.is_candidate(item("x/y", 1, desc=None, pushed=None), known, NOW, 365))


class FindCandidatesTest(unittest.TestCase):
    def test_threshold_is_lowest_in_category_and_dedupes(self):
        calls = []

        def search(topic, min_stars, token):
            calls.append((topic, min_stars))
            return [item("new/fw", 40_000), item("lit/lit", 21_000), item("x/awesome-fw", 99_000)]

        with mock.patch.object(discover, "search", side_effect=search):
            found = discover.find_candidates(CONFIG, None, NOW, 365, fetch=fetch)
        self.assertEqual(calls, [("frontend-framework", 21_000), ("web-framework", 90_000)])
        self.assertEqual(list(found), ["new/fw"])
        self.assertEqual(found["new/fw"]["categories"], {"frontend": 21_000, "backend": 90_000})

    def test_search_error_raises_fetch_error(self):
        err = ranking.urllib.error.URLError("down")
        with mock.patch.object(discover, "search", side_effect=err):
            with self.assertRaises(ranking.FetchError):
                discover.find_candidates(CONFIG, None, NOW, 365, fetch=fetch)


class IssueTest(unittest.TestCase):
    def test_title_roundtrip_and_body(self):
        it = item("New/FW", 40_000, language="TypeScript", topics=["frontend-framework"])
        title = discover.issue_title(it)
        self.assertEqual(discover.TITLE_RE.match(title).group(1), "New/FW")
        body = discover.issue_body(it, {"frontend": 21_000})
        self.assertIn('{"name": "FW", "repo": "New/FW"},', body)
        self.assertIn("frontend（最下位 ★21.0k）", body)
        self.assertIn("40,000", body)

    def test_existing_issue_repos_paginates(self):
        page1 = [{"title": f"[候補] a/r{i}"} for i in range(100)]
        page2 = [{"title": "[候補] B/X"}, {"title": "unrelated"}]
        with mock.patch.object(ranking, "api", side_effect=[page1, page2]):
            seen = discover.existing_issue_repos("o/r", "t")
        self.assertIn("b/x", seen)
        self.assertEqual(len(seen), 101)


class MainTest(unittest.TestCase):
    def run_main(self, found, seen):
        posts = []

        def api(method, url, token, body=None):
            if method == "POST":
                posts.append((url, body))
                return {}
            return {}  # ラベルは既にある

        env = {"GITHUB_TOKEN": "t", "GITHUB_REPOSITORY": "o/r"}
        with mock.patch.dict("os.environ", env), mock.patch.object(sys, "argv", ["discover.py"]), \
             mock.patch.object(discover, "find_candidates", return_value=found), \
             mock.patch.object(discover, "existing_issue_repos", return_value=seen), \
             mock.patch.object(ranking, "api", side_effect=api), mock.patch("sys.stdout"):
            self.assertEqual(discover.main(), 0)
        return posts

    def test_creates_issue_only_for_unseen(self):
        found = {"a/new": {"item": item("a/New", 50_000), "categories": {"frontend": 1}},
                 "b/old": {"item": item("b/old", 60_000), "categories": {"backend": 1}}}
        posts = self.run_main(found, {"b/old"})
        self.assertEqual(len(posts), 1)
        url, body = posts[0]
        self.assertTrue(url.endswith("/repos/o/r/issues"))
        self.assertEqual(body["title"], "[候補] a/New")
        self.assertEqual(body["labels"], [discover.LABEL])

    def test_search_failure_is_skipped(self):
        with mock.patch.object(discover, "find_candidates", side_effect=ranking.FetchError("x")), \
             mock.patch.object(ranking, "warn") as warn, mock.patch.object(sys, "argv", ["discover.py"]):
            self.assertEqual(discover.main(), 0)
        warn.assert_called_once()


if __name__ == "__main__":
    unittest.main()
