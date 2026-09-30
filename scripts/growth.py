#!/usr/bin/env python3
"""直近 GROWTH_DAYS 日の★の伸び幅ランキングを作り、Pinned 用の Gist に書き込む。

frameworks.json のカテゴリ（frontend / backend）ごとに 1 つの Gist を更新する。
伸び幅は「現在の★数 − 起点日の★数」（純増。★を外した分は差し引かれる）。
起点日の★数は ranking.py が毎日記録している .state/stars.json（history.py）から取る。
起点日は GROWTH_DAYS 日前以前で最も新しい記録。記録がまだ GROWTH_DAYS 日分たまっていなければ
最も古い記録を使い、見出しには実際の日数（例: 3d）を出す。
増加率は「伸び ÷ 起点日の★数」。

※ GraphQL の stargazers（★を付けた人と日時の一覧）は、この用途では空で返ってきたため使わない。

環境変数:
  GITHUB_TOKEN              現在の★数の取得に使う（任意）
  GIST_PAT                  gist スコープ付きの Classic PAT
  GIST_ID_FRONTEND_GROWTH   frontend の伸び幅ランキングを書き込む Gist の ID
  GIST_ID_BACKEND_GROWTH    backend の伸び幅ランキングを書き込む Gist の ID
                            （未設定のカテゴリは表示だけしてスキップ）
  GROWTH_DAYS               期間の日数（既定 7）
  STALE_DAYS                この日数以上 push が無いリポジトリを除外（既定 365。0 で無効）

使い方:
  python scripts/growth.py --dry-run
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from datetime import date, datetime, timezone

sys.path.insert(0, os.path.dirname(__file__))
import history  # noqa: E402
import ranking  # noqa: E402


@dataclass
class Growth:
    name: str
    repo: str
    added: int     # 起点日からの★の増減（マイナスもありうる）
    stars: int     # 現在の★
    language: str = "-"

    @property
    def rate(self) -> float | None:
        """起点日に★が 0 なら None。"""
        base = self.stars - self.added
        return self.added / base * 100 if base > 0 else None


def build_growths(repos: list[dict], info: dict[str, dict | None], base: dict[str, int],
                  now: datetime, stale_days: int) -> list[Growth]:
    """ranking と同じ除外条件（見つからない・アーカイブ・更新停止）を適用し、伸びの大きい順に並べる。

    起点日の記録が無いリポジトリ（途中で追加したもの等）は除外する。
    """
    entries = ranking.build_entries(repos, info, now, stale_days, quiet=True)  # 除外の警告は ranking.py が出す
    growths = []
    for e in entries:
        if e.repo not in base:
            print(f"{e.repo}: 起点日の記録が無いため伸び幅ランキングから除外", file=sys.stderr)
            continue
        growths.append(Growth(e.name, e.repo, e.stars - base[e.repo], e.stars, e.language))
    growths.sort(key=lambda g: (-g.added, g.name.lower()))
    return growths


def _signed(n: float, body: str) -> str:
    return ("+" if n >= 0 else "-") + body


def fmt_added(n: int) -> str:
    a = abs(n)
    return _signed(n, f"{a / 1000:.1f}k" if a >= 1000 else str(a))


def fmt_rate(r: float | None) -> str:
    if r is None:
        return "new"
    a = abs(r)
    if round(a, 1) == 0:
        return "+0.0%"  # -0.0% と出さない
    return _signed(r, f"{a:.0f}%" if round(a, 1) >= 100 else f"{a:.1f}%")


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
    token = os.environ.get("GITHUB_TOKEN")
    gist_token = os.environ.get("GIST_PAT")
    try:
        days = int(os.environ.get("GROWTH_DAYS", "7"))
    except ValueError:
        raise SystemExit("GROWTH_DAYS には整数を指定してください")
    if days < 1:
        raise SystemExit("GROWTH_DAYS は 1 以上を指定してください")
    if days >= history.KEEP_DAYS:
        raise SystemExit(f"GROWTH_DAYS は記録の保持日数（{history.KEEP_DAYS}）未満を指定してください")
    stale_days = int(os.environ.get("STALE_DAYS", "365"))
    now = datetime.now(timezone.utc)
    today: date = now.astimezone(ranking.JST).date()

    h = history.load()

    for key in a.category or list(config):
        cat = config[key]
        # 起点日はカテゴリごとに選ぶ（ある日にこのカテゴリの記録が欠けていても別の日を使えるように）
        base_day = history.base_date(h, today, days, [r["repo"] for r in cat["repos"]])
        if base_day is None:
            ranking.warn(f"{key}: 前日以前の★数の記録が無いため、伸び幅ランキングの更新をスキップ（記録の翌日から表示）")
            continue
        span = (today - date.fromisoformat(base_day)).days
        try:
            info = {r["repo"]: ranking.fetch_repo(r["repo"], token) for r in cat["repos"]}
        except ranking.FetchError as e:
            ranking.warn(f"{key}: ★数を取得できなかったため今回の更新をスキップ（{e}）")
            continue
        growths = build_growths(cat["repos"], info, h[base_day], now, stale_days)
        if not growths:
            ranking.warn(f"{key}: 対象が 0 件のため今回の更新をスキップ")
            continue
        content = build_text(cat["title"], growths, span, now.astimezone(ranking.JST))
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
