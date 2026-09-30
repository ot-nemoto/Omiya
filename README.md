# Pinned Gist Maker

GitHub プロフィールに Pin した Gist の中身を、GitHub Actions の定期実行で生成・更新する仕組みです。
ネタ（Pin に載せる内容）ごとにスクリプトと workflow を持ち、今後ネタを追加していく想定です。

## ネタ一覧

| ネタ | Pin する Gist | 更新 | 説明 |
|---|---|---|---|
| [フレームワーク★ランキング](#フレームワークランキング) | frontend / backend の 2 つ | 毎日 JST 7:17 | Web フレームワークの GitHub ★数ランキング。新しいフレームワークの検知と、新進気鋭の候補（Rising）の★数の記録も行う |

## 共通の仕組み

- workflow・スクリプト・ファイルの関係と、各ファイルの使い道は [docs/DATA_FLOW.md](docs/DATA_FLOW.md) の図を参照
- セットアップ（Gist・PAT・Secrets / Variables）は [docs/SETUP.md](docs/SETUP.md) を参照
- Gist の更新には `gist` スコープの Classic PAT（Secret `GIST_PAT`）を使う。Gist ごとの ID は Repository variable で渡す
- Pinned カードには Gist の**名前順で先頭のファイル**の、先頭 5 行ほどしか出ず、1 行 55 桁前後で切れる。
  各ネタはこの範囲に収まるように出力する（Gist のファイルは 1 つだけにする）
- 記録用のデータは `.state/` に置き、workflow の最後に github-actions[bot] 名義で master に直接コミットする（PR は通さない）
- `.state/last-run` は keepalive 用。毎日コミットし、60 日無活動による scheduled workflow の停止を防ぐ
- 標準ライブラリのみで動く（Python 3.12）

### ネタを追加するとき

1. `scripts/` にスクリプトを追加する（Gist の更新は `ranking.update_gist` を使い回せる）
2. 毎日の `.github/workflows/update-ranking.yml` にステップを足すか、別の workflow を作る
3. public Gist を作り、ID を Repository variable に登録して Pin する
4. この README の「ネタ一覧」と、ネタごとの節を追加する

---

## フレームワーク★ランキング

フロントエンド / バックエンドの Web フレームワークの GitHub ★数ランキングを、それぞれの Pinned Gist に毎日表示します。

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
- 見出し以外の行は `LINE_MAX`（49 桁）以内に収める。名前や言語名が長くて収まらないときは棒を短くし
  （最短 `BAR_MIN`）、言語名は `LANG_MAX`（10 桁）で切り詰める

### 仕組み

| ファイル | 役割 |
|---|---|
| `frameworks.json` | カテゴリごとの対象フレームワークと、★を数えるリポジトリの一覧 |
| `scripts/ranking.py` | ★数を取得して並べ替え、カテゴリごとの Gist を `PATCH /gists/{id}` で更新（標準ライブラリのみ） |
| `scripts/rising.py` | 新進気鋭のフレームワーク候補（Rising）を探して★数を記録する（表示はまだしない） |
| `.github/workflows/update-ranking.yml` | 毎日 JST 7:17 に ranking.py と rising.py を実行し、記録をコミット。手動実行も可 |
| `scripts/discover.py` | `frameworks.json` に無い新しいフレームワーク候補を探し、Issue で知らせる |
| `.github/workflows/discover-frameworks.yml` | 毎週月曜 JST 7:37 に実行。手動実行も可 |
| `scripts/history.py` | ★数の日次記録（`.state/stars.json`）の読み書き |
| `.state/stars.json` | 掲載中のフレームワークの日ごとの★数（無制限に保持）。ranking.py が記録し、workflow が毎日 master にコミットする |
| `.state/rising.json` / `rising-repos.json` | Rising 候補の日ごとの★数と、言語・作成日・説明などの情報（無制限に保持） |

- ★数の取得は workflow 標準の `GITHUB_TOKEN` で行う
- Pinned カードには先頭の数行しか出ないため、上位ほど上に並べている（Gist 本体には全件載る）
- 見出しに更新日時（JST）を入れている。★数の取得が一時的なエラー（再試行後も 5xx・429・通信エラー）で
  失敗したカテゴリは更新をスキップして前回の内容を残すため、日付が古ければ更新が止まっていると分かる
- 除外（見つからない・アーカイブ済み・更新停止）やスキップは Actions の実行結果に警告（warning）として表示される

### 対象の選び方

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

### Rising 候補の記録

`frameworks.json` に載る前の、新進気鋭のフレームワークを早い段階から追うために、候補の★数を毎日記録しています。
今は**記録するだけ**で、ランキングなどの表示はデータがたまってから決めます。

- 検索は全カテゴリの `discover_topics` で行い、frontend / backend の区別はしない（新しいリポジトリは機械的に判別しにくいため）
- 条件: ★1,000 以上・作成から 2 年以内・90 日以内に push あり・アーカイブ済みやフォークでない
  （`scripts/rising.py` の `MIN_STARS` / `MAX_AGE_DAYS` / `ACTIVE_DAYS`）
- `frameworks.json` に載っているものと、候補検知と同じノイズ条件（名前・説明のキーワード、VPN 系 topic）に当たるものは除く
- `.state/rising.json` に★数を、`.state/rising-repos.json` に言語・作成日・説明・topics・初めて見つかった日などを残す
- 検索 API は 30 回/分までなので、リクエストの間隔を空けている。topic ごとの検索に失敗したら、その topic だけその日は飛ばす

### 新しいフレームワークの検知

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
python scripts/rising.py --dry-run                                    # Rising 候補の検索だけ（記録しない）
python scripts/discover.py --dry-run                                  # 候補の検索だけ（Issue は作らない）
python -m unittest discover -s tests
```
