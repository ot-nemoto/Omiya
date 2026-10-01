# データの流れ

どの workflow（とスクリプト）が、どのファイルを読み書きし、それが何に使われるかをまとめます。

## 全体図

```mermaid
flowchart LR
    config[("frameworks.json<br/>対象フレームワークと<br/>検知の設定")]

    subgraph daily["update-ranking.yml（毎日 JST 7:17）"]
        direction TB
        test["Test<br/>（unittest）"]
        ranking["ranking.py<br/>★総数ランキング"]
        rising["rising.py<br/>Rising 候補の収集"]
        commit["Commit state<br/>（master に直接コミット）"]
        test ==> ranking ==> rising ==> commit
    end

    subgraph weekly["discover-frameworks.yml（毎週月曜 JST 7:37）"]
        discover["discover.py<br/>新規候補の検知<br/>（topic・説明文・awesome リストから集め、<br/>カテゴリ最下位の★数を閾値にする）"]
    end

    subgraph state[".state/（master にコミット）"]
        stars[("stars.json<br/>掲載中フレームワークの<br/>日ごとの★数")]
        risingStars[("rising.json<br/>Rising 候補の<br/>日ごとの★数")]
        risingRepos[("rising-repos.json<br/>Rising 候補の情報<br/>language / created_at / description /<br/>topics / first_seen / last_seen / found_via")]
        lastRun[("last-run<br/>keepalive 用の日付")]
    end

    gists["Pinned Gist<br/>frontend / backend<br/>★総数ランキング"]
    issues["Issue<br/>framework-candidate"]
    future["今後: Rising ランキング・<br/>伸び幅の表示（未実装）"]

    config --> ranking
    config --> rising
    config --> discover

    ranking -->|"★数・言語"| gists
    ranking -->|"今日の★数を追記"| stars
    rising -->|"今日の★数を追記"| risingStars
    rising -->|"情報を追加・更新"| risingRepos
    commit -->|"日付を更新"| lastRun

    discover -->|"候補ごとに作成"| issues
    issues -->|"既存候補（Open / Closed）を照合"| discover
    awesome["awesome リスト<br/>（awesome-go など）"] -->|"Web フレームワークの節"| discover
    issues -.->|"人が採用を判断して追記"| config

    stars -.-> future
    risingStars -.-> future
    risingRepos -.-> future
```

- 太線（`update-ranking.yml` の中）: ステップの実行順。各ステップの実行条件は下の「毎日の workflow の処理順」を参照
- 実線: データの読み書き（現在動いている処理）
- 点線: 人の作業、または今後の利用予定

## ファイルごとの役割

| ファイル | 書き込み元 | 中身 | 使い道 |
|---|---|---|---|
| `frameworks.json` | 人（手で編集） | カテゴリごとの見出し（`title`）・Gist のファイル名（`filename`）・検知の設定（`discover_topics` / `discover_phrases` / `discover_awesome`）と、対象リポジトリ（`repo`・表示名 `name`・言語の上書き `language`） | すべての workflow の入力 |
| `.state/stars.json` | `ranking.py` | `{日付: {リポジトリ: ★数}}`（掲載中のフレームワーク） | 今後、伸び幅などを表示するときの過去データ |
| `.state/rising.json` | `rising.py` | `{日付: {リポジトリ: ★数}}`（Rising 候補） | 今後の Rising ランキング（伸びの大きい新しいリポジトリ）の元データ |
| `.state/rising-repos.json` | `rising.py` | `{リポジトリ: {language, created_at, description, topics, first_seen, last_seen, found_via}}` | Rising ランキングの表示・絞り込み用の情報 |
| `.state/last-run` | Commit state ステップ | 最終実行日（JST） | 60 日無活動で scheduled workflow が止まるのを防ぐ（keepalive） |

各ファイルの JSON 構成・項目の意味・例は [STATE_FORMAT.md](STATE_FORMAT.md) を参照してください。

`.state/` のファイルは、毎日の workflow の最後に github-actions[bot] 名義で master に直接コミットされます（PR は通しません）。
master にブランチ保護を設定するとこのコミットが失敗する点は [SETUP.md](SETUP.md) の「5. ★数の記録（自動）」を参照してください。

保持期間:
- 日ごとの★数（`stars.json` / `rising.json`）は無制限に保持します（`scripts/history.py` の `KEEP_DAYS = None`）。
  同じ日に複数回実行した場合は、その日最初の値を残します。
- `rising-repos.json` も項目を削除しません（見つかるたびに最新の情報に更新）。
- `last-run` は毎回上書きします。

## 毎日の workflow の処理順

```mermaid
sequenceDiagram
    autonumber
    participant WF as update-ranking.yml
    participant R as ranking.py
    participant RS as rising.py
    participant GH as GitHub API
    participant G as Pinned Gist
    participant S as .state/*
    participant M as master

    WF->>WF: Test（unittest）
    Note over WF,R: Test が失敗したら ranking.py / rising.py はスキップ
    WF->>R: 実行
    R->>GH: 各リポジトリの★数（REST /repos）
    R->>S: stars.json に今日の★数を追記
    R->>G: frontend / backend の★総数ランキングを更新（内容が同じならスキップ）
    Note over WF,RS: rising.py は ranking.py の成否に関係なく実行
    WF->>RS: 実行
    RS->>GH: topic ごとに検索（★500 以上・作成 2 年以内・90 日以内に push）
    RS->>S: rising.json に★数、rising-repos.json に情報を記録
    Note over WF,M: Commit state は前のステップが失敗しても実行（!cancelled()）
    WF->>S: last-run を更新
    WF->>M: .state/* に変更があればコミットし、pull --rebase してから push
```

`ranking.py` は Gist を更新する前に★数を記録し、Commit state ステップは前のステップが失敗しても実行されます。
そのため、Gist の更新が失敗しても（PAT の期限切れなど）、その日の★数の記録は master に残ります。
