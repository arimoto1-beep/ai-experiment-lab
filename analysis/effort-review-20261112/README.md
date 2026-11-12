# AI実験室 #10: Haiku 5.5 effort別レビュー

同じHaiku 5.5の `medium`、`high`、`max` で、#7の初回成果物A・Bを読取専用レビューする計画。2026-11-12 JSTの実行では**4レビューが正常終了、A-maxは600秒でタイムアウト、B-maxは停止条件により未実行**。モデルの追加実行や再試行はしていない。

## 公開記録

- [事前登録](preregistration.md): 対象、既知不具合、採点規則、順序、停止条件。
- [結果と考察](report.md): 各試行の発見・見落とし・誤指摘・新規指摘、時間、費用、因果推論の限界。
- [公開用試行要約](public-runs.json): 実モデルID、CLIバージョン、指定effort、トークン、API換算費用、操作数、ローカル生ログのSHA-256。A-maxの部分ログと最終使用量の欠測も記録。
- [レビュー最終回答](reviews): 正常終了した4件のCLI `result_text` をUTF-8でそのまま保存。各ファイルのSHA-256は公開用試行要約にある。
- [復元マニフェスト](restoration.json): 公式Git blobと#7の保存差分から復元したAの17ファイル、Bの21ファイルのSHA-256。実行時は各元成果物ともバイト一致した。
- [公開監査](audit.json): 公開原文とローカル最終回答のバイト一致、復元コードと元成果物の一致、指定条件、A-maxの部分ログ、公開ファイルのSHA-256。

公式課題のコピー、復元したコード、認証情報、CLI/MCPの生ストリーム、個人用絶対パスはGitに含めない。`results/effort_review_20261112/` の生ログはローカルに保存し、公開用要約からSHA-256で照合できる。公開用のレビュー原文に含まれる入力例のメールアドレスは `example.com` の架空値である。

## 条件と再現手順

固定の公式 Terminal-Bench v4.0.0 checkout はコミット `452bf305c6daa62fc59061d22133a7cbc7c1572e` を `analysis/terminal-bench-v4.0.0/` に置く。課題の入手とDocker環境は[#7アダプターの説明](../../benchmarks/react_lead_form_adapter/README.md)、保存差分は[#7のpatches](../react-lead-form-replication-20261031/patches)を参照する。公式課題と検証器は編集しない。

新しいチェックアウトで、リポジトリのルートから次を実行する。最初のコマンドはモデルを呼ばず、保存差分からA/Bを `restored/` に作り、公開マニフェストの全ファイルハッシュと照合する。元試行の `artifacts/app` がローカルにもあれば、それともバイト比較する。`restored/` が既に存在すると安全のため停止する。

```powershell
py -3 -m analysis.effort-review-20261112.restore
```

実行を再現する場合は、[#9の読取専用コンテナ方式](../review-perspectives-20261109/README.md)と同じ固定CLI/workerイメージ、および分離した `ai-lab-claude-auth` ボリュームを事前に用意する。固定CLIは2.1.302、モデルIDは `claude-haiku-5-5`。次のコマンドは**新たにモデルを呼ぶ**ため、今回の結果確定・コミットでは実行していない。ランナーは `results/effort_review_20261112/` が既にある場合に再実行を拒否する。

```powershell
$env:RLFM_DOCKER = Join-Path $env:LOCALAPPDATA 'Programs/DockerDesktop/resources/bin/docker.exe'
py -3 -m analysis.effort-review-20261112.run
```

ランナーは共通プロンプトでA-medium→B-medium→A-high→B-high→A-max→B-maxの順に各1回だけ実行する。各試行600秒、35ターン、CLI予算上限$0.20。異常時は後続を停止するため、再現実行の完走数や結果は今回の記録と一致するとは限らない。API側の実効effort値はCLI出力から直接確認できない。

元のローカル生ログがある環境では、次の**モデル呼出しをしない**コマンドで公開用要約とレビュー原文を再抽出できる。`curate.py` は個人用パスや認証文字列の疑いがあれば停止する。

```powershell
py -3 -m analysis.effort-review-20261112.curate
py -3 -m analysis.effort-review-20261112.audit
```
