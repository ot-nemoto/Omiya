#!/usr/bin/env python3
"""frameworks.json に無い新しいフレームワーク候補を探し、Issue で知らせる。

下の「候補の探し方」で集めたリポジトリのうち、次の条件をすべて満たすものを候補にする。
  - frameworks.json のどのカテゴリにも載っていない
  - ★ がそのカテゴリのランキング最下位以上（＝載せればランキングに入る）
  - アーカイブ済みでなく、STALE_DAYS 日以内に push がある
  - 名前・説明に awesome / boilerplate / template などを含まない（まとめ・雛形の除外）
  - topic に shadowsocks / v2ray などの VPN 系（NOISE_TOPICS）が付いていない
  - まだ Issue にしていない（Open / Closed とも。Close すれば以後は通知されない）

候補の探し方（frameworks.json のカテゴリごと）:
  - discover_topics: topic で検索
  - discover_phrases: 説明文のキーワード（例: "php framework"）で検索（topic を付けていない定番を拾う）
  - discover_awesome: awesome リストの指定した節（例: awesome-go の「Web Frameworks」）に載っているリポジトリ

候補ごとに Issue を 1 件作る（1 回あたり最大 MAX_ISSUES_PER_RUN 件。環境変数 MAX_ISSUES で変更可。残りは次回）。
採用するなら frameworks.json に追加、不要なら Issue を Close するだけ。
既存 Issue との照合は、本文のマーカー（リポジトリ ID と名前）とタイトルで行うため、
ラベルやタイトルを編集したり、候補がリネームされたりしても再通知されない。

環境変数:
  GITHUB_TOKEN        検索と Issue 作成に使う（Issue 作成には issues: write 権限が必要）
  GITHUB_REPOSITORY   Issue を作るリポジトリ（owner/repo。Actions では自動で入る）
  STALE_DAYS          この日数以上 push が無いリポジトリは候補にしない（既定 365）
  MAX_ISSUES          1 回に作る Issue の上限（既定 MAX_ISSUES_PER_RUN）

使い方:
  python scripts/discover.py --dry-run
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))
import ranking  # noqa: E402

LABEL = "framework-candidate"
LABEL_COLOR = "0e8a16"
MAX_ISSUES_PER_RUN = 5
# 名前・説明にこれらを含むものは、フレームワーク本体ではない（まとめ・雛形・学習用・UI 部品など）とみなす
NOISE = re.compile(
    r"awesome|boilerplate|template|starter|example|tutorial|course|interview|roadmap|"
    r"cheat.?sheet|admin|dashboard|ui.?kit",
    re.IGNORECASE,
)
# これらの topic が 1 つでも付いていたら除外する（完全一致）。
# topic "ssr" は ShadowsocksR（VPN）の意味でも使われるため、その関連リポジトリを弾く
NOISE_TOPICS = {"shadowsocks", "v2ray", "clash", "trojan", "gfw", "vpn"}
TITLE_RE = re.compile(r"^\[候補\] (\S+)")
HEADING_RE = re.compile(r"^(#+)\s+(.*?)\s*#*\s*$")
GITHUB_LINK_RE = re.compile(r"https?://github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)")
NON_REPO_OWNERS = {"sponsors", "topics", "orgs", "features", "marketplace", "apps", "settings", "about"}
SEARCH_INTERVAL = 2.5  # 秒。検索 API の 30 回/分を超えないように
MARKER_RE = re.compile(r"<!-- candidate: (\S+) id:(\d+) -->")


def search(topic: str, min_stars: int, token: str | None, sleep=time.sleep,
           qualifiers: str = "", page: int = 1) -> list[dict]:
    """topic で検索する。★の多い順に最大 100 件（page でその先も取れる）。

    qualifiers は検索条件の追加（例: "created:>2025-01-01"）。
    """
    return search_query(f"topic:{topic}", min_stars, token, sleep, qualifiers, page)


def search_phrase(phrase: str, min_stars: int, token: str | None, sleep=time.sleep) -> list[dict]:
    """説明文に phrase を含むリポジトリを検索する（例: "php framework"）。★の多い順に最大 100 件。"""
    return search_query(f'"{phrase}" in:description', min_stars, token, sleep)


def search_query(term: str, min_stars: int, token: str | None, sleep=time.sleep,
                 qualifiers: str = "", page: int = 1) -> list[dict]:
    """term（"topic:x" や '"web framework" in:description'）で検索する。★の多い順に最大 100 件。

    5xx・429・通信エラーは再試行し、それでも失敗したら FetchError。
    422（クエリの誤り）は設定ミスなので SystemExit で失敗させる。
    """
    q = urllib.parse.quote(f"{term} stars:>={min_stars} archived:false {qualifiers}".strip())
    url = f"https://api.github.com/search/repositories?q={q}&sort=stars&order=desc&per_page=100&page={page}"
    for wait in (*ranking.RETRY_WAITS, None):
        try:
            res = ranking.api("GET", url, token)
            if res.get("incomplete_results"):
                ranking.warn(f"{term} の検索結果が不完全です（GitHub 側のタイムアウト）")
            return res.get("items", [])
        except urllib.error.HTTPError as e:
            if e.code == 422:
                raise SystemExit(f"検索クエリの誤り {term}: {e.read().decode(errors='replace')[:200]}")
            if e.code < 500 and e.code != 429:
                raise ranking.FetchError(f"search {term}: HTTP {e.code}") from e
            err = f"search {term}: HTTP {e.code}"
        except (urllib.error.URLError, TimeoutError) as e:
            err = f"search {term}: {e}"
        if wait is None:
            raise ranking.FetchError(err)
        sleep(wait)


def fetch_text(url: str, sleep=time.sleep) -> str:
    """テキストを取得する（awesome リストの README 用）。一時的なエラーは再試行し、それでも失敗したら FetchError。"""
    for wait in (*ranking.RETRY_WAITS, None):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "pinned-gist-maker"})
            with urllib.request.urlopen(req, timeout=20) as res:
                return res.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as e:
            if e.code < 500 and e.code != 429:
                raise ranking.FetchError(f"{url}: HTTP {e.code}") from e
            err = f"{url}: HTTP {e.code}"
        except (urllib.error.URLError, TimeoutError) as e:
            err = f"{url}: {e}"
        if wait is None:
            raise ranking.FetchError(err)
        sleep(wait)


def markdown_section(text: str, title: str) -> str | None:
    """見出しが title（大文字小文字は無視）の節の本文を返す。次の同じか上位の見出しまで。無ければ None。"""
    lines = text.splitlines()
    for i, line in enumerate(lines):
        m = HEADING_RE.match(line)
        if m and m.group(2).strip().lower() == title.lower():
            level, body = len(m.group(1)), []
            for rest in lines[i + 1:]:
                m2 = HEADING_RE.match(rest)
                if m2 and len(m2.group(1)) <= level:
                    break
                body.append(rest)
            return "\n".join(body)
    return None


def github_repos_in(text: str) -> list[str]:
    """本文中の https://github.com/owner/repo リンクを、出てきた順に重複なく返す。"""
    repos: list[str] = []
    seen: set[str] = set()
    for owner, name in GITHUB_LINK_RE.findall(text):
        name = re.sub(r"\.git$", "", name).rstrip(".")
        key = f"{owner}/{name}"
        if owner.lower() in NON_REPO_OWNERS or key.lower() in seen:
            continue
        seen.add(key.lower())
        repos.append(key)
    return repos


def awesome_repos(source: dict, sleep=time.sleep) -> list[str]:
    """awesome リストの指定した節に載っているリポジトリ（owner/repo）の一覧。節が無ければ警告して空。"""
    url = f"https://raw.githubusercontent.com/{source['repo']}/HEAD/{source.get('path', 'README.md')}"
    body = markdown_section(fetch_text(url, sleep), source["section"])
    if body is None:
        ranking.warn(f"{source['repo']} に見出し「{source['section']}」が見つかりません（リストの構成が変わった可能性）")
        return []
    return github_repos_in(body)


def is_candidate(item: dict, known: set, now: datetime, stale_days: int) -> bool:
    """known は掲載済みリポジトリの小文字の名前と ID（リネーム後の名前でも判定できるように）。"""
    if item["full_name"].lower() in known or item.get("id") in known:
        return False
    if item.get("archived") or item.get("fork"):
        return False
    if NOISE.search(f"{item['full_name']} {item.get('description') or ''}"):
        return False
    if NOISE_TOPICS & {t.lower() for t in item.get("topics") or []}:
        return False
    pushed = item.get("pushed_at")
    if stale_days and pushed:
        if now - datetime.fromisoformat(pushed.replace("Z", "+00:00")) > timedelta(days=stale_days):
            return False
    return True


def find_candidates(config: dict, token: str | None, now: datetime, stale_days: int,
                    fetch=ranking.fetch_repo, sleep=time.sleep) -> dict[str, dict]:
    """repo（小文字）→ {item, categories, sources} を返す。

    候補の探し方（カテゴリごと）:
      - discover_topics: topic で検索
      - discover_phrases: 説明文のキーワード（例: "php framework"）で検索
      - discover_awesome: awesome リストの指定した節に載っているリポジトリ
    掲載中の★数の取得や topic・キーワードの検索に失敗したら FetchError。
    awesome リストは取得に失敗しても警告してその 1 件を飛ばす（補助的な情報源のため）。
    """
    infos = {key: {r["repo"]: fetch(r["repo"], token) for r in cat["repos"]} for key, cat in config.items()}
    known: set = {r["repo"].lower() for cat in config.values() for r in cat["repos"]}
    for info in infos.values():
        for d in filter(None, info.values()):
            known.add(d.get("full_name", "").lower())
            known.add(d.get("id"))
    known.discard("")
    known.discard(None)
    found: dict[str, dict] = {}
    fetched: dict[str, dict | None] = {}  # awesome リストのリポジトリ情報（カテゴリをまたいで使い回す）
    searches = 0

    def add(item: dict, key: str, threshold: int, source: str) -> None:
        if item.get("stargazers_count", 0) < threshold or not is_candidate(item, known, now, stale_days):
            return
        c = found.setdefault(item["full_name"].lower(), {"item": item, "categories": {}, "sources": set()})
        c["categories"].setdefault(key, threshold)
        c["sources"].add(source)

    def throttled(fn, *args):
        nonlocal searches
        if searches:
            sleep(SEARCH_INTERVAL)
        searches += 1
        return fn(*args)

    for key, cat in config.items():
        # ランキングと同じ除外条件（アーカイブ・更新停止）を通した最下位の★数を閾値にする
        entries = ranking.build_entries(cat["repos"], infos[key], now, stale_days, quiet=True)
        if not entries:
            continue
        threshold = min(e.stars for e in entries)
        for topic in cat.get("discover_topics", []):
            for item in throttled(search, topic, threshold, token, sleep):
                add(item, key, threshold, f"topic:{topic}")
        for phrase in cat.get("discover_phrases", []):
            for item in throttled(search_phrase, phrase, threshold, token, sleep):
                add(item, key, threshold, f'説明文 "{phrase}"')
        for source in cat.get("discover_awesome", []):
            try:
                names = awesome_repos(source, sleep)
            except ranking.FetchError as e:
                ranking.warn(f"{source['repo']} を取得できなかったためスキップ（{e}）")
                continue
            for name in names:
                if name.lower() in known:
                    continue
                if name.lower() not in fetched:
                    try:
                        fetched[name.lower()] = fetch(name, token)
                    except ranking.FetchError as e:
                        ranking.warn(f"{name} の情報を取得できなかったためスキップ（{e}）")
                        fetched[name.lower()] = None
                item = fetched[name.lower()]
                if item:
                    add(item, key, threshold, f"{source['repo']}「{source['section']}」")
    return found


def issue_title(item: dict) -> str:
    return f"[候補] {item['full_name']}"


def sanitize(text: str) -> str:
    """Issue 本文の表に入れる外部テキストから、改行・表の区切り・メンション・Issue リンクを無害化する。"""
    text = re.sub(r"\s+", " ", text).replace("|", "/")
    return re.sub(r"([@#])(?=\w)", "\\1\u200b", text)


def issue_body(item: dict, categories: dict[str, int], sources: set[str] | None = None) -> str:
    full = item["full_name"]
    name = item.get("name") or full
    cats = "、".join(f"{k}（最下位 ★{ranking.fmt_stars(v)}）" for k, v in categories.items())
    entry = json.dumps({"name": name, "repo": full}, ensure_ascii=False)
    return f"""新しいフレームワーク候補が見つかりました。

| 項目 | 値 |
|---|---|
| リポジトリ | https://github.com/{full} |
| 説明 | {sanitize(item.get('description') or '-')} |
| ★ | {item.get('stargazers_count', 0):,} |
| 主要言語 | {item.get('language') or '-'} |
| topics | {sanitize(', '.join(item.get('topics') or []) or '-')} |
| 作成日 / 最終 push | {(item.get('created_at') or '-')[:10]} / {(item.get('pushed_at') or '-')[:10]} |
| 該当カテゴリ | {cats} |
| 見つけた方法 | {sanitize("、".join(sorted(sources or [])) or "-")} |

### 対応
- **採用する**: `frameworks.json` の該当カテゴリの `repos` に次の 1 行を追加し、この Issue を Close
  （`name` はリポジトリ名なので、必要なら表示名に直す。配列の最後に置くときは末尾のカンマを外す）
  ```json
  {entry},
  ```
- **採用しない**: この Issue を Close するだけ（以後このリポジトリは通知されません）

<!-- candidate: {full} id:{item.get('id', 0)} -->
"""


def existing_issue_repos(repo: str, token: str) -> set:
    """既に作った候補 Issue（Open / Closed）の対象リポジトリの小文字の名前と ID。

    ラベルが外されたりタイトルが編集されたりしても拾えるよう、全 Issue の本文マーカーとタイトルを見る。
    """
    seen: set = set()
    page = 1
    while True:
        url = f"https://api.github.com/repos/{repo}/issues?state=all&per_page=100&page={page}"
        issues = ranking.api("GET", url, token)
        for i in issues:
            if m := MARKER_RE.search(i.get("body") or ""):
                seen.add(m.group(1).lower())
                seen.add(int(m.group(2)))
            if m := TITLE_RE.match(i.get("title") or ""):
                seen.add(m.group(1).lower())
        if len(issues) < 100:
            return seen
        page += 1


def ensure_label(repo: str, token: str) -> None:
    try:
        ranking.api("GET", f"https://api.github.com/repos/{repo}/labels/{LABEL}", token)
    except urllib.error.HTTPError as e:
        if e.code != 404:
            raise
        ranking.api("POST", f"https://api.github.com/repos/{repo}/labels", token,
                    {"name": LABEL, "color": LABEL_COLOR, "description": "ランキングに追加するか検討する候補"})


def main(sleep=time.sleep) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="Issue を作らず候補を表示だけ")
    a = ap.parse_args()

    config = json.loads(ranking.CONFIG.read_text(encoding="utf-8"))
    token = os.environ.get("GITHUB_TOKEN")
    stale_days = int(os.environ.get("STALE_DAYS", "365"))
    try:
        max_issues = int(os.environ.get("MAX_ISSUES") or MAX_ISSUES_PER_RUN)
    except ValueError:
        raise SystemExit("MAX_ISSUES には整数を指定してください")
    now = datetime.now(timezone.utc)

    try:
        found = find_candidates(config, token, now, stale_days, sleep=sleep)
    except ranking.FetchError as e:
        ranking.warn(f"候補を検索できなかったため今回はスキップ（{e}）")
        return 0

    candidates = sorted(found.values(), key=lambda c: -c["item"].get("stargazers_count", 0))
    for c in candidates:
        i = c["item"]
        print(f"{i['full_name']}  ★{ranking.fmt_stars(i.get('stargazers_count', 0))}  "
              f"[{', '.join(c['categories'])}]  <{', '.join(sorted(c.get('sources', [])))}>  "
              f"{i.get('description') or ''}")
    print(f"候補 {len(candidates)} 件")
    if a.dry_run or not candidates:
        return 0

    repo = os.environ.get("GITHUB_REPOSITORY")
    if not token or not repo:
        raise SystemExit("GITHUB_TOKEN と GITHUB_REPOSITORY を環境変数で指定してください")
    created = 0
    try:
        seen = existing_issue_repos(repo, token)
        new = [c for c in candidates
               if c["item"]["full_name"].lower() not in seen and c["item"].get("id") not in seen]
        if len(new) > max_issues:
            ranking.warn(f"候補 {len(new)} 件のうち★の多い {max_issues} 件だけ Issue にします（残りは次回）")
        if new:
            ensure_label(repo, token)
        for c in new[:max_issues]:
            if created:
                sleep(1)  # 連続作成による secondary rate limit を避ける
            ranking.api("POST", f"https://api.github.com/repos/{repo}/issues", token, {
                "title": issue_title(c["item"]),
                "body": issue_body(c["item"], c["categories"], c.get("sources")),
                "labels": [LABEL],
            })
            created += 1
            print(f"Issue を作成しました: {c['item']['full_name']}")
    except urllib.error.HTTPError as e:
        hints = {403: "（Organization のポリシーで Actions の書き込みが制限されていないか確認してください）",
                 404: "（リポジトリ名と workflow の permissions: issues: write を確認してください）",
                 410: "（リポジトリの Issues 機能が無効です。Settings → General → Features で有効にしてください）"}
        raise SystemExit(f"Issue API エラー {e.code}{hints.get(e.code, '')}: {e.read().decode(errors='replace')}")
    except (urllib.error.URLError, TimeoutError) as e:
        ranking.warn(f"Issue 作成中に通信エラー（{e}）。{created} 件作成済み、残りは次回")
        return 0
    print(f"新規 Issue {created} 件（既に Issue 済み {len(candidates) - len(new)} 件）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
