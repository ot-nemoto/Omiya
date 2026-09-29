#!/usr/bin/env python3
"""大宮の天気を Description（About）に書き込む。

環境変数:
  GH_PAT         Administration: Read and write を付けた Fine-grained PAT
  TARGET_REPO    "owner/repo"（Description を書き換えるリポジトリ）
  DESC_FORMAT    combined(既定) | today | week
  DESC_MAX_LEN   Description の最大文字数（既定 120。GitHub の上限は 350）

使い方:
  python scripts/update_description.py --dry-run   # 取得して表示のみ（PAT 不要）
  python scripts/update_description.py             # 実際に更新
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(__file__))
import omiya_weather as ow  # noqa: E402


def md(d) -> str:
    return f"{d.month}/{d.day}"


# ---- 表示フォーマット --------------------------------------------------------
# ここを書き換えれば表示を自由に変えられる。先頭に日付を置き、重要な情報ほど前に置く。
def fmt_today(w: ow.Weather) -> str:
    """例: 9/29 大宮 ☀️24°C（19〜26°C）☔70% 💨北5m/s"""
    d = w.days[0]
    parts = [f"{md(w.today)} {ow.LOCATION_NAME} {ow.emoji(w.code)}{ow.rnd(w.temp)}°C"]
    parts.append(f"（{ow.rnd(d.tmin)}〜{ow.rnd(d.tmax)}°C）")
    if d.pop is not None:
        parts.append(f"☔{d.pop}%")
    if w.wind_ms is not None:
        parts.append(f"💨{ow.wind_dir_name(w.wind_deg)}{ow.rnd(w.wind_ms)}m/s")
    s = "".join(parts[:2]) + " " + " ".join(parts[2:])
    return s.strip()


def fmt_week(w: ow.Weather) -> str:
    """例: 大宮 9/29〜 ☀️26 ☀️25 🌤️22 ☁️21 🌧️19 ☔18 ☀️23（数字は最高気温）"""
    cells = " ".join(f"{ow.emoji(d.code)}{ow.rnd(d.tmax)}" for d in w.days)
    return f"{ow.LOCATION_NAME} {md(w.days[0].date)}〜 {cells}"


def fmt_combined(w: ow.Weather) -> str:
    """例: 9/29 大宮 ☀️24°C 19〜26 ☔70% 💨北5m/s ｜☀️🌤️⛅☁️🌧️☔☀️
    先頭の「今日」だけでカードに収まり、余裕があれば週間の絵文字列が見える。"""
    d = w.days[0]
    head = f"{md(w.today)} {ow.LOCATION_NAME} {ow.emoji(w.code)}{ow.rnd(w.temp)}°C {ow.rnd(d.tmin)}〜{ow.rnd(d.tmax)}"
    if d.pop is not None:
        head += f" ☔{d.pop}%"
    if w.wind_ms is not None:
        head += f" 💨{ow.wind_dir_name(w.wind_deg)}{ow.rnd(w.wind_ms)}m/s"
    strip = "".join(ow.emoji(x.code) for x in w.days[1:])
    return f"{head} ｜明日〜 {strip}"


FORMATS = {"combined": fmt_combined, "today": fmt_today, "week": fmt_week}


def build_description(w: ow.Weather, fmt: str = "combined", max_len: int = 120) -> str:
    s = " ".join(FORMATS[fmt](w).split())  # 改行・連続空白を除去（プレーン 1 行）
    if len(s) > max_len:
        s = s[: max_len - 1] + "…"
    return s


# ---- GitHub API --------------------------------------------------------------
def gh(method: str, repo: str, token: str, body: dict | None = None) -> dict:
    req = urllib.request.Request(
        f"https://api.github.com/repos/{repo}",
        method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "omiya-weather-description",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as res:
            return json.load(res)
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="replace")
        hint = ""
        if e.code in (403, 404):
            hint = "（PAT の対象リポジトリ・Administration 権限・有効期限を確認してください）"
        raise SystemExit(f"GitHub API エラー {e.code}{hint}: {detail}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="更新せず生成結果だけ表示")
    ap.add_argument("--format", default=os.environ.get("DESC_FORMAT", "combined"), choices=FORMATS)
    args = ap.parse_args()

    max_len = min(int(os.environ.get("DESC_MAX_LEN", "120")), 350)
    desc = build_description(ow.fetch(), args.format, max_len)
    print(f"description ({len(desc)} chars): {desc}")
    if args.dry_run:
        return 0

    repo, token = os.environ.get("TARGET_REPO"), os.environ.get("GH_PAT")
    if not repo or not token:
        raise SystemExit("TARGET_REPO と GH_PAT を環境変数で指定してください")
    if gh("GET", repo, token).get("description") == desc:
        print("変更なし: 更新をスキップ")
        return 0
    gh("PATCH", repo, token, {"description": desc})
    print(f"{repo} の Description を更新しました")
    return 0


if __name__ == "__main__":
    sys.exit(main())
