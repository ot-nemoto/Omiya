# Pinned Gist Maker

GitHub プロフィールに Pin した Gist の中身を、GitHub Actions の定期実行で生成・更新する仕組みです。
ネタ（Pin に載せる内容）ごとにスクリプト（必要に応じて workflow）を持ち、今後ネタを追加していく想定です。

## ネタ一覧

| ネタ | Pin する Gist | 更新 | 説明 |
|---|---|---|---|
| [フレームワーク★ランキング](#フレームワークランキング) | frontend / backend の 2 つ | 毎日 JST 7:17（候補検知は毎週月曜 7:37） | Web フレームワークの GitHub ★数ランキング。新しいフレームワークの検知も行う |

Pin には出しませんが、あわせて [GitHub 全体の★数データ](#github-全体の数データ) も毎日記録しています（今後のネタの元データ）。

## 共通の仕組み

- workflow・スクリプト・ファイルの関係と、各ファイルの使い道は [docs/DATA_FLOW.md](docs/DATA_FLOW.md) の図を参照
- `.state/` 配下のファイルの JSON 構成と項目の意味は [docs/STATE_FORMAT.md](docs/STATE_FORMAT.md) を参照
- GitHub Releases に置く★数データの列と読み方は [docs/RELEASE_DATA.md](docs/RELEASE_DATA.md) を参照
- セットアップ（Gist・PAT・Secrets / Variables）は [docs/SETUP.md](docs/SETUP.md) を参照
  （どちらも現状はフレームワーク★ランキングの内容。ネタを追加したら追記する）
- Gist の更新には `gist` スコープの Classic PAT（Secret `GIST_PAT`）を使う。Gist ごとの ID は Repository variable で渡す
- Pinned カードには Gist の**名前順で先頭のファイル**の、先頭 5 行（見出し + 4 行）ほどしか出ず、1 行 55 桁前後で切れる。
  各ネタはこの範囲に収まるように出力する（Gist のファイルは 1 つだけにする）
- 記録用のデータは `.state/` に置き、workflow の最後に github-actions[bot] 名義で master に直接コミットする（PR は通さない）
- `.state/last-run` は keepalive 用。毎日コミットし、60 日無活動による scheduled workflow の停止を防ぐ
- 標準ライブラリのみで動く（Python 3.12）。★数データの収集（`scripts/collect.py`）だけは Parquet の書き出しに `pyarrow` を使う
  （その workflow でだけインストールする。テストは `pyarrow` が無ければ該当部分を飛ばす）

## テスト

```sh
python -m unittest discover -s tests
```

## ネタを追加するとき

1. `scripts/` にスクリプトを、`tests/` にテストを追加する（Gist の更新は `ranking.update_gist` を使い回せる）。
   workflow の最初の Test ステップが `tests/` をすべて実行する
2. workflow に組み込む
   - 毎日の `.github/workflows/update-ranking.yml` にステップを足す場合は、
     `if: ${{ !cancelled() && steps.test.outcome == 'success' }}` を付け、他のネタの失敗に巻き込まれないようにする
   - `.state/` に記録を書く場合は、Commit state ステップのコミット対象（`git add` と `git diff --cached --quiet -- ...`）に追加する
   - 別の workflow を作る場合は、`.state/` に書くなら `permissions: contents: write` とコミットのステップも用意する
3. public Gist を作り（ファイルは 1 つ）、ID を Repository variable に登録して Pin する
4. ドキュメントを更新する: この README の「ネタ一覧」とネタごとの節、docs/SETUP.md（Gist・Variable）、
   docs/DATA_FLOW.md（図・ファイルの表）、`.state/` に書く場合は docs/STATE_FORMAT.md（データ形式）

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
- Pinned カードの 1 行 55 桁前後の制限に収めるため、見出し以外の行は `LINE_MAX`（49 桁）以内にする。名前や言語名が長くて収まらないときは棒を短くし
  （最短 `BAR_MIN`）、言語名は `LANG_MAX`（10 桁）で切り詰める

### 仕組み

| ファイル | 役割 |
|---|---|
| `frameworks.json` | カテゴリごとの対象フレームワークと、★を数えるリポジトリの一覧 |
| `scripts/ranking.py` | ★数を取得して並べ替え、カテゴリごとの Gist を `PATCH /gists/{id}` で更新 |
| `.github/workflows/update-ranking.yml` | 毎日 JST 7:17 に ranking.py を実行し、記録をコミット。手動実行も可 |
| `scripts/discover.py` | `frameworks.json` に無い新しいフレームワーク候補を探し、Issue で知らせる |
| `.github/workflows/discover-frameworks.yml` | 毎週月曜 JST 7:37 に実行。手動実行も可 |
| `scripts/history.py` | ★数の日次記録（`.state/stars.json`）の読み書き |
| `.state/stars.json` | 掲載中のフレームワークの日ごとの★数（無制限に保持）。ranking.py が記録し、workflow が毎日 master にコミットする |

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

### 新しいフレームワークの検知

週 1 回、`frameworks.json` のカテゴリごとに次の 3 つの方法で候補を集め、
条件をすべて満たすリポジトリを「候補」として Issue（ラベル `framework-candidate`）で知らせます。

| 方法 | 設定 | 拾えるもの |
|---|---|---|
| topic で検索 | `discover_topics` | `web-framework` などの topic を付けているもの |
| 説明文のキーワードで検索 | `discover_phrases`（例: `"php framework"`） | topic を付けていない定番（Symfony、Gatsby など） |
| awesome リストの節 | `discover_awesome`（例: awesome-go の「Web Frameworks」） | 説明文にも手がかりがない定番（Koa、Beego など）。README を raw.githubusercontent.com から読む |

awesome リストは Go / Python / Node.js / Rust / Elixir / JavaScript のものを使っています
（PHP・Java・Ruby の awesome リストは公式サイトへのリンクが中心、または定番が載っていないため対象外。PHP はキーワード検索で補う）。
リストの見出しが変わって節が見つからない場合は警告を出してその 1 件を飛ばします。
リストに載っているリポジトリの情報取得が 3 回続けて失敗したら（GitHub の不調）、awesome リストの残りはその回だけ打ち切ります。

条件:

- `frameworks.json` のどのカテゴリにも載っていない
- ★ がそのカテゴリのランキング最下位以上（＝追加すればランキングに入る）
- アーカイブ済みでなく、`STALE_DAYS` 日以内に push がある
- 名前・説明に awesome / boilerplate / template / starter / example / tutorial / admin panel・admin UI・名前の `-admin` / dashboard / ui-kit などを含まない
- topic に shadowsocks / v2ray / clash / trojan / gfw / vpn / css-framework / game-engine / blockchain のいずれも付いていない
  （topic `ssr` は ShadowsocksR の意味でも使われるため VPN 関連を、キーワード検索で混ざりやすい CSS フレームワーク・ゲームエンジン・ブロックチェーンを弾く。`NOISE_TOPICS`）
- まだ Issue にしていない（Open / Closed とも）

1 回に作る Issue は★の多い順に最大 5 件（`MAX_ISSUES_PER_RUN`）で、残りは翌週に回ります。
手動実行（Run workflow）では入力 `max_issues`（1 以上）で上限を変えられます（初回にまとめて消化したいときなど）。
Issue には「見つけた方法」（topic・キーワード・awesome リスト）も書かれます。
既存 Issue とは本文に埋め込んだリポジトリ ID と名前で照合するため、ラベルやタイトルを編集しても、
候補のリポジトリがリネームされても再通知されません。掲載済みリポジトリがリネームされた場合も候補にはなりません。

Issue を見て判断します。

- **採用する**: Issue に書かれた 1 行を `frameworks.json` の `repos` に追加して Close。
  Issue の「該当カテゴリ」は見つけた方法（topic・キーワード・awesome リストの節）がどのカテゴリの設定かで機械的に決まるだけなので、追加先は上の基準で判断する
  （例: yew は `web-framework` 経由で backend と出るが、フロントエンドのフレームワーク）
- **採用しない**: Close するだけ。以後そのリポジトリは通知されない

3 つの方法のどれにも引っかからないもの（topic が無く、説明文にキーワードが無く、使っている awesome リストにも載っていない）は見つけられないため、
完全な網羅ではなく「見落とし防止」の仕組みです。漏れに気づいたら、そのフレームワークに合う topic を `discover_topics` に、
説明文のキーワードを `discover_phrases` に、awesome リストの節を `discover_awesome` に足してください。
モバイル向け（React Native など）のように対象外のものが混ざることもあるので、その場合は Issue を Close してください。

### ローカルで確認

```sh
python scripts/ranking.py --dry-run                                   # 実データ（GITHUB_TOKEN 推奨）
python scripts/ranking.py --dry-run --sample tests/sample_repos.json  # ダミーデータ
python scripts/discover.py --dry-run                                  # 候補の検索だけ（Issue は作らない）
```

---

## GitHub 全体の★数データ

★500 以上・1 年以内に push があるリポジトリ全体（2026-10 時点で約 6.5 万件、アーカイブ済み・フォークを含む）の★数などを毎日記録しています。
今は**記録するだけ**で、伸びの大きいリポジトリのランキングなど、Pin に出すネタはデータがたまってから決めます。

- データはリポジトリにコミットせず、GitHub Releases に Parquet 形式で添付する（毎日 1 ファイル。1 年で 250〜400MB 程度の見込み）
- 列・置き場所・読み方（DuckDB の例）は [docs/RELEASE_DATA.md](docs/RELEASE_DATA.md) を参照

| ファイル | 役割 |
|---|---|
| `scripts/collect.py` | 検索 API で対象を全件集め、`daily-YYYY-MM-DD.parquet`（その日の数値）と `repos.parquet`（リポジトリ情報のマスタ）を書き出す |
| `.github/workflows/collect-stars.yml` | 毎日 JST 3:37 に collect.py を実行し、Releases に添付する（`data-YYYY-MM` に日次、`data-latest` にマスタ）。手動実行も可 |
| `scripts/sync_data.sh` | Releases のデータを手元の `data/` に同期する（`gh` が必要） |

- 検索 API は 1 つの検索で 1,000 件までなので、★数の範囲で区切って取る。30 回/分の制限があり、1 回 30 分前後かかる
- 取れた件数が対象の 95% 未満のとき（GitHub の不調など）は、何も添付せずに失敗する（その日の分は欠ける）

```sh
python scripts/collect.py --dry-run                             # 対象の件数を数えるだけ（GITHUB_TOKEN 推奨）
python scripts/collect.py --out work --min-stars 50000          # 件数を絞って書き出しを試す（pyarrow が必要）
scripts/sync_data.sh                                            # Releases のデータを data/ に同期
```
