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
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError as e:
        # 黙って空扱いにすると記録が消えるので、はっきり失敗させる
        raise SystemExit(f"{path} が JSON として読めません（マージ衝突などを確認してください）: {e}")
    if not isinstance(data, dict) or not all(isinstance(v, dict) for v in data.values()):
        raise SystemExit(f"{path} の形式が不正です（{{日付: {{リポジトリ: ★数}}}} を想定）")
    return data


def save(history: dict[str, dict[str, int]], path: Path | None = None) -> None:
    path = path or PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    # 日付・リポジトリ名の順に並べ、1 日 1 行にして差分を読みやすくする
    lines = [f"  {json.dumps(d)}: {json.dumps(dict(sorted(history[d].items())), ensure_ascii=False)}"
             for d in sorted(history)]
    path.write_text("{\n" + ",\n".join(lines) + "\n}\n", encoding="utf-8")


def record(history: dict, today: date, stars: dict[str, int], keep_days: int = KEEP_DAYS) -> None:
    """today の★数を追記し、keep_days より古い日付を削除する。

    同じ日に複数回実行した場合は、その日最初の値を残す（定期実行の時刻の値を起点に使うため）。
    """
    day = history.setdefault(today.isoformat(), {})
    for repo, n in stars.items():
        day.setdefault(repo, n)
    cutoff = (today - timedelta(days=keep_days)).isoformat()
    for d in [d for d in history if d < cutoff]:
        del history[d]


def base_date(history: dict, today: date, days: int, repos: list[str] | None = None) -> str | None:
    """伸び幅の起点にする日付。days 日前以前で最も新しい記録。無ければ today より前で最も古い記録。

    repos を渡すと、そのうち 1 つでも記録がある日だけを候補にする（カテゴリ単位で起点を選ぶため。
    ある日にそのカテゴリの取得が失敗していても、別の日の記録を使える）。
    候補が 1 つも無ければ None。
    """
    target = (today - timedelta(days=days)).isoformat()
    wanted = set(repos) if repos is not None else None
    past = sorted(d for d in history
                  if d < today.isoformat() and (wanted is None or wanted & history[d].keys()))
    if not past:
        return None
    older = [d for d in past if d <= target]
    return older[-1] if older else past[0]
