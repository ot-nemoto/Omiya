# Pinned Gist Maker — フレームワーク★ランキング

GitHub プロフィールに Pin した Gist に、フロントエンド / バックエンドのフレームワークの
GitHub ★数ランキングを毎日表示する仕組みです。

```
🏆 Frontend Framework ★ Ranking (2026-09-29)
 1. React      ★232.0k
 2. Next.js    ★131.0k
 3. Angular    ★ 97.0k
 ...
```

（数値はイメージ）

## 仕組み

| ファイル | 役割 |
|---|---|
| `frameworks.json` | カテゴリごとの対象フレームワークと、★を数えるリポジトリの一覧 |
| `scripts/ranking.py` | ★数を取得して並べ替え、カテゴリごとの Gist を `PATCH /gists/{id}` で更新（内容が同じなら何もしない。標準ライブラリのみ） |
| `.github/workflows/update-ranking.yml` | 毎日 JST 7:17 に実行。手動実行も可 |
| `.state/last-run` | keepalive 用。1 日 1 回コミットし、60 日無活動による scheduled workflow の停止を防ぐ |

- ★数の取得は workflow 標準の `GITHUB_TOKEN` で行う
- Gist の更新には `gist` スコープの Classic PAT が必要 → [docs/SETUP.md](docs/SETUP.md)
- Pinned カードには先頭の数行しか出ないため、上位ほど上に並べている（Gist 本体には全件載る）

## 対象の選び方

`frameworks.json` に載せる基準:

1. 一般に「Web フレームワーク」と呼ばれているもの（State of JS / Stack Overflow Survey に出てくるもの）。
   ユーティリティや UI キットは除く。React は慣例に従って含める
2. 本体が GitHub にあり、開発が続いているもの。アーカイブ済み・`STALE_DAYS`（既定 365 日）以上
   push が無いリポジトリは実行時に自動で除外される
3. ★を数えるのは**本体のリポジトリ**（例: Vue は `vuejs/core`、Laravel は `laravel/framework`）
4. Next.js / Nuxt などのメタフレームワークはフロントエンドに入れる

追加・削除は `frameworks.json` を 1 行編集するだけです。リポジトリがリネームされても API のリダイレクトで追従します。

## ローカルで確認

```sh
python scripts/ranking.py --dry-run                                   # 実データ（GITHUB_TOKEN 推奨）
python scripts/ranking.py --dry-run --sample tests/sample_repos.json  # ダミーデータ
python -m unittest discover -s tests
```
