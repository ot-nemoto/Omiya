# GitHub 全体の★数データ（GitHub Releases）

★500 以上・1 年以内に push があるリポジトリ全体（アーカイブ済み・フォークを含む）について、★数などを毎日記録したデータです。
件数が多く（2026-10 時点で約 6.5 万件）、リポジトリにコミットするには大きすぎるため、
GitHub Releases の添付ファイル（Parquet 形式）として置いています。

- 集めるスクリプト: `scripts/collect.py`
- workflow: `.github/workflows/collect-stars.yml`（毎日 JST 3:37。手動実行も可）
- 手元への同期: `scripts/sync_data.sh`

## 置き場所

| リリース（タグ） | 添付ファイル | 更新のしかた |
|---|---|---|
| `data-YYYY-MM`（月ごと） | `daily-YYYY-MM-DD.parquet` | 毎日 1 つ追加する。一度添付したら書き換えない（同じ日に再実行しても最初の分を残す） |
| `data-YYYY-MM`（月ごと） | `repos-YYYY-MM.parquet` | `repos.parquet` の控え。毎日上書きする（その月の最後の状態が残る） |
| `data-latest` | `repos.parquet` | 毎日上書きする |

どのリリースも pre-release で作っているので、「Latest release」にはなりません（リポジトリのトップのサイドバーに Latest として出ません）。
`--latest=false` だけでは、ほかに通常のリリースが無いとき GitHub が Latest 扱いにするためです。

2026-10-03 の初回の時点で、1 日分（`daily-*.parquet`）は約 1.1MB、`repos.parquet` は約 7.6MB でした（月ごとの控えを含め、1 年で 500MB 前後の見込み）。

`repos.parquet` の上書き（`gh release upload --clobber`）は古いファイルを消してから添付するため、途中で失敗すると消えたままになります。
その場合、翌日の実行は「`repos.parquet` がありません」で失敗します（マスタを作り直して `first_seen` が消えるのを防ぐため）。
その月の `repos-YYYY-MM.parquet` をダウンロードし、`repos.parquet` という名前で `data-latest` に添付し直してから再実行してください。
作り直してよい場合は、手動実行（Run workflow）で `fresh` にチェックを入れます。

## テーブル

2 つのテーブルは `id`（GitHub のリポジトリ ID。リネームしても変わらない）で結び付けます。
日付は JST、日時は UTC です。

### daily（`daily-YYYY-MM-DD.parquet`）

その日の数値です。1 リポジトリ 1 行。

| 列 | 型 | 中身 |
|---|---|---|
| `date` | date | 記録した日（JST） |
| `id` | int64 | リポジトリ ID |
| `stargazers_count` | int32 | ★数 |
| `forks_count` | int32 | フォーク数 |
| `open_issues_count` | int32 | 開いている Issue と PR の合計 |
| `pushed_at` | timestamp（UTC） | 最後に push された日時 |
| `archived` | bool | アーカイブ済みか |

### repos（`repos.parquet`）

リポジトリ情報のマスタです。1 リポジトリ 1 行で、最新の状態だけを持ちます（変更の履歴は持たない）。

| 列 | 型 | 中身 |
|---|---|---|
| `id` | int64 | リポジトリ ID |
| `full_name` | string | `owner/repo`（リネームされたら新しい名前で上書き） |
| `owner_login` / `owner_type` | string | 持ち主の名前と、`User` か `Organization` か |
| `description` | string / null | 説明文 |
| `topics` | list&lt;string&gt; | topic の一覧 |
| `language` | string / null | GitHub が判定した主要言語 |
| `license` | string / null | ライセンスの SPDX ID（`MIT` など。判定できないものは `NOASSERTION`） |
| `homepage` | string / null | 公式サイトの URL |
| `created_at` | timestamp（UTC） | 作成日時 |
| `fork` / `is_template` | bool | フォークか、テンプレートリポジトリか |
| `first_seen` / `last_seen` | date | このデータに最初・最後に現れた日（JST） |

- 条件から外れて検索に出なくなったリポジトリも、行は消さずに残します（`last_seen` がその日で止まる）。
- 説明や topics などは、検索に出た日の値で上書きします。

## 取得のしかた

- 検索 API で `stars:>=500 pushed:>=（1 年前の日付） fork:true` を数え、★数の範囲で区切って全件を取ります
  （検索は既定でフォークを除くため `fork:true` を付けて含めています）。
  検索 API は 1 つの検索で 1,000 件までしか返さないため、件数が多い範囲は細かく分けます
  （★数が同じものだけで 1,000 件を超えたら、作成日でさらに分けます）。
- 検索 API は 30 回/分までなので、リクエストの間隔を空けています。6.5 万件で 700〜800 回、30 分前後かかります。
- 取得には数十分かかり、その間にも★数は動きます。範囲の境目にいるリポジトリが取りこぼされることがありますが、ごく一部です。
- ★数が同じリポジトリは、ページをまたぐと並び順が揺れて取りこぼすことがあります。範囲の件数に足りなかったときは、
  作成日で分けて（1 回あたりのページを減らして）取り直します（警告を出します）。
- 2 次 rate limit や接続切れは、待って再試行します。
- 取れた件数が最初に数えた件数の 95% 未満のとき（GitHub の不調など）は、欠けたデータを残さないよう何も添付せずに失敗します。
  その日の分は欠けますが、翌日の実行で続きから記録されます。

## 手元で読む

```sh
scripts/sync_data.sh            # data/ に同期（daily は手元に無いものだけ、repos.parquet は毎回取り直す）
```

DuckDB の例:

```sql
-- 直近 7 日で★が増えた数の多い順
WITH d AS (SELECT * FROM read_parquet('data/daily-*.parquet')),
     latest AS (SELECT max(date) AS day FROM d)
SELECT r.full_name, r.language, cur.stargazers_count AS stars,
       cur.stargazers_count - prev.stargazers_count AS gain_7d
FROM d AS cur
JOIN d AS prev ON prev.id = cur.id AND prev.date = cur.date - 7
JOIN read_parquet('data/repos.parquet') AS r ON r.id = cur.id
WHERE cur.date = (SELECT day FROM latest)
ORDER BY gain_7d DESC
LIMIT 20;
```

ダウンロードせずに読むこともできます（添付ファイルの URL を DuckDB の `httpfs` で直接読む）:
`https://github.com/ot-nemoto/pinned-gist-maker/releases/download/data-2026-10/daily-2026-10-04.parquet`

## 今後の検討

- 分析のたびにダウンロードし直すのが重くなったり、ブラウザやほかのツールから直接読みたくなったりしたら、
  Cloudflare R2 に移す（ファイルの形はそのままで移せる）
- マスタの変更履歴（説明や topics がいつ変わったか）が必要になったら、3 つ目のテーブルとして追加する
