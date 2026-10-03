# セットアップ手順

## 1. Gist を 2 つ作る

1. https://gist.github.com で **public** Gist を作成（中身は適当な 1 行でよい）
   - frontend 用と backend 用で 2 つ作る
   - ファイルは **1 つだけ**にする。ファイル名は何でもよく、初回実行時に `frontend-framework-ranking.txt` などへ自動でリネームされる
     （Pinned カードには名前順で先頭のファイルが表示されるため、ファイルが複数あると別のファイルが出ることがある）
2. それぞれの URL 末尾の英数字（`https://gist.github.com/<user>/<GIST_ID>`）を控える

## 2. Classic PAT を作る

Gist は Fine-grained PAT に対応していないため Classic PAT を使います。

1. GitHub → Settings → Developer settings → Personal access tokens → **Tokens (classic)** → Generate new token
2. スコープは **`gist`** のみ。Expiration は任意（切れる前に更新が必要）

## 3. Secrets / Variables に登録する

このリポジトリ → **Settings** → **Secrets and variables** → **Actions**

| 種類 | 名前 | 値 |
|---|---|---|
| Secret | `GIST_PAT` | 手順 2 の Classic PAT |
| Variable | `GIST_ID_FRONTEND` | frontend 用 Gist の ID |
| Variable | `GIST_ID_BACKEND` | backend 用 Gist の ID |

Variable が未設定のカテゴリは更新がスキップされます（片方だけでも動きます）。

任意で Variable `STALE_DAYS`（既定 365）を設定すると、何日 push が無いリポジトリを除外するかを変えられます（0 で無効）。

## 4. 動作確認と Pin

1. **Actions** タブ → *Update framework ranking gists* → **Run workflow**
2. Gist が更新されたら、プロフィールの **Customize your pins** で 2 つの Gist を Pin する

## 5. ★数の記録（自動）

設定は不要です。毎日の workflow が `frameworks.json` に載っているフレームワークの★数（総数ランキングで取得した値）を
`.state/stars.json` に記録し、github-actions[bot] 名義で master に直接コミットします（PR は通しません。記録は無制限に保持）。

master にブランチ保護（PR 必須など）を設定すると、このコミットが失敗するので注意してください。

## 6. 新しいフレームワークの検知

追加の設定は不要です（workflow 標準の `GITHUB_TOKEN` に `issues: write` を付けている）。

1. **Actions** タブ → *Discover new framework candidates* → **Run workflow** で初回の候補を確認
   （入力 `max_issues` で 1 回に作る Issue の上限を変えられる。既定 5）
2. 作られた Issue（ラベル `framework-candidate`）を見て、採用するなら `frameworks.json` に追加、不要なら Close

## 7. GitHub 全体の★数データの収集

追加の設定は不要です（workflow 標準の `GITHUB_TOKEN` に `contents: write` を付け、Releases にデータを添付する）。

1. **Actions** タブ → *Collect GitHub star data* → **Run workflow** で初回を実行（30 分前後かかる）
2. **Releases** に `data-YYYY-MM`（その月の日次データ）と `data-latest`（`repos.parquet`）ができていることを確認。
   どちらも「Latest release」にはならない
3. 以後は毎日 JST 3:37 に自動で実行される。手元で読むときは `scripts/sync_data.sh` で同期する（[RELEASE_DATA.md](RELEASE_DATA.md)）

## トラブルシューティング

| 症状 | 原因 |
|---|---|
| `Gist API エラー 403/404`（ジョブが失敗する） | PAT の `gist` スコープ不足・期限切れ、または Gist ID の誤り |
| 警告 `... が見つからないため除外` | `frameworks.json` のリポジトリ名の誤り、または削除された |
| *Commit state* ステップで push が失敗する | master のブランチ保護で bot の直接 push が拒否されている |
| 警告 `★数を取得できなかったため今回の更新をスキップ` | GitHub API の一時的な障害。次回の実行で自動的に回復する（見出しの日付は前回のまま） |
| `Issue API エラー 403` | Organization / Enterprise のポリシーで Actions からの書き込みが制限されている |
| `Issue API エラー 410` | リポジトリの Issues 機能が無効（Settings → General → Features で有効にする） |
| `検索クエリの誤り`（ジョブが失敗する） | `frameworks.json` の `discover_topics` / `discover_phrases` の書式誤り |
| 警告 `… に見出し「…」が見つかりません` | awesome リストの構成が変わった。`frameworks.json` の `discover_awesome` の `section`（や `path`）を直す |
| 警告 `… を取得できなかったためスキップ` / `awesome リストの残りを打ち切ります` | GitHub の一時的な障害。翌週の実行で自動的に回復する |
| `MAX_ISSUES には 1 以上の整数を指定してください`（ジョブが失敗する） | 手動実行の入力 `max_issues` に 0 以下や数値でない値を入れた |
| 警告 `候補を検索できなかったため今回はスキップ` | GitHub API の一時的な障害。翌週の実行で自動的に回復する |
| *Collect GitHub star data* が `取れた件数が対象の 95% 未満` / `検索に失敗した` で失敗する | GitHub の一時的な障害。その日の分は添付されない（欠ける）。翌日の実行で続きから記録される。すぐ取り直したいなら手動実行する |
| *Collect GitHub star data* が `data-latest に repos.parquet がありません` で失敗する | 前回の上書きの途中で失敗した。その月の `repos-YYYY-MM.parquet` を `repos.parquet` として `data-latest` に添付し直して再実行する（[RELEASE_DATA.md](RELEASE_DATA.md)）。作り直してよければ手動実行で `fresh` を指定 |
| *Collect GitHub star data* がタイムアウトする | 対象の件数が増えた。`collect-stars.yml` の `timeout-minutes` を延ばす |
| workflow が動かない | 60 日無活動で停止。Actions タブで *Enable workflow*（keepalive で通常は防げる） |
| 実行が数十分遅れる | Actions の cron は遅延することがある（仕様） |
