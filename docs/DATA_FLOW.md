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
        commit["Commit state<br/>（master に直接コミット）"]
        test ==> ranking ==> commit
    end

    subgraph weekly["discover-frameworks.yml（毎週月曜 JST 7:37）"]
        discover["discover.py<br/>新規候補の検知<br/>（topic・説明文・awesome リストから集め、<br/>カテゴリ最下位の★数を閾値にする）"]
    end

    subgraph collectwf["collect-stars.yml（毎日 JST 3:37）"]
        collect["collect.py<br/>★500 以上・1 年以内に push の<br/>リポジトリ全体を検索"]
    end

    subgraph state[".state/（master にコミット）"]
        stars[("stars.json<br/>掲載中フレームワークの<br/>日ごとの★数")]
        lastRun[("last-run<br/>keepalive 用の日付")]
    end

    subgraph releases["GitHub Releases（コミットしない）"]
        dailyFiles[("data-YYYY-MM<br/>daily-YYYY-MM-DD.parquet<br/>日ごとの★数など")]
        reposFile[("data-latest<br/>repos.parquet<br/>リポジトリ情報のマスタ")]
    end

    gists["Pinned Gist<br/>frontend / backend<br/>★総数ランキング"]
    issues["Issue<br/>framework-candidate"]
    awesome["awesome リスト<br/>（awesome-go など）"]
    local["手元の分析<br/>sync_data.sh + DuckDB"]

    config --> ranking
    config --> discover

    ranking -->|"★数・言語"| gists
    ranking -->|"今日の★数を追記"| stars
    commit -->|"日付を更新"| lastRun

    discover -->|"候補ごとに作成"| issues
    issues -->|"既存候補（Open / Closed）を照合"| discover
    awesome -->|"Web フレームワークの節"| discover
    issues -.->|"人が採用を判断して追記"| config

    reposFile -->|"前日のマスタ"| collect
    collect -->|"毎日 1 ファイル追加"| dailyFiles
    collect -->|"上書き"| reposFile
    dailyFiles -.-> local
    reposFile -.-> local
```

- 太線（`update-ranking.yml` の中）: ステップの実行順。各ステップの実行条件は下の「毎日の workflow の処理順」を参照
- 実線: データの読み書き（現在動いている処理）
- 点線: 人の作業（Issue を見て判断する、手元で分析する）

## ファイルごとの役割

| ファイル | 書き込み元 | 中身 | 使い道 |
|---|---|---|---|
| `frameworks.json` | 人（手で編集） | カテゴリごとの見出し（`title`）・Gist のファイル名（`filename`）・検知の設定（`discover_topics` / `discover_phrases` / `discover_awesome`）と、対象リポジトリ（`repo`・表示名 `name`・言語の上書き `language`） | すべての workflow の入力 |
| `.state/stars.json` | `ranking.py` | `{日付: {リポジトリ: ★数}}`（掲載中のフレームワーク） | 今後、伸び幅などを表示するときの過去データ |
| `.state/last-run` | Commit state ステップ | 最終実行日（JST） | 60 日無活動で scheduled workflow が止まるのを防ぐ（keepalive） |
| Releases `data-YYYY-MM` の `daily-YYYY-MM-DD.parquet` | `collect.py`（collect-stars.yml が添付） | その日の★数・フォーク数・open issue 数・最終 push 日・アーカイブかどうか（★500 以上・1 年以内に push の全リポジトリ） | 伸び幅の分析（手元で DuckDB など） |
| Releases `data-latest` の `repos.parquet` | 同上（毎日上書き） | リポジトリ情報のマスタ（名前・説明・topics・言語・作成日など、最新の状態） | 分析時の名前や言語・作成日での絞り込み |

`.state/` の各ファイルの JSON 構成・項目の意味・例は [STATE_FORMAT.md](STATE_FORMAT.md) を、
Releases のデータの列・置き場所・読み方は [RELEASE_DATA.md](RELEASE_DATA.md) を参照してください。

`.state/` のファイルは、毎日の workflow の最後に github-actions[bot] 名義で master に直接コミットされます（PR は通しません）。
master にブランチ保護を設定するとこのコミットが失敗する点は [SETUP.md](SETUP.md) の「5. ★数の記録（自動）」を参照してください。

保持期間:
- 日ごとの★数（`stars.json`）は無制限に保持します（`scripts/history.py` の `KEEP_DAYS = None`）。
  同じ日に複数回実行した場合は、その日最初の値を残します。
- `last-run` は毎回上書きします。
- Releases の `daily-*.parquet` は削除も書き換えもしません（同じ日に再実行しても最初の分を残します）。`repos.parquet` は毎日上書きします。

## 毎日の workflow の処理順

```mermaid
sequenceDiagram
    autonumber
    participant WF as update-ranking.yml
    participant R as ranking.py
    participant GH as GitHub API
    participant G as Pinned Gist
    participant S as .state/*
    participant M as master

    WF->>WF: Test（unittest）
    Note over WF,R: Test が失敗したら ranking.py はスキップ
    WF->>R: 実行
    R->>GH: 各リポジトリの★数（REST /repos）
    R->>S: stars.json に今日の★数を追記
    R->>G: frontend / backend の★総数ランキングを更新（内容が同じならスキップ）
    Note over WF,M: Commit state は前のステップが失敗しても実行（!cancelled()）
    WF->>S: last-run を更新
    WF->>M: .state/* に変更があればコミットし、pull --rebase してから push
```

`ranking.py` は Gist を更新する前に★数を記録し、Commit state ステップは前のステップが失敗しても実行されます。
そのため、Gist の更新が失敗しても（PAT の期限切れなど）、その日の★数の記録は master に残ります。

## 毎日のデータ収集の処理順

```mermaid
sequenceDiagram
    autonumber
    participant WF as collect-stars.yml
    participant C as collect.py
    participant GH as GitHub 検索 API
    participant RL as GitHub Releases

    WF->>WF: Test（unittest。pyarrow を入れて実行）
    WF->>RL: data-latest から前日の repos.parquet をダウンロード（初回は無し）
    WF->>C: 実行
    C->>GH: ★500 以上・1 年以内に push の件数を数える
    loop ★数の範囲ごと（1 つの検索は 1,000 件まで）
        C->>GH: 検索（30 回/分を超えないよう間隔を空ける）
    end
    Note over C: 取れた件数が 95% 未満なら何も書き出さずに失敗
    C->>C: daily-YYYY-MM-DD.parquet と、前日のマスタに今日の分を反映した repos.parquet を書き出す
    WF->>RL: data-YYYY-MM に daily を添付（無ければリリースを作る。添付済みならそのまま）
    WF->>RL: data-latest の repos.parquet を上書き
```
