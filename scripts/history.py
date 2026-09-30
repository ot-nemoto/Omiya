"""★数の日次記録（.state/stars.json）の読み書き。

形式: {"YYYY-MM-DD"（JST）: {"owner/repo": ★数, ...}, ...}
ranking.py が毎日の★数を記録し、growth.py が過去の記録との差から伸び幅を出す。
ファイルは workflow の最後のステップで master にコミットされる。
"""
from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

PATH = Path(__file__).resolve().parent.parent / ".state" / "stars.json"
KEEP_DAYS = 35  # これより古い日付の記録は削除する（GROWTH_DAYS より十分長くしておく）


def load(path: Path | None = None) -> dict[str, dict[str, int]]:
    path = path or PATH
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}


def save(history: dict[str, dict[str, int]], path: Path | None = None) -> None:
    path = path or PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    # 日付・リポジトリ名の順に並べ、1 日 1 行にして差分を読みやすくする
    lines = [f"  {json.dumps(d)}: {json.dumps(dict(sorted(history[d].items())), ensure_ascii=False)}"
             for d in sorted(history)]
    path.write_text("{\n" + ",\n".join(lines) + "\n}\n", encoding="utf-8")


def record(history: dict, today: date, stars: dict[str, int], keep_days: int = KEEP_DAYS) -> None:
    """today の★数を追記（同じ日は上書き・マージ）し、keep_days より古い日付を削除する。"""
    history.setdefault(today.isoformat(), {}).update(stars)
    cutoff = (today - timedelta(days=keep_days)).isoformat()
    for d in [d for d in history if d < cutoff]:
        del history[d]


def base_date(history: dict, today: date, days: int) -> str | None:
    """伸び幅の起点にする日付。days 日前以前で最も新しい記録。無ければ today より前で最も古い記録。

    today より前の記録が 1 つも無ければ None。
    """
    target = (today - timedelta(days=days)).isoformat()
    past = sorted(d for d in history if d < today.isoformat())
    if not past:
        return None
    older = [d for d in past if d <= target]
    return older[-1] if older else past[0]
