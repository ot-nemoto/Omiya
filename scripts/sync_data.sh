#!/usr/bin/env bash
# GitHub Releases に添付した★数のデータを手元に同期する（docs/RELEASE_DATA.md）。
#   data-YYYY-MM の daily-*.parquet は、手元に無いものだけダウンロードする（過去の分は書き換わらないため）
#   data-latest の repos.parquet は毎回取り直す
#
# 使い方:
#   scripts/sync_data.sh [保存先（既定 data）]
#   REPO=owner/repo scripts/sync_data.sh   # このリポジトリの外で実行するとき
# 必要なもの: GitHub CLI（gh）
set -euo pipefail

dir="${1:-data}"
repo_opt=()
if [ -n "${REPO:-}" ]; then
  repo_opt=(--repo "$REPO")
fi
mkdir -p "$dir"

gh release list ${repo_opt[@]+"${repo_opt[@]}"} --limit 1000 --json tagName --jq '.[].tagName' \
  | grep -E '^data-[0-9]{4}-[0-9]{2}$' | sort \
  | while read -r tag; do
      echo "== $tag"
      gh release download "$tag" ${repo_opt[@]+"${repo_opt[@]}"} --dir "$dir" --pattern 'daily-*.parquet' --skip-existing
    done

echo "== data-latest"
gh release download data-latest ${repo_opt[@]+"${repo_opt[@]}"} --dir "$dir" --pattern repos.parquet --clobber
echo "同期しました: $dir"
