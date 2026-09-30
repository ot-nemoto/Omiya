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

## トラブルシューティング

| 症状 | 原因 |
|---|---|
| `Gist API エラー 403/404`（ジョブが失敗する） | PAT の `gist` スコープ不足・期限切れ、または Gist ID の誤り |
| 警告 `... が見つからないため除外` | `frameworks.json` のリポジトリ名の誤り、または削除された |
| 警告 `★数を取得できなかったため今回の更新をスキップ` | GitHub API の一時的な障害。次回の実行で自動的に回復する（見出しの日付は前回のまま） |
| workflow が動かない | 60 日無活動で停止。Actions タブで *Enable workflow*（keepalive で通常は防げる） |
| 実行が数十分遅れる | Actions の cron は遅延することがある（仕様） |
