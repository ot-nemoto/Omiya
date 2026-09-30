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
| `scripts/growth.py` | 直近 7 日の★の伸び幅ランキングを作り、カテゴリごとの Gist を更新 |
| `.github/workflows/update-ranking.yml` | 毎日 JST 7:17 に ranking.py と growth.py を実行。手動実行も可 |
| `scripts/discover.py` | `frameworks.json` に無い新しいフレームワーク候補を探し、Issue で知らせる |
| `.github/workflows/discover-frameworks.yml` | 毎週月曜 JST 7:37 に実行。手動実行も可 |
| `scripts/history.py` | ★数の日次記録（`.state/stars.json`）の読み書き |
| `.state/stars.json` | 日ごとの★数の記録（直近 35 日分）。ranking.py が記録し、workflow が毎日 master にコミットする |
| `.state/last-run` | keepalive 用。毎日コミットし、60 日無活動による scheduled workflow の停止を防ぐ |

- ★数の取得は workflow 標準の `GITHUB_TOKEN` で行う
- Gist の更新には `gist` スコープの Classic PAT が必要 → [docs/SETUP.md](docs/SETUP.md)
- Pinned カードには先頭の数行しか出ないため、上位ほど上に並べている（Gist 本体には全件載る）
- 見出しに更新日時（JST）を入れている。★数の取得が一時的なエラー（再試行後も 5xx・429・通信エラー）で
  失敗したカテゴリは更新をスキップして前回の内容を残すため、日付が古ければ更新が止まっていると分かる
- 除外（見つからない・アーカイブ済み・更新停止）やスキップは Actions の実行結果に警告（warning）として表示される

## 対象の選び方

`frameworks.json` に載せる基準:

1. 一般に「Web フレームワーク」と呼ばれているもの。State of JS / Stack Overflow Survey に出てくるもの、
   または自ら Web（アプリ）フレームワークを名乗り、ランキングに入る程度の★があるもの（候補検知の Issue で
   見つかったものを含む）。ユーティリティや UI キット、モバイル専用のフレームワークは除く。React は慣例に従って含める
2. 本体が GitHub にあり、開発が続いているもの。アーカイブ済み・`STALE_DAYS`（既定 365 日。
   Repository variable で変更可、0 で無効）以上 push が無いリポジトリは実行時に自動で除外される
3. ★を数えるのは**本体のリポジトリ**（例: Vue は `vuejs/core`、Laravel は `laravel/framework`）。
   旧リポジトリや雛形リポジトリの★は含めない
4. Next.js / Nuxt などのメタフレームワークはフロントエンドに入れる
5. Remix（v2）は React Router v7 に統合されたため、`remix-run/react-router` を React Router として数える

追加・削除は `frameworks.json` を 1 行編集するだけです。リポジトリがリネームされても API のリダイレクトで追従します。

## ★の伸び幅ランキング

総数ランキングと同じフレームワークについて、直近 `GROWTH_DAYS`（既定 7）日の★の増加数で並べた表を
別の Gist に毎日書き込みます。

```
🚀 Frontend Framework ★ Growth 7d (2026-09-30 07:17)
1. Next.js      JavaScript ███████████ +720 +0.5%
2. React        JavaScript █████████   +610 +0.2%
3. Dioxus       Rust       ██████      +380 +1.0%
...
```

（数値はイメージ）

- 各行は「順位・名前・主要言語・伸びの横棒（1 位を基準）・★の増減・増加率」
- 伸び = 現在の★数 − 起点日の★数（純増。★を外した分も差し引く）。起点日の★数は、総数ランキングが
  毎日 `.state/stars.json` に記録した値を使う
- 起点日は `GROWTH_DAYS` 日前以前で最も新しい記録。運用開始直後など記録が足りないうちは最も古い記録を使い、
  見出しに実際の日数（例: `Growth 3d`）を出す。前日以前の記録が 1 つも無い日は更新しない
- 増加率は「伸び ÷ 起点日の★数」。起点日に★が 0 なら `new`
- 起点日の記録が無いリポジトリ（途中で `frameworks.json` に追加したもの）は、記録がたまるまで表示しない
- 除外条件（見つからない・アーカイブ済み・更新停止）や取得失敗時のスキップは総数ランキングと同じ

## 新しいフレームワークの検知

週 1 回、カテゴリごとの `discover_topics`（`frameworks.json`）の topic で GitHub を検索し、
次の条件をすべて満たすリポジトリを「候補」として Issue（ラベル `framework-candidate`）で知らせます。

- `frameworks.json` のどのカテゴリにも載っていない
- ★ がそのカテゴリのランキング最下位以上（＝追加すればランキングに入る）
- アーカイブ済みでなく、`STALE_DAYS` 日以内に push がある
- 名前・説明に awesome / boilerplate / template / starter / example / tutorial / admin / dashboard / ui-kit などを含まない
- topic に shadowsocks / v2ray / clash / trojan / gfw / vpn のいずれも付いていない
  （topic `ssr` は ShadowsocksR の意味でも使われるため、VPN 関連を弾く。`NOISE_TOPICS`）
- まだ Issue にしていない（Open / Closed とも）

1 回に作る Issue は★の多い順に最大 5 件（`MAX_ISSUES_PER_RUN`）で、残りは翌週に回ります。
既存 Issue とは本文に埋め込んだリポジトリ ID と名前で照合するため、ラベルやタイトルを編集しても、
候補のリポジトリがリネームされても再通知されません。掲載済みリポジトリがリネームされた場合も候補にはなりません。

Issue を見て判断します。

- **採用する**: Issue に書かれた 1 行を `frameworks.json` の `repos` に追加して Close。
  Issue の「該当カテゴリ」は検索に使った topic から機械的に決まるだけなので、追加先は上の基準で判断する
  （例: yew は `web-framework` 経由で backend と出るが、フロントエンドのフレームワーク）
- **採用しない**: Close するだけ。以後そのリポジトリは通知されない

topic を付けていないフレームワークは見つけられないため、完全な網羅ではなく「見落とし防止」の仕組みです。
拾いたい topic があれば `discover_topics` に足してください。

## ローカルで確認

```sh
python scripts/ranking.py --dry-run                                   # 実データ（GITHUB_TOKEN 推奨）
python scripts/ranking.py --dry-run --sample tests/sample_repos.json  # ダミーデータ
python scripts/growth.py --dry-run                                    # 伸び幅（.state/stars.json が必要）
python scripts/discover.py --dry-run                                  # 候補の検索だけ（Issue は作らない）
python -m unittest discover -s tests
```
