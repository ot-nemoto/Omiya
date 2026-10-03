import io
import random
import re
import sys
import tempfile
import unittest
import urllib.error
from datetime import date, datetime, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import collect  # noqa: E402
import ranking  # noqa: E402

try:
    import pyarrow  # noqa: F401
    HAS_PYARROW = True
except ImportError:  # 毎日のランキングの workflow では入れていない
    HAS_PYARROW = False

DAY = date(2026, 10, 4)


def item(rid, stars, created="2024-01-01T00:00:00Z", **kw):
    return {"id": rid, "full_name": f"o/r{rid}", "stargazers_count": stars, "created_at": created,
            "forks_count": 3, "open_issues_count": 2, "pushed_at": "2026-10-01T12:00:00Z", "archived": False,
            "owner": {"login": "o", "type": "Organization"}, "description": f"repo {rid}",
            "topics": ["a", "b"], "language": "Go", "license": {"spdx_id": "MIT"}, "homepage": "",
            "fork": False, "is_template": False, **kw}


class FakeSearch:
    """検索 API の代わり。stars / created の条件で絞り、★の多い順にページを返す（1,000 件の上限も再現）。"""

    def __init__(self, repos):
        self.repos = repos
        self.queries = []

    @property
    def requests(self):
        return len(self.queries)

    def __call__(self, query, page=1):
        self.queries.append((query, page))
        hits = [r for r in self.repos if self._match(r, query)]
        hits.sort(key=lambda r: (-r["stargazers_count"], r["id"]))
        start = (page - 1) * collect.PER_PAGE
        shown = hits[:collect.SEARCH_LIMIT][start:start + collect.PER_PAGE]
        return {"total_count": len(hits), "incomplete_results": False, "items": shown}

    @staticmethod
    def _match(r, query):
        s = r["stargazers_count"]
        if m := re.search(r"stars:(\d+)\.\.(\d+)", query):
            if not int(m[1]) <= s <= int(m[2]):
                return False
        elif m := re.search(r"stars:>=(\d+)", query):
            if s < int(m[1]):
                return False
        if m := re.search(r"created:(\S+)\.\.(\S+)", query):
            c = r["created_at"][:10]
            if not m[1] <= c <= m[2]:
                return False
        return True


class SplitTest(unittest.TestCase):
    def test_split_points_cover_range_without_gaps(self):
        for lo, hi, parts in [(500, 1000, 3), (500, 500_000, 10), (5, 7, 10), (500, 501, 5)]:
            ranges = collect.split_points(lo, hi, parts)
            self.assertEqual(ranges[0][0], lo)
            self.assertEqual(ranges[-1][1], hi)
            for (a, b), (c, _) in zip(ranges, ranges[1:]):
                self.assertEqual(b + 1, c)
            self.assertTrue(all(a <= b for a, b in ranges))

    def test_collects_everything_beyond_search_limit(self):
        rng = random.Random(1)
        # ★数は少ない側に偏る（べき分布）。合計 5,000 件で、1 つの検索の上限 1,000 を大きく超える
        repos = [item(i, int(500 / (1 - rng.random()) ** 0.9)) for i in range(5000)]
        search = FakeSearch(repos)
        found, expected = collect.collect(search, date(2025, 10, 4))
        self.assertEqual(expected, 5000)
        self.assertEqual(set(found), {r["id"] for r in repos})
        self.assertLess(len(search.queries), 120)  # 最低 50 ページ。分け方の無駄が多すぎないこと

    def test_same_star_count_over_limit_splits_by_created(self):
        repos = [item(i, 700, created=f"20{10 + i % 15}-0{1 + i % 9}-01T00:00:00Z") for i in range(1500)]
        repos += [item(5000 + i, 900 + i) for i in range(10)]
        found, _ = collect.collect(FakeSearch(repos), date(2025, 10, 4))
        self.assertEqual(len(found), 1510)

    def test_empty(self):
        self.assertEqual(collect.collect(FakeSearch([]), date(2025, 10, 4)), ({}, 0))


class SearcherTest(unittest.TestCase):
    def http_error(self, code, headers=None):
        return urllib.error.HTTPError("u", code, "err", headers or {}, io.BytesIO(b"{}"))

    def response(self, body=b'{"total_count": 1, "items": []}'):
        res = mock.MagicMock()
        res.__enter__.return_value = io.BytesIO(body)
        return res

    def test_waits_between_requests_and_retries_rate_limit(self):
        sleeps = []
        search = collect.Searcher("t", sleep=sleeps.append, clock=lambda: 1000)
        limited = self.http_error(403, {"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "1030"})
        with mock.patch("urllib.request.urlopen", side_effect=[self.response(), limited, self.response()]):
            search("stars:>=500")
            search("stars:>=500", 2)
        # 2 回目の前に間隔、rate limit で解除まで待ち（30 秒 + 1）、再試行の前にまた間隔
        self.assertEqual(sleeps, [collect.SEARCH_INTERVAL, 31, collect.SEARCH_INTERVAL])
        self.assertEqual(search.requests, 3)

    def test_retry_after_and_server_errors_then_gives_up(self):
        sleeps = []
        search = collect.Searcher("t", sleep=sleeps.append)
        errors = [self.http_error(429, {"Retry-After": "7"})] + [self.http_error(502)] * 4
        with mock.patch("urllib.request.urlopen", side_effect=errors), self.assertRaises(ranking.FetchError):
            search("q")
        self.assertIn(7.0, sleeps)

    def test_other_client_errors_fail_fast(self):
        search = collect.Searcher("t", sleep=lambda s: None)
        with mock.patch("urllib.request.urlopen", side_effect=self.http_error(401)), \
             self.assertRaises(ranking.FetchError):
            search("q")
        self.assertEqual(search.requests, 1)

    def test_422_is_fatal(self):
        search = collect.Searcher("t", sleep=lambda s: None)
        with mock.patch("urllib.request.urlopen", side_effect=self.http_error(422)), self.assertRaises(SystemExit):
            search("q")

    def test_incomplete_results_are_retried(self):
        search = collect.Searcher("t", sleep=lambda s: None)
        incomplete = self.response(b'{"total_count": 1, "incomplete_results": true, "items": []}')
        with mock.patch("urllib.request.urlopen", side_effect=[incomplete, self.response()]):
            self.assertFalse(search("q").get("incomplete_results"))


class RowsTest(unittest.TestCase):
    def test_rows(self):
        it = item(1, 600, license=None, homepage="https://x.dev")
        d = collect.daily_row(it, DAY)
        self.assertEqual((d["date"], d["id"], d["stargazers_count"], d["archived"]), (DAY, 1, 600, False))
        self.assertEqual(d["pushed_at"], datetime(2026, 10, 1, 12, tzinfo=timezone.utc))
        m = collect.master_row(it)
        self.assertEqual((m["full_name"], m["owner_type"], m["license"], m["homepage"]),
                         ("o/r1", "Organization", None, "https://x.dev"))
        self.assertIsNone(collect.master_row(item(2, 600))["homepage"])  # 空文字は None

    def test_merge_master_keeps_first_seen_and_unseen_repos(self):
        old = date(2026, 9, 1)
        prev = {1: {**collect.master_row(item(1, 600)), "first_seen": old, "last_seen": old},
                9: {**collect.master_row(item(9, 600)), "first_seen": old, "last_seen": old}}
        merged = collect.merge_master(prev, {1: item(1, 700, full_name="o/renamed"), 2: item(2, 600)}, DAY)
        self.assertEqual(merged[1]["full_name"], "o/renamed")  # 変わった情報は上書き
        self.assertEqual((merged[1]["first_seen"], merged[1]["last_seen"]), (old, DAY))
        self.assertEqual((merged[2]["first_seen"], merged[2]["last_seen"]), (DAY, DAY))
        self.assertEqual(merged[9]["last_seen"], old)  # 今日見つからなかったものは残す


@unittest.skipUnless(HAS_PYARROW, "pyarrow が入っていない（データ収集の workflow でだけ使う）")
class ParquetTest(unittest.TestCase):
    def test_write_and_read(self):
        import pyarrow.parquet as pq
        items = {1: item(1, 600), 2: item(2, 900, topics=[], language=None)}
        master = collect.merge_master({}, items, DAY)
        with tempfile.TemporaryDirectory() as d:
            daily_path, repos_path = Path(d) / "daily.parquet", Path(d) / "repos.parquet"
            collect.write_parquet([collect.daily_row(items[k], DAY) for k in sorted(items)], daily_path, "daily")
            collect.write_parquet([master[k] for k in sorted(master)], repos_path, "master")
            self.assertEqual(pq.read_table(daily_path).column("stargazers_count").to_pylist(), [600, 900])
            back = collect.read_master(repos_path)
        self.assertEqual(back[2]["topics"], [])
        self.assertIsNone(back[2]["language"])
        self.assertEqual(back[1]["first_seen"], DAY)
        self.assertEqual(back[1]["created_at"], datetime(2024, 1, 1, tzinfo=timezone.utc))


class MainTest(unittest.TestCase):
    def run_main(self, repos, *args):
        with mock.patch.object(collect, "Searcher", return_value=FakeSearch(repos)), \
             mock.patch.object(collect, "write_parquet") as write, \
             mock.patch.object(sys, "argv", ["collect.py", "--date", "2026-10-04", *args]), \
             mock.patch("sys.stdout"):
            collect.main(sleep=lambda s: None)
        return write

    def test_writes_daily_and_master(self):
        write = self.run_main([item(1, 600), item(2, 900)], "--out", "w")
        (daily, daily_path, k1), _ = write.call_args_list[0]
        (master, master_path, k2), _ = write.call_args_list[1]
        self.assertEqual((str(daily_path), k1, len(daily)), ("w/daily-2026-10-04.parquet", "daily", 2))
        self.assertEqual((str(master_path), k2, len(master)), ("w/repos.parquet", "master", 2))

    def test_low_coverage_writes_nothing(self):
        class Lossy(FakeSearch):  # 最初の件数だけ多く返す（取得の途中で取りこぼしたのと同じ状況）
            def __call__(self, query, page=1):
                res = super().__call__(query, page)
                if not self.queries[1:]:
                    res = {**res, "total_count": res["total_count"] * 2}
                return res
        with mock.patch.object(collect, "Searcher", return_value=Lossy([item(1, 600)])), \
             mock.patch.object(collect, "write_parquet") as write, \
             mock.patch.object(sys, "argv", ["collect.py", "--date", "2026-10-04"]), \
             mock.patch("sys.stdout"), self.assertRaises(SystemExit):
            collect.main(sleep=lambda s: None)
        write.assert_not_called()

    def test_search_failure_writes_nothing(self):
        failing = mock.Mock(side_effect=ranking.FetchError("down"))
        with mock.patch.object(collect, "Searcher", return_value=failing), \
             mock.patch.object(collect, "write_parquet") as write, \
             mock.patch.object(sys, "argv", ["collect.py"]), mock.patch("sys.stdout"), \
             self.assertRaises(SystemExit):
            collect.main(sleep=lambda s: None)
        write.assert_not_called()


if __name__ == "__main__":
    unittest.main()
