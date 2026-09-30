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

★数の取得で一時的なエラー（5xx・429・通信エラー）が再試行後も続いた場合、そのカテゴリの
Gist は更新せずに前回の内容を残す（ジョブは成功扱い）。見出しの更新日時で鮮度が分かる。

使い方:
  python scripts/ranking.py --dry-run
  python scripts/ranking.py --dry-run --sample tests/sample_repos.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import unicodedata
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "frameworks.json"
JST = timezone(timedelta(hours=9))
RETRY_WAITS = (2, 5)  # 一時的なエラーの再試行までの待ち秒数
# Pinned カードは 1 行 55 桁前後で切れる。行（見出し以外）はこの桁数に収め、はみ出す分は棒を短くする
LINE_MAX = 49
BAR_WIDTH = 14  # 1 位の棒の最大の長さ（文字数）
BAR_MIN = 4     # 桁が足りないときでも残す棒の長さ
LANG_MAX = 10   # 言語名の最大桁数（"Jupyter Notebook" などは切り詰める）


class FetchError(Exception):
    """再試行しても★数を取得できなかった。"""


def warn(msg: str) -> None:
    """GitHub Actions のサマリーに警告として表示する（ローカルではただの出力）。"""
    print(f"::warning::{msg}", file=sys.stderr)


@dataclass
class Entry:
    name: str
    repo: str
    stars: int
    language: str = "-"


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


def fetch_repo(repo: str, token: str | None, sleep=time.sleep) -> dict | None:
    """リポジトリ情報を返す。存在しなければ None（リネームはリダイレクトで追従される）。

    5xx・429・通信エラーは RETRY_WAITS に従って再試行し、それでも失敗したら FetchError。
    """
    for wait in (*RETRY_WAITS, None):
        try:
            return api("GET", f"https://api.github.com/repos/{repo}", token)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            if e.code < 500 and e.code != 429:
                raise FetchError(f"{repo}: HTTP {e.code} {e.read().decode(errors='replace')[:200]}") from e
            err = f"{repo}: HTTP {e.code}"
        except (urllib.error.URLError, TimeoutError) as e:
            err = f"{repo}: {e}"
        if wait is None:
            raise FetchError(err)
        sleep(wait)


# ---- ランキング作成 ----------------------------------------------------------------
def build_entries(repos: list[dict], info: dict[str, dict | None],
                  now: datetime, stale_days: int, quiet: bool = False) -> list[Entry]:
    """info（repo → API レスポンス）から除外条件を適用し、★の多い順に並べる。quiet なら警告を出さない。"""
    warn_ = (lambda msg: None) if quiet else warn
    entries = []
    for r in repos:
        d = info.get(r["repo"])
        if d is None:
            warn_(f"{r['repo']} が見つからないため除外")
            continue
        if d.get("archived"):
            warn_(f"{r['repo']} はアーカイブ済みのため除外")
            continue
        if stale_days and d.get("pushed_at"):
            pushed = datetime.fromisoformat(d["pushed_at"].replace("Z", "+00:00"))
            if now - pushed > timedelta(days=stale_days):
                warn_(f"{r['repo']} は {stale_days} 日以上 push が無いため除外")
                continue
        language = r.get("language") or d.get("language") or "-"  # frameworks.json の指定を優先
        entries.append(Entry(r["name"], r["repo"], int(d.get("stargazers_count") or 0), language))
    entries.sort(key=lambda e: (-e.stars, e.name.lower()))
    return entries


def fmt_stars(n: int) -> str:
    return f"{n / 1000:.1f}k" if n >= 1000 else str(n)


def width(s: str) -> int:
    """全角文字を 2 として数えた表示幅。"""
    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in s)


def bar(stars: int, top: int, bar_w: int = BAR_WIDTH) -> str:
    """1 位を bar_w とした横棒。フォント差でずれにくいよう █ だけを使い、★ が 1 以上なら最低 1 つは出す。"""
    n = max(1, round(bar_w * stars / top)) if top and stars > 0 else 0
    return "█" * n + " " * (bar_w - n)


def build_text(title: str, entries: list[Entry], updated: datetime) -> str:
    langs = [e.language[:LANG_MAX] for e in entries]
    name_w = max((width(e.name) for e in entries), default=0)
    lang_w = max((width(lang) for lang in langs), default=0)
    star_w = max((len(fmt_stars(e.stars)) for e in entries), default=0)
    rank_w = len(str(len(entries)))
    top = max((e.stars for e in entries), default=0)
    # 「順位. 名前 言語 棒 ★数」の棒以外の幅を引いた残りを棒に使う
    fixed = rank_w + 2 + name_w + 1 + lang_w + 1 + 1 + star_w
    bar_w = max(BAR_MIN, min(BAR_WIDTH, LINE_MAX - fixed))
    lines = [f"🏆 {title} ★ Ranking ({updated:%Y-%m-%d %H:%M})"]
    for i, (e, lang) in enumerate(zip(entries, langs), 1):
        name = e.name + " " * (name_w - width(e.name))
        lang += " " * (lang_w - width(lang))
        lines.append(f"{i:>{rank_w}}. {name} {lang} {bar(e.stars, top, bar_w)} {fmt_stars(e.stars):>{star_w}}")
    return "\n".join(lines) + "\n"


# ---- Gist 更新 ---------------------------------------------------------------------
def update_gist(gist_id: str, token: str, filename: str, content: str) -> None:
    try:
        files = api("GET", f"https://api.github.com/gists/{gist_id}", token).get("files", {})
        if len(files) > 1 and min(files) != filename:
            # Pinned カードには名前順で先頭のファイルが出る
            warn(f"Gist {gist_id} には複数のファイルがあり、Pin には {min(files)} が表示されます")
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
        try:
            info = {r["repo"]: (sample.get(r["repo"]) if sample is not None else fetch_repo(r["repo"], token))
                    for r in cat["repos"]}
        except FetchError as e:
            warn(f"{key}: ★数を取得できなかったため今回の更新をスキップ（{e}）")
            continue
        entries = build_entries(cat["repos"], info, now, stale_days)
        if not entries:
            warn(f"{key}: 対象が 0 件のため今回の更新をスキップ")
            continue
        content = build_text(cat["title"], entries, now.astimezone(JST))
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
