#!/usr/bin/env python3
"""frameworks.json に無い新しいフレームワーク候補を探し、Issue で知らせる。

カテゴリごとに discover_topics の topic で GitHub を検索し、次の条件をすべて満たすものを候補にする。
  - frameworks.json のどのカテゴリにも載っていない
  - ★ がそのカテゴリのランキング最下位以上（＝載せればランキングに入る）
  - アーカイブ済みでなく、STALE_DAYS 日以内に push がある
  - 名前・説明に awesome / boilerplate / template などを含まない（まとめ・雛形の除外）
  - まだ Issue にしていない（Open / Closed とも。Close すれば以後は通知されない）

候補ごとに Issue を 1 件作る（1 回あたり最大 MAX_ISSUES_PER_RUN 件。残りは次回）。
採用するなら frameworks.json に追加、不要なら Issue を Close するだけ。
既存 Issue との照合は、本文のマーカー（リポジトリ ID と名前）とタイトルで行うため、
ラベルやタイトルを編集したり、候補がリネームされたりしても再通知されない。

環境変数:
  GITHUB_TOKEN        検索と Issue 作成に使う（Issue 作成には issues: write 権限が必要）
  GITHUB_REPOSITORY   Issue を作るリポジトリ（owner/repo。Actions では自動で入る）
  STALE_DAYS          この日数以上 push が無いリポジトリは候補にしない（既定 365）

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
TITLE_RE = re.compile(r"^\[候補\] (\S+)")
MARKER_RE = re.compile(r"<!-- candidate: (\S+) id:(\d+) -->")


def search(topic: str, min_stars: int, token: str | None, sleep=time.sleep) -> list[dict]:
    """★の多い順に最大 100 件。5xx・429・通信エラーは再試行し、それでも失敗したら FetchError。

    422（クエリの誤り）は設定ミスなので SystemExit で失敗させる。
    """
    q = urllib.parse.quote(f"topic:{topic} stars:>={min_stars} archived:false")
    url = f"https://api.github.com/search/repositories?q={q}&sort=stars&order=desc&per_page=100"
    for wait in (*ranking.RETRY_WAITS, None):
        try:
            res = ranking.api("GET", url, token)
            if res.get("incomplete_results"):
                ranking.warn(f"topic:{topic} の検索結果が不完全です（GitHub 側のタイムアウト）")
            return res.get("items", [])
        except urllib.error.HTTPError as e:
            if e.code == 422:
                raise SystemExit(f"検索クエリの誤り topic:{topic}: {e.read().decode(errors='replace')[:200]}")
            if e.code < 500 and e.code != 429:
                raise ranking.FetchError(f"search topic:{topic}: HTTP {e.code}") from e
            err = f"search topic:{topic}: HTTP {e.code}"
        except (urllib.error.URLError, TimeoutError) as e:
            err = f"search topic:{topic}: {e}"
        if wait is None:
            raise ranking.FetchError(err)
        sleep(wait)


def is_candidate(item: dict, known: set, now: datetime, stale_days: int) -> bool:
    """known は掲載済みリポジトリの小文字の名前と ID（リネーム後の名前でも判定できるように）。"""
    if item["full_name"].lower() in known or item.get("id") in known:
        return False
    if item.get("archived") or item.get("fork"):
        return False
    if NOISE.search(f"{item['full_name']} {item.get('description') or ''}"):
        return False
    pushed = item.get("pushed_at")
    if stale_days and pushed:
        if now - datetime.fromisoformat(pushed.replace("Z", "+00:00")) > timedelta(days=stale_days):
            return False
    return True


def find_candidates(config: dict, token: str | None, now: datetime, stale_days: int,
                    fetch=ranking.fetch_repo) -> dict[str, dict]:
    """repo（小文字）→ {item, categories} を返す。★数の取得や検索に失敗したら FetchError。"""
    infos = {key: {r["repo"]: fetch(r["repo"], token) for r in cat["repos"]} for key, cat in config.items()}
    known: set = {r["repo"].lower() for cat in config.values() for r in cat["repos"]}
    for info in infos.values():
        for d in filter(None, info.values()):
            known.add(d.get("full_name", "").lower())
            known.add(d.get("id"))
    known.discard("")
    known.discard(None)
    found: dict[str, dict] = {}
    for key, cat in config.items():
        # ランキングと同じ除外条件（アーカイブ・更新停止）を通した最下位の★数を閾値にする
        entries = ranking.build_entries(cat["repos"], infos[key], now, stale_days, quiet=True)
        if not entries:
            continue
        threshold = min(e.stars for e in entries)
        for topic in cat.get("discover_topics", []):
            for item in search(topic, threshold, token):
                if not is_candidate(item, known, now, stale_days):
                    continue
                c = found.setdefault(item["full_name"].lower(), {"item": item, "categories": {}})
                c["categories"].setdefault(key, threshold)
    return found


def issue_title(item: dict) -> str:
    return f"[候補] {item['full_name']}"


def sanitize(text: str) -> str:
    """Issue 本文の表に入れる外部テキストから、改行・表の区切り・メンション・Issue リンクを無害化する。"""
    text = re.sub(r"\s+", " ", text).replace("|", "/")
    return re.sub(r"([@#])(?=\w)", "\\1\u200b", text)


def issue_body(item: dict, categories: dict[str, int]) -> str:
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
    now = datetime.now(timezone.utc)

    try:
        found = find_candidates(config, token, now, stale_days)
    except ranking.FetchError as e:
        ranking.warn(f"候補を検索できなかったため今回はスキップ（{e}）")
        return 0

    candidates = sorted(found.values(), key=lambda c: -c["item"].get("stargazers_count", 0))
    for c in candidates:
        i = c["item"]
        print(f"{i['full_name']}  ★{ranking.fmt_stars(i.get('stargazers_count', 0))}  "
              f"[{', '.join(c['categories'])}]  {i.get('description') or ''}")
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
        if len(new) > MAX_ISSUES_PER_RUN:
            ranking.warn(f"候補 {len(new)} 件のうち★の多い {MAX_ISSUES_PER_RUN} 件だけ Issue にします（残りは次回）")
        if new:
            ensure_label(repo, token)
        for c in new[:MAX_ISSUES_PER_RUN]:
            if created:
                sleep(1)  # 連続作成による secondary rate limit を避ける
            ranking.api("POST", f"https://api.github.com/repos/{repo}/issues", token, {
                "title": issue_title(c["item"]),
                "body": issue_body(c["item"], c["categories"]),
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
