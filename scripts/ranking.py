#!/usr/bin/env python3
"""フレームワークの GitHub ★数ランキングを作り、Pinned 用の Gist に書き込む。

frameworks.json のカテゴリ（frontend / backend）ごとに 1 つの Gist を更新する。
Pinned カードには Gist ファイルの先頭数行しか出ないため、上位ほど上に並べる。

環境変数:
  GITHUB_TOKEN        ★数の取得に使う（任意。無いと 60 回/時の制限にかかりやすい）
  GIST_PAT            gist スコープ付きの Classic PAT（Fine-grained PAT は Gist 非対応）
  GIST_ID_FRONTEND    frontend ランキングを書き込む Gist の ID
  GIST_ID_BACKEND     backend ランキングを書き込む Gist の ID
                      （未設定のカテゴリは表示だけしてスキップ）
  STALE_DAYS          この日数以上 push が無いリポジトリを除外（既定 365。0 で無効）

使い方:
  python scripts/ranking.py --dry-run
  python scripts/ranking.py --dry-run --sample tests/sample_repos.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import unicodedata
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "frameworks.json"
JST = timezone(timedelta(hours=9))


@dataclass
class Entry:
    name: str
    repo: str
    stars: int


# ---- GitHub API -------------------------------------------------------------------
def api(method: str, url: str, token: str | None, body: dict | None = None) -> dict:
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "pinned-gist-maker",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(
        url, method=method, headers=headers,
        data=json.dumps(body).encode() if body is not None else None,
    )
    with urllib.request.urlopen(req, timeout=20) as res:
        return json.load(res)


def fetch_repo(repo: str, token: str | None) -> dict | None:
    """リポジトリ情報を返す。存在しなければ None（リネームはリダイレクトで追従される）。"""
    try:
        return api("GET", f"https://api.github.com/repos/{repo}", token)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise SystemExit(f"GitHub API エラー {e.code} ({repo}): {e.read().decode(errors='replace')}")


# ---- ランキング作成 ----------------------------------------------------------------
def build_entries(repos: list[dict], info: dict[str, dict | None],
                  now: datetime, stale_days: int) -> list[Entry]:
    """info（repo → API レスポンス）から除外条件を適用し、★の多い順に並べる。"""
    entries = []
    for r in repos:
        d = info.get(r["repo"])
        if d is None:
            print(f"warn: {r['repo']} が見つからないため除外", file=sys.stderr)
            continue
        if d.get("archived"):
            print(f"warn: {r['repo']} はアーカイブ済みのため除外", file=sys.stderr)
            continue
        pushed = datetime.fromisoformat(d["pushed_at"].replace("Z", "+00:00"))
        if stale_days and now - pushed > timedelta(days=stale_days):
            print(f"warn: {r['repo']} は {stale_days} 日以上 push が無いため除外", file=sys.stderr)
            continue
        entries.append(Entry(r["name"], r["repo"], int(d["stargazers_count"])))
    entries.sort(key=lambda e: (-e.stars, e.name.lower()))
    return entries


def fmt_stars(n: int) -> str:
    return f"{n / 1000:.1f}k" if n >= 1000 else str(n)


def width(s: str) -> int:
    """全角文字を 2 として数えた表示幅。"""
    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in s)


def build_text(title: str, entries: list[Entry], today: datetime) -> str:
    name_w = max((width(e.name) for e in entries), default=0)
    star_w = max((len(fmt_stars(e.stars)) for e in entries), default=0)
    rank_w = len(str(len(entries)))
    lines = [f"🏆 {title} ★ Ranking ({today:%Y-%m-%d})"]
    for i, e in enumerate(entries, 1):
        pad = " " * (name_w - width(e.name))
        lines.append(f"{i:>{rank_w}}. {e.name}{pad}  ★{fmt_stars(e.stars):>{star_w}}")
    return "\n".join(lines) + "\n"


# ---- Gist 更新 ---------------------------------------------------------------------
def update_gist(gist_id: str, token: str, filename: str, content: str) -> None:
    try:
        files = api("GET", f"https://api.github.com/gists/{gist_id}", token).get("files", {})
        if files.get(filename, {}).get("content") == content:
            print(f"変更なし: {filename} の更新をスキップ")
            return
        if filename not in files and len(files) == 1:
            # 作成時の仮ファイル名を置き換える（Pinned には名前順で先頭のファイルが出るため）
            (old,) = files
            patch = {old: {"filename": filename, "content": content}}
        else:
            patch = {filename: {"content": content}}
        api("PATCH", f"https://api.github.com/gists/{gist_id}", token, {"files": patch})
    except urllib.error.HTTPError as e:
        hint = "（Classic PAT の gist スコープと Gist ID を確認してください）" if e.code in (403, 404) else ""
        raise SystemExit(f"Gist API エラー {e.code}{hint}: {e.read().decode(errors='replace')}")
    print(f"Gist を更新しました: {filename}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="Gist を更新せず表示だけ")
    ap.add_argument("--sample", help="API の代わりに読み込む JSON（repo → レスポンス。テスト用）")
    ap.add_argument("--category", action="append", help="対象カテゴリ（複数可。既定は全部）")
    a = ap.parse_args()

    config = json.loads(CONFIG.read_text(encoding="utf-8"))
    sample = json.loads(Path(a.sample).read_text(encoding="utf-8")) if a.sample else None
    token = os.environ.get("GITHUB_TOKEN")
    gist_token = os.environ.get("GIST_PAT")
    stale_days = int(os.environ.get("STALE_DAYS", "365"))
    now = datetime.now(timezone.utc)

    for key in a.category or list(config):
        cat = config[key]
        info = {r["repo"]: (sample.get(r["repo"]) if sample is not None else fetch_repo(r["repo"], token))
                for r in cat["repos"]}
        content = build_text(cat["title"], build_entries(cat["repos"], info, now, stale_days),
                             now.astimezone(JST))
        print(content)
        if a.dry_run:
            continue
        gist_id = os.environ.get(f"GIST_ID_{key.upper()}")
        if not gist_id:
            print(f"GIST_ID_{key.upper()} が未設定のため {key} の Gist 更新をスキップ")
            continue
        if not gist_token:
            raise SystemExit("GIST_PAT を環境変数で指定してください")
        update_gist(gist_id, gist_token, cat["filename"], content)
    return 0


if __name__ == "__main__":
    sys.exit(main())
