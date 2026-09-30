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

## 5. （任意）★の伸び幅ランキング

1. 手順 1 と同じ要領で public Gist をさらに 2 つ作る（frontend 用・backend 用。ファイルは 1 つだけ）
2. Variables に登録する
   | 名前 | 値 |
   |---|---|
   | `GIST_ID_FRONTEND_GROWTH` | frontend の伸び幅用 Gist の ID |
   | `GIST_ID_BACKEND_GROWTH` | backend の伸び幅用 Gist の ID |
3. Actions → *Update framework ranking gists* → **Run workflow** で確認し、2 つの Gist を Pin する

`GIST_PAT` は総数ランキングと共通です。任意で Variable `GROWTH_DAYS`（既定 7）で期間を変えられます。

伸び幅は、総数ランキングが毎日 `.state/stars.json` に記録する★数との差で出します。
記録は workflow が github-actions[bot] 名義で master に直接コミットします（PR は通しません）。
運用開始の翌日から表示され、7 日分たまるまでは見出しの日数（`Growth 1d` など）が実際の期間を表します。
master にブランチ保護（PR 必須など）を設定すると、このコミットが失敗するので注意してください。
Variable が未設定のカテゴリはスキップされます。

## 6. 新しいフレームワークの検知

追加の設定は不要です（workflow 標準の `GITHUB_TOKEN` に `issues: write` を付けている）。

1. **Actions** タブ → *Discover new framework candidates* → **Run workflow** で初回の候補を確認
2. 作られた Issue（ラベル `framework-candidate`）を見て、採用するなら `frameworks.json` に追加、不要なら Close

## トラブルシューティング

| 症状 | 原因 |
|---|---|
| `Gist API エラー 403/404`（ジョブが失敗する） | PAT の `gist` スコープ不足・期限切れ、または Gist ID の誤り |
| 警告 `... が見つからないため除外` | `frameworks.json` のリポジトリ名の誤り、または削除された |
| 警告 `★数の記録がまだ 1 日分も無い…` | 運用開始日。翌日の実行から伸び幅が表示される |
| *Commit state* ステップで push が失敗する | master のブランチ保護で bot の直接 push が拒否されている |
| 警告 `★数を取得できなかったため今回の更新をスキップ` | GitHub API の一時的な障害。次回の実行で自動的に回復する（見出しの日付は前回のまま） |
| `Issue API エラー 403` | Organization / Enterprise のポリシーで Actions からの書き込みが制限されている |
| `Issue API エラー 410` | リポジトリの Issues 機能が無効（Settings → General → Features で有効にする） |
| `検索クエリの誤り`（ジョブが失敗する） | `frameworks.json` の `discover_topics` の書式誤り |
| 警告 `候補を検索できなかったため今回はスキップ` | GitHub API の一時的な障害。翌週の実行で自動的に回復する |
| workflow が動かない | 60 日無活動で停止。Actions タブで *Enable workflow*（keepalive で通常は防げる） |
| 実行が数十分遅れる | Actions の cron は遅延することがある（仕様） |
