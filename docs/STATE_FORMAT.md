# .state/ のデータ形式

`.state/` 配下のファイルに、どんなデータがどの JSON 構成で入っているかをまとめます。
どの workflow がいつ書き込むかは [DATA_FLOW.md](DATA_FLOW.md) を参照してください。

| ファイル | 書き込み元 | 中身 |
|---|---|---|
| [`stars.json`](#starsjson) | `scripts/ranking.py` | 掲載中のフレームワークの日ごとの★数 |
| [`rising.json`](#risingjson) | `scripts/rising.py` | Rising 候補の日ごとの★数 |
| [`rising-repos.json`](#rising-reposjson) | `scripts/rising.py` | Rising 候補の情報（言語・作成日など） |
| [`last-run`](#last-run) | update-ranking.yml の Commit state ステップ | 最終実行日 |

共通の決まり:

- 日付はすべて JST の `YYYY-MM-DD`（文字列）
- リポジトリは `owner/repo` の形の文字列（GitHub API の `full_name`。大文字小文字もそのまま）
- 記録は削除せず無制限に残す（`scripts/history.py` の `KEEP_DAYS = None`）
- インデント（2 スペース）付きの整形済み JSON で保存し、キーは名前順（日付は古い順）に並べる。
  そのまま読めて、差分もリポジトリ単位で見える
  （2026-10-01 の記録は 1 日分を 1 行にまとめた形式で、次回の書き込み時に整形済みの形式へ書き直される）
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
  - ★数の取得に失敗したカテゴリ（その日は、そのカテゴリのリポジトリがまるごと無い）
- 同じ日に複数回実行した場合は、その日最初の値を残す（手動実行しても定期実行の値が変わらない）
- `--dry-run` / `--sample` のときは書き込まない

使い方の例: ある日と 7 日前の★数の差で伸び幅を出す（`history.base_date()` が起点の日付を選ぶ）。

---

## rising.json

Rising 候補（作成から日の浅い、伸びている新しいリポジトリ）の★数を、日付ごとに記録します。
形は `stars.json` と同じです。

```json
{
  "2026-10-01": {
    "dashersw/gea": 1258,
    "rari-build/rari": 1176,
    "ratatui/ratzilla": 1467
  }
}
```

| 階層 | キー | 値 |
|---|---|---|
| 1 | 日付（JST） | その日の記録（オブジェクト） |
| 2 | リポジトリ（`owner/repo`） | ★数（整数） |

その日に次の条件をすべて満たしたリポジトリだけが入ります（条件は `scripts/rising.py` の定数）。

- 全カテゴリの `discover_topics` のどれかの topic が付いている
- ★ 1,000 以上（`MIN_STARS`）、作成から 730 日以内（`MAX_AGE_DAYS`）、90 日以内に push あり（`ACTIVE_DAYS`）
- アーカイブ済み・フォークでない、`frameworks.json` に載っていない
- 名前・説明・topic がノイズ条件（`discover.py` の `NOISE` / `NOISE_TOPICS`）に当たらない

そのため、同じリポジトリでも日によって入ったり入らなかったりします
（作成から 730 日を過ぎた、`frameworks.json` に採用された、など）。
1 件も見つからなかった日や、`--dry-run` のときは、その日付のキー自体を書きません。

---

## rising-repos.json

Rising 候補として一度でも見つかったリポジトリの情報です。

```json
{
  "dashersw/gea": {
    "created_at": "2026-03-18",
    "description": "A batteries-included, reactive JavaScript UI framework. ...",
    "first_seen": "2026-10-01",
    "found_via": [
      "javascript-framework"
    ],
    "language": "JavaScript",
    "last_seen": "2026-10-01",
    "topics": [
      "components",
      "javascript-framework",
      "reactivity",
      "ui-framework",
      "web-development"
    ]
  }
}
```

キーはリポジトリ（`owner/repo`）で、値は次の項目を持つオブジェクトです。

| 項目 | 型 | 中身 | 更新のしかた |
|---|---|---|---|
| `first_seen` | 文字列（日付） | 初めて見つかった日（JST） | 最初の 1 回だけ書く |
| `last_seen` | 文字列（日付） | 最後に見つかった日（JST） | 見つかるたびに更新 |
| `found_via` | 文字列の配列 | 見つかった検索の topic（名前順） | これまでの分に追加していく（減らない） |
| `language` | 文字列 / `null` | GitHub の主要言語 | 見つかるたびに最新の値で上書き |
| `created_at` | 文字列（日付） | リポジトリの作成日（UTC の日付部分） | 同上 |
| `description` | 文字列 | リポジトリの説明（無ければ `""`） | 同上 |
| `topics` | 文字列の配列 | リポジトリの topic | 同上 |

- 項目は削除しない。`last_seen` が古いものは、条件から外れた（作成から 730 日経過、`frameworks.json` に採用など）か、
  topic を外したなどで検索に出なくなったもの
- ★数はここには持たない（`rising.json` を見る）

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

stars = json.load(open(".state/stars.json"))
day = max(stars)                                # 最新の日付
top = sorted(stars[day].items(), key=lambda kv: -kv[1])[:5]

rising = json.load(open(".state/rising.json"))
repos = json.load(open(".state/rising-repos.json"))
for name, n in sorted(rising[max(rising)].items(), key=lambda kv: -kv[1]):
    print(name, n, repos[name]["language"], repos[name]["created_at"])
```
