#!/usr/bin/env python3
"""新進気鋭のフレームワーク候補（Rising）を探し、★数を毎日記録する（表示はまだしない）。

frameworks.json の全カテゴリの discover_topics で GitHub を検索し、次の条件をすべて満たすものを記録する。
  - ★ MIN_STARS 以上、作成から MAX_AGE_DAYS 日以内、ACTIVE_DAYS 日以内に push あり
  - アーカイブ済み・フォークでない
  - frameworks.json に載っていない（載っているものは ranking.py が .state/stars.json に記録する）
  - 名前・説明・topic が discover.py のノイズ条件（NOISE / NOISE_TOPICS）に当たらない
frontend / backend の区別はしない（新しいリポジトリは機械的に判別しにくいため）。

記録先（どちらも workflow の最後のステップで master にコミットする。無制限に保持）:
  .state/rising.json        {日付（JST）: {"owner/repo": ★数}}（history.py と同じ形式）
  .state/rising-repos.json  {"owner/repo": 言語・作成日・説明・topics・初めて/最後に見つかった日・見つかった topic}

環境変数:
  GITHUB_TOKEN   検索に使う（検索 API は 30 回/分まで。リクエストの間隔を空けている）

使い方:
  python scripts/rising.py --dry-run
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, os.path.dirname(__file__))
import discover  # noqa: E402
import history  # noqa: E402
import ranking  # noqa: E402

STARS_PATH = ranking.ROOT / ".state" / "rising.json"
REPOS_PATH = ranking.ROOT / ".state" / "rising-repos.json"
MIN_STARS = 500
MAX_AGE_DAYS = 730
ACTIVE_DAYS = 90
MAX_PAGES = 10          # 検索 API は 1 クエリ 1000 件（100 件 × 10 ページ）まで
SEARCH_INTERVAL = 2.5   # 秒。検索 API の 30 回/分を超えないように


def topics(config: dict) -> list[str]:
    seen: list[str] = []
    for cat in config.values():
        for t in cat.get("discover_topics", []):
            if t not in seen:
                seen.append(t)
    return seen


def is_rising(item: dict, known: set[str]) -> bool:
    if item.get("archived") or item.get("fork"):
        return False
    if item["full_name"].lower() in known:
        return False
    if discover.NOISE.search(f"{item['full_name']} {item.get('description') or ''}"):
        return False
    if discover.NOISE_TOPICS & {t.lower() for t in item.get("topics") or []}:
        return False
    return True


def collect(config: dict, token: str | None, now: datetime, sleep=time.sleep) -> dict[str, dict]:
    """full_name → {item, found_via} を返す。topic ごとの検索に失敗したら警告してその topic だけ飛ばす。"""
    known = {r["repo"].lower() for cat in config.values() for r in cat["repos"]}
    created = (now - timedelta(days=MAX_AGE_DAYS)).date().isoformat()
    pushed = (now - timedelta(days=ACTIVE_DAYS)).date().isoformat()
    qualifiers = f"created:>={created} pushed:>={pushed}"
    found: dict[str, dict] = {}
    first = True
    for topic in topics(config):
        for page in range(1, MAX_PAGES + 1):
            if not first:
                sleep(SEARCH_INTERVAL)
            first = False
            try:
                items = discover.search(topic, MIN_STARS, token, sleep, qualifiers=qualifiers, page=page)
            except ranking.FetchError as e:
                ranking.warn(f"Rising: topic:{topic} の検索に失敗したためスキップ（{e}）")
                break
            for item in items:
                if is_rising(item, known):
                    c = found.setdefault(item["full_name"], {"item": item, "found_via": set()})
                    c["found_via"].add(topic)
            if len(items) < 100:
                break
    return found


def update_repos(repos: dict, found: dict[str, dict], today: str) -> None:
    for name, c in found.items():
        item = c["item"]
        meta = repos.setdefault(name, {"first_seen": today})
        meta.update({
            "last_seen": today,
            "language": item.get("language"),
            "created_at": (item.get("created_at") or "")[:10],
            "description": item.get("description") or "",
            "topics": item.get("topics") or [],
            "found_via": sorted(set(meta.get("found_via", [])) | c["found_via"]),
        })


def load_repos(path: Path | None = None) -> dict:
    path = path or REPOS_PATH
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError as e:
        raise SystemExit(f"{path} が JSON として読めません（マージ衝突などを確認してください）: {e}")
    if not isinstance(data, dict):
        raise SystemExit(f"{path} の形式が不正です")
    return data


def save_repos(repos: dict, path: Path | None = None) -> None:
    path = path or REPOS_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    # リポジトリ名・項目名の順に並べ、インデント付きで保存する
    path.write_text(json.dumps(repos, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")


def main(sleep=time.sleep) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="記録せず件数と上位を表示だけ")
    a = ap.parse_args()

    config = json.loads(ranking.CONFIG.read_text(encoding="utf-8"))
    token = os.environ.get("GITHUB_TOKEN")
    now = datetime.now(timezone.utc)
    today = now.astimezone(ranking.JST).date()

    found = collect(config, token, now, sleep)
    top = sorted(found.values(), key=lambda c: -c["item"].get("stargazers_count", 0))
    print(f"Rising 候補 {len(found)} 件（★{MIN_STARS:,} 以上・作成 {MAX_AGE_DAYS} 日以内・{ACTIVE_DAYS} 日以内に push）")
    for c in top[:10]:
        i = c["item"]
        print(f"  {i['full_name']}  ★{ranking.fmt_stars(i.get('stargazers_count', 0))}  "
              f"{i.get('language') or '-'}  {(i.get('created_at') or '')[:10]}")
    if a.dry_run or not found:
        return 0

    h = history.load(STARS_PATH)
    history.record(h, today, {name: c["item"].get("stargazers_count", 0) for name, c in found.items()})
    history.save(h, STARS_PATH)
    repos = load_repos()
    update_repos(repos, found, today.isoformat())
    save_repos(repos)
    print(f"★数を記録しました: .state/{STARS_PATH.name}, .state/{REPOS_PATH.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
