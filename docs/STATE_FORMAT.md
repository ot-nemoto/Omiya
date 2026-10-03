# .state/ のデータ形式

`.state/` 配下のファイルに、どんなデータがどの JSON 構成で入っているかをまとめます。
どの workflow がいつ書き込むかは [DATA_FLOW.md](DATA_FLOW.md) を参照してください。
GitHub 全体の★数のデータ（GitHub Releases に置く Parquet）は [RELEASE_DATA.md](RELEASE_DATA.md) を参照してください。

| ファイル | 書き込み元 | 中身 |
|---|---|---|
| [`stars.json`](#starsjson) | `scripts/ranking.py` | 掲載中のフレームワークの日ごとの★数 |
| [`last-run`](#last-run) | update-ranking.yml の Commit state ステップ | 最終実行日 |

共通の決まり:

- 日付はすべて JST の `YYYY-MM-DD`（文字列）
- リポジトリは `owner/repo` の形の文字列で、`frameworks.json` に書いた表記（大文字小文字もそのまま）
- 記録は削除せず無制限に残す（`scripts/history.py` の `KEEP_DAYS = None`）
- インデント（2 スペース）付きの整形済み JSON（UTF-8）で保存し、キーは名前順（日付は古い順）に並べる。
  名前順は大文字小文字を区別する文字コード順（`DioxusLabs/…` が `facebook/…` より前）
- 毎日の workflow の最後に github-actions[bot] が master に直接コミットする（変更が無ければコミットしない）

---

## stars.json

掲載中のフレームワーク（`frameworks.json` の `repos`）の★数を、日付ごとに記録します。

```json
{
  "2026-10-01": {
    "DioxusLabs/dioxus": 39303,
    "QwikDev/qwik": 22064,
    "facebook/react": 250849,
    "gatsbyjs/gatsby": 55941
  },
  "2026-10-02": {
    "DioxusLabs/dioxus": 39350,
    "QwikDev/qwik": 22070,
    "facebook/react": 250901,
    "gatsbyjs/gatsby": 55945
  }
}
```

（実際には 1 日に掲載中の全リポジトリが入ります。2 日目は形を示すための例です）

| 階層 | キー | 値 |
|---|---|---|
| 1 | 日付（JST） | その日の記録（オブジェクト） |
| 2 | リポジトリ（`owner/repo`） | ★数（整数） |

- frontend / backend の区別は持たない（どのカテゴリかは `frameworks.json` で分かる）
- キーのリポジトリ名は `frameworks.json` に書いた名前（リネームされても書いた名前のまま）
- 記録しないもの:
  - 見つからない（404）・アーカイブ済み・`STALE_DAYS` 日以上 push が無いリポジトリ（ランキングから除外されたもの）
  - ★数の取得に失敗したカテゴリ（そのカテゴリのリポジトリがまるごと無い。
    その日のうちに再実行して取得できれば、そのときの値が追加される）
- 同じ日に複数回実行した場合は、リポジトリごとにその日最初に記録した値を残す（手動実行しても定期実行の値が変わらない）
- `--dry-run` / `--sample` のときは書き込まない。`--category` を指定したときは指定したカテゴリだけ記録する（workflow では使っていない）

使い方の例: ある日と 7 日前の★数の差で伸び幅を出す（`history.base_date()` が起点の日付を選ぶ）。

---

## last-run

最終実行日（JST）が 1 行だけ入ったテキストファイルです（JSON ではありません）。

```
2026-10-01
```

毎日の workflow で上書きします。60 日間コミットが無いと scheduled workflow が止まるのを防ぐための keepalive 用で、
データとしての使い道はありません。

---

## 読み方の例

```python
import json

def load(name):
    try:
        with open(f".state/{name}", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return {}

stars = load("stars.json")
if stars:
    day = max(stars)                            # 最新の日付
    top = sorted(stars[day].items(), key=lambda kv: -kv[1])[:5]
    print(day, top)
```
