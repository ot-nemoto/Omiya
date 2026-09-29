# Omiya — 大宮の天気を Description に表示する

Pin したリポジトリのカードに、さいたま市大宮の天気がライブ表示されているように見せる仕組みです。
GitHub Actions が 1 日 3 回、[Open-Meteo](https://open-meteo.com/)（API キー不要）から天気を取得し、
リポジトリの **Description（About）** を書き換えます。

```
9/29 大宮 ⛅24°C 19〜26 ☔70% 💨北5m/s ｜明日〜 ☀️🌤️☁️🌧️☔☀️
```

## 仕組み

| ファイル | 役割 |
|---|---|
| `scripts/omiya_weather.py` | Open-Meteo 取得、WMO コード→絵文字表、値の整形（標準ライブラリのみ） |
| `scripts/update_description.py` | Description 文字列を生成し `PATCH /repos/{owner}/{repo}` で更新（内容が同じなら何もしない） |
| `scripts/make_svg.py` | 週間予報 SVG（ライト/ダーク）を生成（任意） |
| `.github/workflows/update-description.yml` | JST 6:13 / 12:13 / 18:13 に実行。手動実行も可 |
| `.state/last-run` | keepalive 用。1 日 1 回コミットし、60 日無活動による scheduled workflow の停止を防ぐ |

- 認証には Administration 権限付きの Fine-grained PAT（Secret `DESCRIPTION_PAT`）が必要 → [docs/SETUP.md](docs/SETUP.md)
- Description はプレーンテキスト 1 行のみ。リンク・画像・Markdown は使えません

## 表示フォーマット（提案）

Pinned カードは幅で省略されるため、**重要な情報ほど先頭**に置いています。`DESC_FORMAT` で切り替えられます。

| 値 | 出力例（文字数） | 用途 |
|---|---|---|
| `combined`（既定） | `9/29 大宮 ⛅24°C 19〜26 ☔70% 💨北5m/s ｜明日〜 ☀️🌤️☁️🌧️☔☀️`（約48） | 今日の要点＋週間の絵文字。カードが広ければ週間まで見える |
| `today` | `9/29 大宮 ⛅24°C（19〜26°C） ☔70% 💨北5m/s`（約34） | スマホ幅でも省略されにくい |
| `week` | `大宮 9/29〜 ⛅26 ☀️25 🌤️22 ☁️21 🌧️19 ☔18 ☀️23`（約41） | 週間の最高気温 |

先頭の日付（`9/29`）で情報の鮮度が分かります。スマホで省略される場合は `today` を推奨します。

## カスタマイズ

- **地点の変更**: 環境変数 `LOCATION_NAME` / `LATITUDE` / `LONGITUDE` / `TIMEZONE`
  （workflow の `env:` に追記。既定は大宮駅付近 35.906, 139.624）
- **書式の変更**: `scripts/update_description.py` の `fmt_today` / `fmt_week` / `fmt_combined` を編集。
  新しい書式は `FORMATS` に登録して `DESC_FORMAT` で指定
- **絵文字の変更**: `scripts/omiya_weather.py` の `WEATHER_EMOJI`（WMO コード対応表）
- **文字数上限**: `DESC_MAX_LEN`（既定 120、GitHub の上限は 350）
- **実行時刻**: workflow の `cron`（UTC 表記。JST−9 時間。例: JST 7:00 = `0 22 * * *`）
- 使える項目: 体感気温・UV 指数・日の出/日没は `Weather` / `Day` に取得済み（`make_svg.py` で使用）

## ローカル実行

```sh
python scripts/update_description.py --dry-run          # 表示のみ
python scripts/make_svg.py --out dist                   # SVG 生成
python scripts/make_svg.py --sample tests/sample.json   # オフラインで確認
```

## プロフィール README の週間予報 SVG（任意）

役割分担: **Pinned は 1 行の要約、README の SVG は詳細（曜日・最高/最低・降水確率・UV・日の出/日没）**。
SVG は `<img>` として表示されるため JS・外部フォント不使用（CSS アニメーションのみ、`prefers-reduced-motion` 対応）。
`<picture>` でダーク/ライトを切り替えます。手順は [docs/SETUP.md](docs/SETUP.md#4-任意プロフィール-readme-に週間予報-svg-を出す) と `profile-readme/` を参照。

## 注意

- Actions の cron は遅延・スキップされることがあります（数時間おきなら問題なし）
- PAT には有効期限があります。切れると workflow が失敗するので更新してください
