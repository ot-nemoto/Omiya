#!/usr/bin/env python3
"""大宮の天気を Gist に複数行で書き込む（Pinned Gist 用）。

Pinned カードには Gist ファイルの先頭数行が表示されるため、改行が使える。
重要な情報ほど上に置くこと。1 行は 30〜35 文字程度に収める。

環境変数:
  GIST_PAT       gist スコープ付きの Classic PAT（Fine-grained PAT は Gist 非対応）
  GIST_ID        更新する Gist の ID（URL 末尾の英数字）
  GIST_FILENAME  Gist 内のファイル名（既定 omiya-weather.txt）

使い方:
  python scripts/update_gist.py --dry-run
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


# ---- 表示フォーマット（自由に編集可） ---------------------------------------------
def build_text(w: ow.Weather) -> str:
    d0 = w.days[0]
    lines = [
        f"{ow.LOCATION_NAME} {w.today.month}/{w.today.day} {ow.emoji(w.code)}{ow.rnd(w.temp)}°C "
        f"{ow.rnd(d0.tmin)}〜{ow.rnd(d0.tmax)}°C"
        + ("" if d0.pop is None else f" ☔{d0.pop}%"),
        f"💨{ow.wind_dir_name(w.wind_deg)}{ow.rnd(w.wind_ms)}m/s 体感{ow.rnd(w.feels)}°C"
        + ("" if d0.uv is None else f" UV{d0.uv:.0f}"),
    ]
    for d in w.days[1:]:
        pop = "–" if d.pop is None else d.pop
        lines.append(f"{d.date.month}/{d.date.day}({d.weekday}) {ow.emoji(d.code)} "
                     f"{ow.rnd(d.tmax)}/{ow.rnd(d.tmin)}° ☔{pop}%")
    return "\n".join(lines) + "\n"


def gist_api(method: str, gist_id: str, token: str, body: dict | None = None) -> dict:
    req = urllib.request.Request(
        f"https://api.github.com/gists/{gist_id}",
        method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "omiya-weather-gist",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=20) as res:
            return json.load(res)
    except urllib.error.HTTPError as e:
        hint = "（Classic PAT の gist スコープと GIST_ID を確認してください）" if e.code in (403, 404) else ""
        raise SystemExit(f"GitHub API エラー {e.code}{hint}: {e.read().decode(errors='replace')}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--sample", help="API の代わりに読み込む JSON（テスト用）")
    a = ap.parse_args()

    w = ow.parse(json.load(open(a.sample))) if a.sample else ow.fetch()
    content = build_text(w)
    print(content, end="")
    if a.dry_run:
        return 0

    gist_id, token = os.environ.get("GIST_ID"), os.environ.get("GIST_PAT")
    name = os.environ.get("GIST_FILENAME", "omiya-weather.txt")
    if not gist_id or not token:
        raise SystemExit("GIST_ID と GIST_PAT を環境変数で指定してください")
    current = gist_api("GET", gist_id, token).get("files", {}).get(name, {}).get("content")
    if current == content:
        print("変更なし: 更新をスキップ")
        return 0
    gist_api("PATCH", gist_id, token, {"files": {name: {"content": content}}})
    print("Gist を更新しました")
    return 0


if __name__ == "__main__":
    sys.exit(main())
