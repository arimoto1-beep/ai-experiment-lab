# 長文処理パイロットの再現手順

このディレクトリは、seed 101・中央配置・similarの同一問題を、short／medium／long90kと3モデル条件で各1回実行した9試行の最終分析です。実行条件と元ディレクトリ名は `pilot_config.json` に固定しています。

Gitには分析レポート、比較CSV、設定と分析スクリプトを保存します。元のCLIログ・生成資料・校正JSONは `results/`、詳細スナップショットは `analysis.json` に置き、既存のGit管理方針に従って追加しません。元ログを持たないチェックアウトでも、コミット済みCSVとレポートから比較結果を確認できます。

## 分析の再生成（モデル呼び出しなし）

元の9試行を `results/long_context_runs/` に置き、リポジトリのルートで実行します。元結果・正解・採点基準は変更しません。詳細スナップショットとこのディレクトリの分析成果物は再生成します。

```powershell
python -X utf8 -m analysis.long_context_comparison_20261014.prepare_snapshot
python -X utf8 analysis/long_context_comparison_20261014/render_report.py
```

最初のコマンドは元入力の再生成、保存回答と既存採点、CLI使用量と費用、入力元のSHA256を照合して、管理外の `analysis.json` を作ります。既存の集計関数を再利用し、原資料や実行結果を上書きしません。2つ目は日本語レポートと比較CSVを作ります。

## 資料と校正の再生成（モデル呼び出しなし）

次の保存先が既にある場合は、新しいディレクトリ名を使ってください。生成器は既存コーパスを上書きしません。

```powershell
python -m ai_lab.long_context_benchmark generate --output-dir results/long_context_pilot_reproduction --seeds 101 --lengths short medium long90k --positions middle --distractions similar
python -m ai_lab.long_context_benchmark validate results/long_context_pilot_reproduction

python -m ai_lab.long_context_benchmark calibrate results/long_context_runs/long_context_haiku45_default_sqcjgww6 results/long_context_runs/long_context_haiku_medium_0br101o7 results/long_context_runs/long_context_haiku_high_2tdltpqu --output-file results/long_context_pilot_calibration_reproduction.json
```

資料だけで正解も機械的に再現できます。校正は保存済み中程度3試行の入力使用量から安全チェック用の比率を再計算するもので、問題・正解を変更しません。共通枠18万・CLI予約2万・出力予約8000は維持します。dry-run例は [ベンチマークREADME](../../benchmarks/long_context/README.md#9万トークン相当の追加資料) を参照してください。実モデルを呼ぶコマンドはこの再現手順に含めません。

## 自動テスト

```powershell
python -X utf8 -m pytest -q
```

WindowsではUTF-8モードを使います。テストでは偽CLIを利用し、本物のClaude CLI探索を禁止しています。
