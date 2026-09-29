# セットアップ手順

## 1. Fine-grained PAT を作る

Description（リポジトリ設定）の変更には Administration 権限が必要で、標準の `GITHUB_TOKEN` では足りません。

1. GitHub → 右上アイコン → **Settings** → **Developer settings** → **Personal access tokens** → **Fine-grained tokens** → **Generate new token**
2. Token name: `omiya-description`、Expiration: 任意（最長 1 年。切れる前に更新が必要）
3. Resource owner: 自分のユーザー
4. **Repository access** → *Only select repositories* → Description を書き換えるリポジトリ（このリポジトリ）だけを選ぶ
5. **Permissions** → Repository permissions → **Administration: Read and write**（Metadata: Read-only は自動で付く）
6. **Generate token** し、表示されたトークンをコピー（再表示されません）

## 2. Secrets に登録する

1. このリポジトリ → **Settings** → **Secrets and variables** → **Actions** → **New repository secret**
2. Name: `DESCRIPTION_PAT`、Secret: コピーしたトークン

## 3. 動作確認

1. **Actions** タブ → *Update description (Omiya weather)* → **Run workflow**
2. 成功するとリポジトリトップの About 欄が更新される
3. プロフィールの **Customize your pins** でこのリポジトリを Pin する

ローカルで表示だけ確認: `python scripts/update_description.py --dry-run`

## 4. （任意）プロフィール README に週間予報 SVG を出す

1. `<USERNAME>/<USERNAME>` リポジトリを用意（無ければ public で作成）
2. `profile-readme/update-weather-svg.yml` を `.github/workflows/` にコピーし、`<USERNAME>` と `<OMIYA_REPO>` を置換（このリポジトリが private の場合は checkout に PAT が必要）
3. `profile-readme/README-snippet.md` の `<picture>` を README.md に貼る
4. Actions から一度 **Run workflow** して `assets/weather-*.svg` を生成

## 5. （任意）Pinned Gist で複数行表示する

Pinned カードには Gist ファイルの先頭数行が表示されるため、改行が使えます。

1. https://gist.github.com で **public** Gist を作成（ファイル名 `omiya-weather.txt`、中身は適当な 1 行でよい）
2. URL 末尾の英数字（`https://gist.github.com/<user>/<GIST_ID>`）を控える
3. **Classic PAT** を作成: Settings → Developer settings → Personal access tokens → **Tokens (classic)** → スコープは **`gist`** のみ（Gist は Fine-grained PAT 非対応）
4. このリポジトリの Settings → Secrets and variables → Actions で
   - Secret `GIST_PAT` = Classic PAT
   - Variables タブに `GIST_ID` = Gist の ID
5. Actions から **Run workflow**。プロフィールの **Customize your pins** で Gist を Pin する

`GIST_ID` を設定しなければ Gist の更新は自動でスキップされます。
ローカル確認: `python scripts/update_gist.py --dry-run`

## トラブルシューティング

| 症状 | 原因 |
|---|---|
| `GitHub API エラー 403/404` | PAT の対象リポジトリ or Administration 権限が不足、または期限切れ |
| workflow が動かない | 60 日無活動で停止。Actions タブで *Enable workflow*（keepalive で通常は防げる） |
| 実行が数十分遅れる | Actions の cron は遅延することがある（仕様） |
