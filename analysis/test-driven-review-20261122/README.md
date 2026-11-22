# AI実験室 #12

## 実験条件と結果

- [事前登録](preregistration.md)、[固定入力のSHA-256とモデル条件](frozen-inputs.json)、[プリフライト](preflight.json)
- [結果報告](report.md)、[観測・評価・推測を分けた根拠](evidence.md)、[評価者の判定](adjudication.json)
- [試行1：OAuth障害による無効試行](public-run.json)、[障害時の認証状態](auth-recovery-status.json)、[復旧確認](auth-restored-status.json)
- [試行2：有効なモデル試行](trial2-public-run.json)、[2回のテスト実行内訳](test-runs.json)、[モデル回答原文](model-response.md)
- [AI作成のパイプライン/CLIテスト](test-work-trial2/tests/intake_pipeline.test.ts)、[AI作成のフォームテスト](test-work-trial2/tests/intake_form.test.ts)
- [モデルなしの再現結果](replay-check.json)、[公開用監査結果](audit.json)、[監査コード](audit.py)、[料金・使用量集計コード](summarize_trial2.py)

試行2ではClaude Haiku 5.5・effort highが2ファイルにテストを作成し、2回実行した。最終93件中91件成功・2件失敗。既知Z1/Z2の検出は0/2群。失敗2件は対象実装の確認済み不具合と認定しない。**91/93を仕様充足率や不具合検出率として使用しない。** 試行1は無効試行として別に保持した。

## 保存範囲

元の成果物の復元コピー `source-app/` と、公式課題文を含む `prompt.txt` はローカルのみに保存し、Gitに含めない。[固定入力](frozen-inputs.json)に全22ファイルとプロンプトのハッシュを残した。認証volume、公式課題コピー、非公開採点器、CLI生ストリーム、stderr、詳細操作ログもGitに含めない。生ログはGit除外済みの `results/test_driven_review_20261122/` と `results/test_driven_review_20261122_trial2/` にある。公開記録には認証文字列や個人用絶対パスを含めない。

`run.py` は当時の実行手順を示すが、モデルを新たに起動するため結果確認には使わない。現環境では両試行の結果ディレクトリが存在すると再実行を拒否する。

## モデルを呼ばない再現手順

1. [既存の#8復元手順](../react-lead-form-review-20261102/README.md)に従い、固定コミットの公式課題チェックアウトを用意する。保存済み差分からZを復元する。

   ```powershell
   powershell -NoProfile -ExecutionPolicy Bypass -File analysis/react-lead-form-review-20261102/restore_artifacts.ps1 -SourceRunId rlfm-0df740e1d9e8
   ```

   #8の復元マニフェストと今回の `frozen-inputs.json` はZの22ファイルについて同じSHA-256を記録している。[再現スクリプト](reproduce.ps1)も実行前に全ファイルを照合する。

2. 固定のテスト用Dockerイメージを用意し、次を実行する。どちらも `--network none`、認証なし、読取専用の成果物マウントと一時コピーを使い、**モデルは呼び出さない**。

   ```powershell
   powershell -NoProfile -ExecutionPolicy Bypass -File analysis/test-driven-review-20261122/reproduce.ps1 -Mode model-tests
   powershell -NoProfile -ExecutionPolicy Bypass -File analysis/test-driven-review-20261122/reproduce.ps1 -Mode known-bugs
   ```

   `model-tests` は最終93件のうち2件が失敗するため終了コード1が期待値。`known-bugs` は[評価者用コード](adjudicate_known.ts)を使い、Z1の `accepted` 対 `rejected/invalid_lead` と、Z2の既存CRM 363→364バイトを出力する。評価者の再現はAIの検出成功に数えない。

3. ローカルに両試行の非公開生ログがある環境では、次でモデルのツール履歴、TAP要約、入力・元成果物・公式課題の不変性、公開候補の秘密情報非混入を再監査できる。公開リポジトリだけでは生ログ自体の再照合はできない。

   ```powershell
   .\.harbor-react-lead-form-venv\Scripts\python.exe -m analysis.test-driven-review-20261122.audit --require-raw
   ```

   生ログがない環境では `--require-raw` を省くと、復元済みZ・公開記録・テストファイルを確認する。監査の範囲は生成される `audit.json` の `raw_records_checked` に示す。
