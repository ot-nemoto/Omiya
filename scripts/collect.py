#!/usr/bin/env python3
"""★500 以上・1 年以内に push のリポジトリ全体の★数を毎日集め、Parquet ファイルに書き出す。

書き出したファイルは workflow（collect-stars.yml）が GitHub Releases に添付する（リポジトリにはコミットしない）。
データの形は docs/RELEASE_DATA.md を参照。

  daily-YYYY-MM-DD.parquet  その日の数値（★数・フォーク数など）。1 リポジトリ 1 行
  repos.parquet             リポジトリ情報のマスタ（最新の状態）。前日の repos.parquet に今日の分を反映したもの

取得のしかた:
  - 検索 API（/search/repositories）で `stars:>=500 pushed:>=（1 年前）` を数え、★数の範囲で区切って全件を取る。
    検索 API は 1 つの検索で 1,000 件までしか返さないため、範囲の件数が 1,000 を超えたら細かく分ける
    （★数が同じものだけで 1,000 を超えたら、作成日でさらに分ける）
  - アーカイブ済みも含める
  - 検索 API は 30 回/分までなので、リクエストの間隔を SEARCH_INTERVAL 秒空ける（6.5 万件で 30 分前後）
  - 取れた件数が最初に数えた件数の MIN_COVERAGE 未満なら、欠けたデータを残さないよう失敗させる

環境変数:
  GITHUB_TOKEN   検索に使う

使い方:
  python scripts/collect.py --dry-run                     # 対象の件数を数えるだけ
  python scripts/collect.py --out work --prev work/repos.parquet
  python scripts/collect.py --out work --min-stars 50000  # 件数を絞って試す
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))
import ranking  # noqa: E402

MIN_STARS = 500
ACTIVE_DAYS = 365
PER_PAGE = 100
SEARCH_LIMIT = 1000        # 検索 API が 1 つの検索で返す上限
SPLIT_TARGET = 800         # 範囲を分けるときの 1 範囲あたりの目安（★数が動いても 1,000 を超えにくいように）
SEARCH_INTERVAL = 2.1      # 秒。検索 API の 30 回/分を超えないように
RETRY_WAITS = (5, 15, 30, 60)
RATE_LIMIT_WAIT_MAX = 120  # rate limit の解除待ちの上限（秒）
INCOMPLETE_RETRIES = 2     # 検索結果が不完全（incomplete_results）なときに取り直す回数
MIN_COVERAGE = 0.95
OLDEST_CREATED = date(2007, 10, 1)  # GitHub の公開より前


# ---- 検索 API ----------------------------------------------------------------------
class Searcher:
    """検索 API を呼ぶ。呼び出しの間隔を空け、一時的なエラーと rate limit は待って再試行する。"""

    def __init__(self, token: str | None, sleep=time.sleep, interval: float = SEARCH_INTERVAL,
                 clock=time.time):
        self.token = token
        self.sleep = sleep
        self.interval = interval
        self.clock = clock
        self.requests = 0

    def __call__(self, query: str, page: int = 1) -> dict:
        for attempt in range(INCOMPLETE_RETRIES + 1):
            res = self._get(query, page)
            if not res.get("incomplete_results"):
                return res
        ranking.warn(f"検索結果が不完全なまま進めます（{query} の {page} ページ目）")
        return res

    def _get(self, query: str, page: int) -> dict:
        url = ("https://api.github.com/search/repositories?q=" + urllib.parse.quote(query)
               + f"&sort=stars&order=desc&per_page={PER_PAGE}&page={page}")
        headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28",
                   "User-Agent": "pinned-gist-maker"}
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        for wait in (*RETRY_WAITS, None):
            if self.requests:
                self.sleep(self.interval)
            self.requests += 1
            try:
                with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=30) as res:
                    return json.load(res)
            except urllib.error.HTTPError as e:
                if e.code == 422:
                    raise SystemExit(f"検索クエリの誤り {query}: {e.read().decode(errors='replace')[:200]}")
                limited = self._rate_limit_wait(e)
                if limited is not None:
                    err, delay = f"rate limit（HTTP {e.code}）", limited
                elif e.code >= 500:
                    err, delay = f"HTTP {e.code}", wait
                else:
                    raise ranking.FetchError(f"search {query}: HTTP {e.code} {e.read().decode(errors='replace')[:200]}")
            except (urllib.error.URLError, TimeoutError) as e:
                err, delay = str(e), wait
            if wait is None:
                raise ranking.FetchError(f"search {query} page {page}: {err}")
            self.sleep(delay)

    def _rate_limit_wait(self, e: urllib.error.HTTPError) -> float | None:
        """rate limit なら待つ秒数、そうでなければ None。"""
        if e.code not in (403, 429):
            return None
        headers = e.headers or {}
        if headers.get("Retry-After"):
            return min(float(headers["Retry-After"]), RATE_LIMIT_WAIT_MAX)
        if headers.get("X-RateLimit-Remaining") == "0" and headers.get("X-RateLimit-Reset"):
            return min(max(float(headers["X-RateLimit-Reset"]) - self.clock(), 0) + 1, RATE_LIMIT_WAIT_MAX)
        return 60 if e.code == 429 else None


def stars_query(lo: int, hi: int | None) -> str:
    return f"stars:{lo}..{hi}" if hi is not None else f"stars:>={lo}"


def split_points(lo: int, hi: int, parts: int) -> list[tuple[int, int]]:
    """[lo, hi] を parts 個に分ける。★数は少ない側に偏っているので、等比で区切る。"""
    parts = max(2, min(parts, hi - lo + 1))
    bounds = [lo]
    for i in range(1, parts):
        b = round(lo * (hi / lo) ** (i / parts)) if lo > 0 else lo + (hi - lo) * i // parts
        bounds.append(max(b, bounds[-1] + 1))
    ranges = []
    for i, start in enumerate(bounds):
        end = bounds[i + 1] - 1 if i + 1 < len(bounds) else hi
        if start <= end:
            ranges.append((start, end))
    return ranges


def collect(search, pushed_since: date, min_stars: int = MIN_STARS) -> tuple[dict[int, dict], int]:
    """条件を満たすリポジトリを全件集める。(id → 検索結果の項目, 最初に数えた件数) を返す。"""
    base = f"pushed:>={pushed_since.isoformat()}"
    first = search(f"{stars_query(min_stars, None)} {base}")
    expected = first["total_count"]
    found: dict[int, dict] = {}
    if not first["items"]:
        return found, expected
    top = first["items"][0]["stargazers_count"]
    # 取得中に★が増えても漏れないよう、最上位より上は上限なしの範囲にする
    for lo, hi in [(min_stars, top), (top + 1, None)]:
        _collect_stars(search, base, lo, hi, found)
    return found, expected


def _collect_stars(search, base: str, lo: int, hi: int | None, found: dict) -> None:
    query = f"{stars_query(lo, hi)} {base}"
    res = search(query)
    total = res["total_count"]
    if total <= SEARCH_LIMIT:
        _take_pages(search, query, res, found)
    elif hi is None:
        _collect_stars(search, base, lo, lo * 10, found)
        _collect_stars(search, base, lo * 10 + 1, None, found)
    elif lo == hi:
        _collect_created(search, f"{stars_query(lo, hi)} {base}", OLDEST_CREATED, date.today(), found)
    else:
        for a, b in split_points(lo, hi, math.ceil(total / SPLIT_TARGET)):
            _collect_stars(search, base, a, b, found)


def _collect_created(search, query: str, start: date, end: date, found: dict) -> None:
    """★数が同じものだけで 1,000 件を超えたとき、作成日の範囲で半分ずつに分ける。"""
    q = f"{query} created:{start.isoformat()}..{end.isoformat()}"
    res = search(q)
    if res["total_count"] <= SEARCH_LIMIT or start == end:
        if res["total_count"] > SEARCH_LIMIT:
            ranking.warn(f"{q} は 1,000 件を超えるため、一部しか取れません")
        _take_pages(search, q, res, found)
        return
    mid = start + (end - start) // 2
    _collect_created(search, query, start, mid, found)
    _collect_created(search, query, mid + timedelta(days=1), end, found)


def _take_pages(search, query: str, first: dict, found: dict) -> None:
    for item in first["items"]:
        found[item["id"]] = item
    pages = math.ceil(min(first["total_count"], SEARCH_LIMIT) / PER_PAGE)
    for page in range(2, pages + 1):
        items = search(query, page)["items"]
        for item in items:
            found[item["id"]] = item
        if len(items) < PER_PAGE:
            break


# ---- 行の組み立て ------------------------------------------------------------------
def parse_time(s: str | None) -> datetime | None:
    return datetime.fromisoformat(s.replace("Z", "+00:00")) if s else None


def daily_row(item: dict, day: date) -> dict:
    return {
        "date": day,
        "id": item["id"],
        "stargazers_count": item.get("stargazers_count") or 0,
        "forks_count": item.get("forks_count") or 0,
        "open_issues_count": item.get("open_issues_count") or 0,
        "pushed_at": parse_time(item.get("pushed_at")),
        "archived": bool(item.get("archived")),
    }


def master_row(item: dict) -> dict:
    owner = item.get("owner") or {}
    license_ = item.get("license") or {}
    return {
        "id": item["id"],
        "full_name": item["full_name"],
        "owner_login": owner.get("login"),
        "owner_type": owner.get("type"),
        "description": item.get("description"),
        "topics": list(item.get("topics") or []),
        "language": item.get("language"),
        "license": license_.get("spdx_id"),
        "homepage": item.get("homepage") or None,
        "created_at": parse_time(item.get("created_at")),
        "fork": bool(item.get("fork")),
        "is_template": bool(item.get("is_template")),
    }


def merge_master(prev: dict[int, dict], items: dict[int, dict], day: date) -> dict[int, dict]:
    """前日までのマスタに今日の分を反映する。今日見つからなかったものは前の状態のまま残す。"""
    merged = dict(prev)
    for rid, item in items.items():
        row = master_row(item)
        row["first_seen"] = prev[rid]["first_seen"] if rid in prev else day
        row["last_seen"] = day
        merged[rid] = row
    return merged


# ---- Parquet の読み書き（pyarrow はここでだけ使う） -----------------------------------
def _schemas():
    import pyarrow as pa
    ts = pa.timestamp("s", tz="UTC")
    daily = pa.schema([
        ("date", pa.date32()), ("id", pa.int64()), ("stargazers_count", pa.int32()),
        ("forks_count", pa.int32()), ("open_issues_count", pa.int32()), ("pushed_at", ts),
        ("archived", pa.bool_()),
    ])
    master = pa.schema([
        ("id", pa.int64()), ("full_name", pa.string()), ("owner_login", pa.string()),
        ("owner_type", pa.string()), ("description", pa.string()), ("topics", pa.list_(pa.string())),
        ("language", pa.string()), ("license", pa.string()), ("homepage", pa.string()),
        ("created_at", ts), ("fork", pa.bool_()), ("is_template", pa.bool_()),
        ("first_seen", pa.date32()), ("last_seen", pa.date32()),
    ])
    return daily, master


def write_parquet(rows: list[dict], path: Path, kind: str) -> None:
    import pyarrow as pa
    import pyarrow.parquet as pq
    daily, master = _schemas()
    schema = daily if kind == "daily" else master
    table = pa.Table.from_pylist(rows, schema=schema)
    path.parent.mkdir(parents=True, exist_ok=True)
    pq.write_table(table, path, compression="zstd")


def read_master(path: Path) -> dict[int, dict]:
    import pyarrow.parquet as pq
    return {row["id"]: row for row in pq.read_table(path).to_pylist()}


# ---- main ---------------------------------------------------------------------------
def main(sleep=time.sleep) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="work", help="書き出し先のディレクトリ")
    ap.add_argument("--prev", help="前日までの repos.parquet（無ければ新しく作る）")
    ap.add_argument("--date", help="記録する日付（既定は今日の JST）")
    ap.add_argument("--min-stars", type=int, default=MIN_STARS, help="★の下限（試すときに件数を絞る用）")
    ap.add_argument("--dry-run", action="store_true", help="対象の件数を数えるだけ")
    a = ap.parse_args()

    now = datetime.now(timezone.utc)
    day = date.fromisoformat(a.date) if a.date else now.astimezone(ranking.JST).date()
    pushed_since = day - timedelta(days=ACTIVE_DAYS)
    search = Searcher(os.environ.get("GITHUB_TOKEN"), sleep=sleep)

    if a.dry_run:
        try:
            total = search(f"{stars_query(a.min_stars, None)} pushed:>={pushed_since.isoformat()}")["total_count"]
        except ranking.FetchError as e:
            raise SystemExit(f"検索に失敗しました（{e}）")
        print(f"対象 {total:,} 件（★{a.min_stars:,} 以上・{pushed_since} 以降に push、アーカイブ済みを含む）")
        return 0

    prev_path = Path(a.prev) if a.prev else None
    if prev_path and prev_path.exists():
        prev = read_master(prev_path)
    else:
        prev = {}
        print("前日の repos.parquet が無いため、マスタを新しく作ります")

    started = time.monotonic()
    try:
        items, expected = collect(search, pushed_since, a.min_stars)
    except ranking.FetchError as e:
        raise SystemExit(f"検索に失敗したため、今回は何も書き出しません（{e}）")
    minutes = (time.monotonic() - started) / 60
    print(f"取得 {len(items):,} 件 / 対象 {expected:,} 件（検索 {search.requests} 回、{minutes:.1f} 分）")
    if expected and len(items) < expected * MIN_COVERAGE:
        raise SystemExit(f"取れた件数が対象の {MIN_COVERAGE:.0%} 未満のため、今回は何も書き出しません")

    out = Path(a.out)
    daily_path = out / f"daily-{day.isoformat()}.parquet"
    write_parquet([daily_row(items[rid], day) for rid in sorted(items)], daily_path, "daily")
    master = merge_master(prev, items, day)
    write_parquet([master[rid] for rid in sorted(master)], out / "repos.parquet", "master")
    new = sum(1 for rid in items if rid not in prev)
    print(f"書き出しました: {daily_path}（{len(items):,} 行）, {out / 'repos.parquet'}（{len(master):,} 行、うち新規 {new:,}）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
