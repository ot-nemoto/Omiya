# Pinned Gist Maker — フレームワーク★ランキング

GitHub プロフィールに Pin した Gist に、フロントエンド / バックエンドのフレームワークの
GitHub ★数ランキングを毎日表示する仕組みです。

```
🏆 Frontend Framework ★ Ranking (2026-09-30 10:16)
 1. React        JavaScript ██████████████ 250.8k
 2. Next.js      JavaScript ████████       142.9k
 3. Angular      TypeScript ██████         101.0k
 ...
```

- 各行は「順位・名前・主要言語・★数の横棒（1 位を基準）・★数」
- 主要言語は GitHub API の `language`（リポジトリで最も多い言語）。実態と違う場合は
  `frameworks.json` の各項目に `"language": "TypeScript"` のように書くと上書きできる
- 見出しの日時は JST
- Pinned カードは 1 行 55 桁前後で切れるため、見出し以外の行は `LINE_MAX`（49 桁）以内に収める。
  名前や言語名が長くて収まらないときは棒を短くし（最短 `BAR_MIN`）、言語名は `LANG_MAX`（10 桁）で切り詰める

## 仕組み

| ファイル | 役割 |
|---|---|
| `frameworks.json` | カテゴリごとの対象フレームワークと、★を数えるリポジトリの一覧 |
| `scripts/ranking.py` | ★数を取得して並べ替え、カテゴリごとの Gist を `PATCH /gists/{id}` で更新（標準ライブラリのみ） |
| `.github/workflows/update-ranking.yml` | 毎日 JST 7:17 に実行。手動実行も可 |
| `.state/last-run` | keepalive 用。1 日 1 回コミットし、60 日無活動による scheduled workflow の停止を防ぐ |

- ★数の取得は workflow 標準の `GITHUB_TOKEN` で行う
- Gist の更新には `gist` スコープの Classic PAT が必要 → [docs/SETUP.md](docs/SETUP.md)
- Pinned カードには先頭の数行しか出ないため、上位ほど上に並べている（Gist 本体には全件載る）
- 見出しに更新日時（JST）を入れている。★数の取得が一時的なエラー（再試行後も 5xx・429・通信エラー）で
  失敗したカテゴリは更新をスキップして前回の内容を残すため、日付が古ければ更新が止まっていると分かる
- 除外（見つからない・アーカイブ済み・更新停止）やスキップは Actions の実行結果に警告（warning）として表示される

## 対象の選び方

`frameworks.json` に載せる基準:

1. 一般に「Web フレームワーク」と呼ばれているもの（State of JS / Stack Overflow Survey に出てくるもの）。
   ユーティリティや UI キットは除く。React は慣例に従って含める
2. 本体が GitHub にあり、開発が続いているもの。アーカイブ済み・`STALE_DAYS`（既定 365 日。
   Repository variable で変更可、0 で無効）以上 push が無いリポジトリは実行時に自動で除外される
3. ★を数えるのは**本体のリポジトリ**（例: Vue は `vuejs/core`、Laravel は `laravel/framework`）。
   旧リポジトリや雛形リポジトリの★は含めない
5. Remix（v2）は React Router v7 に統合されたため、`remix-run/react-router` を React Router として数える
4. Next.js / Nuxt などのメタフレームワークはフロントエンドに入れる

追加・削除は `frameworks.json` を 1 行編集するだけです。リポジトリがリネームされても API のリダイレクトで追従します。

## ローカルで確認

```sh
python scripts/ranking.py --dry-run                                   # 実データ（GITHUB_TOKEN 推奨）
python scripts/ranking.py --dry-run --sample tests/sample_repos.json  # ダミーデータ
python -m unittest discover -s tests
```
