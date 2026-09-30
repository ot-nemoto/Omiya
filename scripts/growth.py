#!/usr/bin/env python3
"""直近 GROWTH_DAYS 日の★の伸び幅ランキングを作り、Pinned 用の Gist に書き込む。

frameworks.json のカテゴリ（frontend / backend）ごとに 1 つの Gist を更新する。
GraphQL の stargazers を★を付けた日時の新しい順にたどり、期間内に付いた★を数える。
★を外した人は差し引かれないため「純増」ではなく「期間内に新しく付いた★の数」になる。
増加率は「期間内の★ ÷ 期間の始めの★数（現在の★数 − 期間内の★）」。

環境変数:
  GRAPHQL_TOKEN             GraphQL API に必須。ユーザーとして認証されるトークン（Classic PAT など）を使う。
                            workflow 標準の GITHUB_TOKEN（GitHub App）では他リポジトリの stargazers を
                            読めず "Resource not accessible by integration" になる。未設定なら GITHUB_TOKEN を使う
  GIST_PAT                  gist スコープ付きの Classic PAT
  GIST_ID_FRONTEND_GROWTH   frontend の伸び幅ランキングを書き込む Gist の ID
  GIST_ID_BACKEND_GROWTH    backend の伸び幅ランキングを書き込む Gist の ID
                            （未設定のカテゴリは表示だけしてスキップ）
  GROWTH_DAYS               期間の日数（既定 7）
  STALE_DAYS                この日数以上 push が無いリポジトリを除外（既定 365。0 で無効）

使い方:
  GRAPHQL_TOKEN=<Classic PAT> python scripts/growth.py --dry-run
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(__file__))
import ranking  # noqa: E402

GRAPHQL_URL = "https://api.github.com/graphql"
PAGE_SIZE = 100
MAX_PAGES = 100  # 1 リポジトリあたり期間内の★を最大 1 万件まで数える（超えたら打ち切って警告）

QUERY = """
query($owner: String!, $name: String!, $after: String) {
  repository(owner: $owner, name: $name) {
    nameWithOwner
    stargazerCount
    isArchived
    pushedAt
    primaryLanguage { name }
    stargazers(first: %d, after: $after, orderBy: {field: STARRED_AT, direction: DESC}) {
      pageInfo { hasNextPage endCursor }
      edges { starredAt }
    }
  }
}
""" % PAGE_SIZE


@dataclass
class Growth:
    name: str
    repo: str
    added: int     # 期間内に付いた★
    stars: int     # 現在の★
    language: str = "-"

    @property
    def rate(self) -> float | None:
        """期間の始めに★が 0（期間内に作られた等）なら None。"""
        base = self.stars - self.added
        return self.added / base * 100 if base > 0 else None


def graphql(variables: dict, token: str, sleep=time.sleep) -> dict:
    """5xx・429・通信エラー・GraphQL のエラー応答（NOT_FOUND 以外）は再試行し、それでも失敗したら FetchError。"""
    for wait in (*ranking.RETRY_WAITS, None):
        try:
            res = ranking.api("POST", GRAPHQL_URL, token, {"query": QUERY, "variables": variables})
            errors = [e for e in res.get("errors") or [] if e.get("type") != "NOT_FOUND"]
            if not errors:
                return res.get("data") or {}
            err = f"{variables['owner']}/{variables['name']}: {errors[0].get('message')}"
            if errors[0].get("type") == "FORBIDDEN":
                # トークンの種類・権限の問題なので再試行しても直らない
                raise ranking.FetchError(err + "（GRAPHQL_TOKEN に Classic PAT などユーザーのトークンを指定してください）")
            # "Something went wrong" や RATE_LIMITED などは一時的なことが多い
        except urllib.error.HTTPError as e:
            if e.code < 500 and e.code != 429:
                raise ranking.FetchError(f"GraphQL HTTP {e.code} {e.read().decode(errors='replace')[:200]}") from e
            err = f"GraphQL HTTP {e.code}"
        except (urllib.error.URLError, TimeoutError) as e:
            err = f"GraphQL: {e}"
        if wait is None:
            raise ranking.FetchError(err)
        sleep(wait)


def fetch_growth(repo: str, token: str, since: datetime, sleep=time.sleep) -> dict | None:
    """REST の /repos に近い形（stargazers_count など）に added を加えて返す。存在しなければ None。"""
    owner, name = repo.split("/", 1)
    after, added = None, 0
    for _ in range(MAX_PAGES):
        data = graphql({"owner": owner, "name": name, "after": after}, token, sleep)
        r = data.get("repository")
        if r is None:
            return None
        stars = r["stargazers"]
        for edge in stars["edges"]:
            if datetime.fromisoformat(edge["starredAt"].replace("Z", "+00:00")) < since:
                break
            added += 1
        else:
            if stars["pageInfo"]["hasNextPage"]:
                after = stars["pageInfo"]["endCursor"]
                continue
        break
    else:
        ranking.warn(f"{repo}: ★が {MAX_PAGES * PAGE_SIZE} 件を超えたため打ち切り")
    return {
        "full_name": r["nameWithOwner"],
        "stargazers_count": r["stargazerCount"],
        "archived": r["isArchived"],
        "pushed_at": r["pushedAt"],
        "language": (r.get("primaryLanguage") or {}).get("name"),
        "added": added,
    }


def build_growths(repos: list[dict], info: dict[str, dict | None], now: datetime, stale_days: int) -> list[Growth]:
    """ranking と同じ除外条件（見つからない・アーカイブ・更新停止）を適用し、伸びの大きい順に並べる。"""
    entries = ranking.build_entries(repos, info, now, stale_days, quiet=True)  # 除外の警告は ranking.py が出す
    growths = [Growth(e.name, e.repo, info[e.repo]["added"], e.stars, e.language) for e in entries]
    growths.sort(key=lambda g: (-g.added, g.name.lower()))
    return growths


def fmt_added(n: int) -> str:
    return f"+{n / 1000:.1f}k" if n >= 1000 else f"+{n}"


def fmt_rate(r: float | None) -> str:
    if r is None:
        return "new"
    return f"+{r:.0f}%" if round(r, 1) >= 100 else f"+{r:.1f}%"


def build_text(title: str, growths: list[Growth], days: int, updated: datetime) -> str:
    langs = [g.language[:ranking.LANG_MAX] for g in growths]
    name_w = max((ranking.width(g.name) for g in growths), default=0)
    lang_w = max((ranking.width(lang) for lang in langs), default=0)
    add_w = max((len(fmt_added(g.added)) for g in growths), default=0)
    rate_w = max((len(fmt_rate(g.rate)) for g in growths), default=0)
    rank_w = len(str(len(growths)))
    top = max((g.added for g in growths), default=0)
    # 「順位. 名前 言語 棒 +数 +率」の棒以外の幅を引いた残りを棒に使う
    fixed = rank_w + 2 + name_w + 1 + lang_w + 1 + 1 + add_w + 1 + rate_w
    bar_w = max(ranking.BAR_MIN, min(ranking.BAR_WIDTH, ranking.LINE_MAX - fixed))
    lines = [f"🚀 {title} ★ Growth {days}d ({updated:%Y-%m-%d %H:%M})"]
    for i, (g, lang) in enumerate(zip(growths, langs), 1):
        name = g.name + " " * (name_w - ranking.width(g.name))
        lang += " " * (lang_w - ranking.width(lang))
        lines.append(f"{i:>{rank_w}}. {name} {lang} {ranking.bar(g.added, top, bar_w)} "
                     f"{fmt_added(g.added):>{add_w}} {fmt_rate(g.rate):>{rate_w}}")
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="Gist を更新せず表示だけ")
    ap.add_argument("--category", action="append", help="対象カテゴリ（複数可。既定は全部）")
    a = ap.parse_args()

    config = json.loads(ranking.CONFIG.read_text(encoding="utf-8"))
    token = os.environ.get("GRAPHQL_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if not token:
        raise SystemExit("GraphQL API には GRAPHQL_TOKEN（または GITHUB_TOKEN）が必要です")
    gist_token = os.environ.get("GIST_PAT")
    days = int(os.environ.get("GROWTH_DAYS", "7"))
    if days < 1:
        raise SystemExit("GROWTH_DAYS は 1 以上を指定してください")
    stale_days = int(os.environ.get("STALE_DAYS", "365"))
    now = datetime.now(timezone.utc)
    since = now - timedelta(days=days)

    for key in a.category or list(config):
        cat = config[key]
        try:
            info = {r["repo"]: fetch_growth(r["repo"], token, since) for r in cat["repos"]}
        except ranking.FetchError as e:
            ranking.warn(f"{key}: 伸び幅を取得できなかったため今回の更新をスキップ（{e}）")
            continue
        growths = build_growths(cat["repos"], info, now, stale_days)
        if not growths:
            ranking.warn(f"{key}: 対象が 0 件のため今回の更新をスキップ")
            continue
        content = build_text(cat["title"], growths, days, now.astimezone(ranking.JST))
        print(content)
        if a.dry_run:
            continue
        var = f"GIST_ID_{key.upper()}_GROWTH"
        gist_id = os.environ.get(var)
        if not gist_id:
            print(f"{var} が未設定のため {key} の Gist 更新をスキップ")
            continue
        if not gist_token:
            raise SystemExit("GIST_PAT を環境変数で指定してください")
        ranking.update_gist(gist_id, gist_token, cat["growth_filename"], content)
    return 0


if __name__ == "__main__":
    sys.exit(main())
