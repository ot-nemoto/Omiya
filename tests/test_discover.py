import io
import sys
import unittest
import urllib.error
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
    return {"stargazers_count": STARS[repo], "full_name": repo, "id": hash(repo) % 10_000}


def http_error(code):
    return urllib.error.HTTPError("u", code, "err", {}, io.BytesIO(b"{}"))


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
        self.assertFalse(discover.is_candidate(item("x/y", 1, fork=True), known, NOW, 365))
        self.assertFalse(discover.is_candidate(item("renamed/fw", 1, id=42), {42}, NOW, 365))
        vpn = item("x/fanqiang", 1, desc="翻墙", topics=["proxy", "Shadowsocks", "ssr"])
        self.assertFalse(discover.is_candidate(vpn, known, NOW, 365))
        fw = item("x/leptos", 1, desc="Build fast web applications with Rust.", topics=["rust", "ssr", "web"])
        self.assertTrue(discover.is_candidate(fw, known, NOW, 365))


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

    def test_renamed_listed_repo_is_known(self):
        def renamed_fetch(repo, token):
            d = fetch(repo, token)
            if repo == "lit/lit":
                d["full_name"] = "lit/lit-new"
            return d

        with mock.patch.object(discover, "search", return_value=[item("lit/lit-new", 30_000)]):
            found = discover.find_candidates(CONFIG, None, NOW, 365, fetch=renamed_fetch)
        self.assertEqual(found, {})

    def test_threshold_ignores_archived_listed_repos(self):
        def fetch_archived(repo, token):
            d = fetch(repo, token)
            if repo == "lit/lit":
                d["archived"] = True
            return d

        calls = []
        with mock.patch.object(discover, "search", side_effect=lambda t, m, tok: calls.append(m) or []):
            discover.find_candidates(CONFIG, None, NOW, 365, fetch=fetch_archived)
        self.assertEqual(calls[0], 250_000)

    def test_fetch_error_propagates(self):
        def failing(repo, token):
            raise ranking.FetchError("x")
        with self.assertRaises(ranking.FetchError):
            discover.find_candidates(CONFIG, None, NOW, 365, fetch=failing)


class SearchTest(unittest.TestCase):
    def test_retries_then_returns_items(self):
        with mock.patch.object(ranking, "api", side_effect=[http_error(502), {"items": [1]}]):
            self.assertEqual(discover.search("t", 1, None, sleep=lambda s: None), [1])

    def test_gives_up_as_fetch_error(self):
        with mock.patch.object(ranking, "api", side_effect=urllib.error.URLError("down")):
            with self.assertRaises(ranking.FetchError):
                discover.search("t", 1, None, sleep=lambda s: None)

    def test_422_is_fatal(self):
        with mock.patch.object(ranking, "api", side_effect=http_error(422)):
            with self.assertRaises(SystemExit):
                discover.search("t", 1, None, sleep=lambda s: None)

    def test_incomplete_results_warns(self):
        with mock.patch.object(ranking, "api", return_value={"items": [], "incomplete_results": True}), \
             mock.patch.object(ranking, "warn") as warn:
            discover.search("t", 1, None)
        warn.assert_called_once()


class IssueTest(unittest.TestCase):
    def test_title_roundtrip_and_body(self):
        it = item("New/FW", 40_000, language="TypeScript", topics=["frontend-framework"], id=7,
                  desc="Fast | by @alice, see #12\nnew line")
        title = discover.issue_title(it)
        self.assertEqual(discover.TITLE_RE.match(title).group(1), "New/FW")
        body = discover.issue_body(it, {"frontend": 21_000})
        self.assertIn('{"name": "FW", "repo": "New/FW"},', body)
        self.assertIn("frontend（最下位 ★21.0k）", body)
        self.assertIn("40,000", body)
        self.assertIn("Fast / by @\u200balice, see #\u200b12 new line", body)
        m = discover.MARKER_RE.search(body)
        self.assertEqual((m.group(1), m.group(2)), ("New/FW", "7"))

    def test_existing_issue_repos_paginates(self):
        page1 = [{"title": f"[候補] a/r{i}"} for i in range(100)]
        page2 = [{"title": "[候補] B/X"}, {"title": "unrelated", "body": None},
                 {"title": "edited title", "body": "...\n<!-- candidate: c/Old id:99 -->"}]
        with mock.patch.object(ranking, "api", side_effect=[page1, page2]):
            seen = discover.existing_issue_repos("o/r", "t")
        self.assertIn("b/x", seen)
        self.assertIn("c/old", seen)
        self.assertIn(99, seen)

    def test_ensure_label_creates_when_missing(self):
        with mock.patch.object(ranking, "api", side_effect=[http_error(404), {}]) as api:
            discover.ensure_label("o/r", "t")
        self.assertEqual(api.call_args.args[0], "POST")


class MainTest(unittest.TestCase):
    def run_main(self, found, seen, argv=(), api_error=None):
        posts = []

        def api(method, url, token, body=None):
            if method == "POST":
                if api_error:
                    raise api_error
                posts.append((url, body))
            return {}  # ラベルは既にある

        env = {"GITHUB_TOKEN": "t", "GITHUB_REPOSITORY": "o/r"}
        with mock.patch.dict("os.environ", env), mock.patch.object(sys, "argv", ["discover.py", *argv]), \
             mock.patch.object(discover, "find_candidates", return_value=found), \
             mock.patch.object(discover, "existing_issue_repos", return_value=seen), \
             mock.patch.object(ranking, "api", side_effect=api), mock.patch.object(ranking, "warn"), \
             mock.patch("sys.stdout"):
            self.assertEqual(discover.main(sleep=lambda s: None), 0)
        return posts

    def test_caps_issues_per_run_by_stars(self):
        found = {f"o/r{i}": {"item": item(f"o/r{i}", 1000 * i, id=i), "categories": {"frontend": 1}}
                 for i in range(1, 9)}
        posts = self.run_main(found, set())
        self.assertEqual(len(posts), discover.MAX_ISSUES_PER_RUN)
        self.assertEqual(posts[0][1]["title"], "[候補] o/r8")

    def test_skips_seen_by_id(self):
        found = {"new/name": {"item": item("new/name", 1, id=5), "categories": {"frontend": 1}}}
        self.assertEqual(self.run_main(found, {5}), [])

    def test_dry_run_and_empty_create_nothing(self):
        found = {"a/b": {"item": item("a/b", 1, id=1), "categories": {"frontend": 1}}}
        self.assertEqual(self.run_main(found, set(), argv=["--dry-run"]), [])
        self.assertEqual(self.run_main({}, set()), [])

    def test_network_error_during_create_is_skipped(self):
        found = {"a/b": {"item": item("a/b", 1, id=1), "categories": {"frontend": 1}}}
        self.run_main(found, set(), api_error=urllib.error.URLError("down"))

    def test_http_error_during_create_fails(self):
        found = {"a/b": {"item": item("a/b", 1, id=1), "categories": {"frontend": 1}}}
        with self.assertRaises(SystemExit):
            self.run_main(found, set(), api_error=http_error(410))

    def test_creates_issue_only_for_unseen(self):
        found = {"a/new": {"item": item("a/New", 50_000, id=1), "categories": {"frontend": 1}},
                 "b/old": {"item": item("b/old", 60_000, id=2), "categories": {"backend": 1}}}
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
