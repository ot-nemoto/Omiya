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

設定は不要です。毎日の workflow が次の 2 種類の★数を記録し、github-actions[bot] 名義で master に直接コミットします
（PR は通しません。記録は無制限に保持）。

- `.state/stars.json`: `frameworks.json` に載っているフレームワーク（総数ランキングで取得した値）
- `.state/rising.json` / `.state/rising-repos.json`: 新進気鋭の候補（Rising）。README の「Rising 候補の記録」参照

master にブランチ保護（PR 必須など）を設定すると、このコミットが失敗するので注意してください。

## 6. 新しいフレームワークの検知

追加の設定は不要です（workflow 標準の `GITHUB_TOKEN` に `issues: write` を付けている）。

1. **Actions** タブ → *Discover new framework candidates* → **Run workflow** で初回の候補を確認
   （入力 `max_issues` で 1 回に作る Issue の上限を変えられる。既定 5）
2. 作られた Issue（ラベル `framework-candidate`）を見て、採用するなら `frameworks.json` に追加、不要なら Close

## トラブルシューティング

| 症状 | 原因 |
|---|---|
| `Gist API エラー 403/404`（ジョブが失敗する） | PAT の `gist` スコープ不足・期限切れ、または Gist ID の誤り |
| 警告 `... が見つからないため除外` | `frameworks.json` のリポジトリ名の誤り、または削除された |
| 警告 `Rising: topic:… の検索に失敗したためスキップ` | GitHub 検索 API の一時的な障害や rate limit。その topic の候補はその日だけ記録されない |
| *Commit state* ステップで push が失敗する | master のブランチ保護で bot の直接 push が拒否されている |
| 警告 `★数を取得できなかったため今回の更新をスキップ` | GitHub API の一時的な障害。次回の実行で自動的に回復する（見出しの日付は前回のまま） |
| `Issue API エラー 403` | Organization / Enterprise のポリシーで Actions からの書き込みが制限されている |
| `Issue API エラー 410` | リポジトリの Issues 機能が無効（Settings → General → Features で有効にする） |
| `検索クエリの誤り`（ジョブが失敗する） | `frameworks.json` の `discover_topics` / `discover_phrases` の書式誤り |
| 警告 `… に見出し「…」が見つかりません` | awesome リストの構成が変わった。`frameworks.json` の `discover_awesome` の `section`（や `path`）を直す |
| 警告 `… を取得できなかったためスキップ` / `awesome リストの残りを打ち切ります` | GitHub の一時的な障害。翌週の実行で自動的に回復する |
| `MAX_ISSUES には 1 以上の整数を指定してください`（ジョブが失敗する） | 手動実行の入力 `max_issues` に 0 以下や数値でない値を入れた |
| 警告 `候補を検索できなかったため今回はスキップ` | GitHub API の一時的な障害。翌週の実行で自動的に回復する |
| workflow が動かない | 60 日無活動で停止。Actions タブで *Enable workflow*（keepalive で通常は防げる） |
| 実行が数十分遅れる | Actions の cron は遅延することがある（仕様） |
