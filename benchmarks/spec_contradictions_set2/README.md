# 仕様書矛盾検出 第2セット

第2セットとして3仕様書を追加した。人間による本文・正解・形式モデルの確認用に [REVIEW.md](REVIEW.md) を用意した。課題設計・実装の開発中には実モデルを呼び出していない。その後の保存済み比較は [Haiku 4.5を加えた分析レポート](../../analysis/spec_set2_json_normalization_with_haiku45_20261012/report.md) を参照。

| 課題 | 要件 | 矛盾 | 2要件 | 3要件 | 4要件 | critical | 情報不足 | 非矛盾の対照 |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `subscription_billing` | 28 | 5 | 3 | 1 | 1 | 3 | 2 | 4 |
| `resource_booking` | 28 | 5 | 3 | 1 | 1 | 3 | 2 | 4 |
| `notification_delivery` | 28 | 5 | 3 | 1 | 1 | 2 | 2 | 4 |

課金の更新停止、金額・IDの食い違い、利用開始の前提条件、予約定員・取消状態、利用枠の返却、通知の優先順位・停止・再送を扱う。
要件は業務項目に沿って配置し、互いに関係する規定を離している。順序は処理の「完了後」で統一し、同期でない処理の完了を同時と読み替えない。停止したままなら矛盾しない順序制約と、完了義務が加わって矛盾する要件集合を区別する。
課題設計の段階では、特定モデルを失敗させるための調整や実モデルへの試行投入はしていない。

## 固定データと採点

本文は `specs/`、正解は `answer_keys/` に置く。第1セットのファイル・正解・manifestは変更していない。
既存の正解JSON形式（`version: 1`）を使用し、正解の矛盾に `condition` という成立条件の文字列だけを追加した。モデルの回答形式は変更しない。
最小ID集合の完全一致、重複処理、JSON不正時の扱い、TP/FP/FN・Precision/Recall/F1、criticalの見落とし、理由の別レビューは従来どおりである。
各正解の重大度は事前固定している。criticalは更新停止を無視する課金、必須処理の停止、定員不変条件の破壊、配信停止の破壊。金額・応答ID・取消状態・優先選択・再送時刻の食い違いはmajorとした。
成立条件と正解理由は採点側だけで読む。これらやREVIEW.mdをモデルのプロンプトに含めず、既存のツール無効化・空の作業場所・独立セッションを使用する。
入力6ファイルのSHA256を専用の `manifest.json` に固定する。改訂は実験前に行い、ハッシュも確認する。実験中はロード済みの同じ本文・正解を使う。原本と同じバイト列をスナップショット保存する。
レビュー資料は正解を含むため、実験対象モデルへ渡さない。

## 選択と記録

新規3仕様書だけを実行するには `--set set2 --spec all` を使う。
`--set` を省略した `--spec all` は従来の第1セット3件のまま。`--set set1` でも明示できる。
新規1件だけなら `--spec subscription_billing` 等を指定する。`--set` と単一仕様書の所属が違う場合は実行しない。
`experiment.json` と `summary.json` に `spec_sets`、各試行に `dataset_set` を記録し、`by_spec` と `by_set` に別々の集計を保存する。
レポートにはset列を追加した。過去のsummaryにセット情報がなくても、課題名から第1セットとして読み込む。過去の記録は書き換えない。
モデル、Effort、実モデルID照合、時間、トークン・キャッシュ使用量、API換算費用とCLI報告費用は既存機能を再利用する。

## 人間の確認後に実行するコマンド

まず固定データと実行条件を確認する。dry-runはモデルを呼ばない。

```powershell
python -m ai_lab.spec_benchmark validate --set set2
python -m ai_lab.spec_benchmark run --set set2 --spec all --model haiku --effort medium --runs 3 --dry-run
python -m ai_lab.spec_benchmark run --set set2 --spec all --model haiku --effort max --runs 3 --dry-run
python -m ai_lab.spec_benchmark run --set set2 --spec all --model opus48 --effort high --runs 3 --dry-run
```

本文・正解・モデル化を [REVIEW.md](REVIEW.md) から照合した後、独立したPowerShellで実行する。各条件は新規3仕様書×3回、計9試行。

```powershell
python -m ai_lab.spec_benchmark run --set set2 --spec all --model haiku --effort medium --runs 3
python -m ai_lab.spec_benchmark run --set set2 --spec all --model haiku --effort max --runs 3
python -m ai_lab.spec_benchmark run --set set2 --spec all --model opus48 --effort high --runs 3
```

比較は従来と同じreportコマンドで行う。第1セットの結果と並べても、set列と課題名で区別できる。

```powershell
python -m ai_lab.spec_benchmark report "results\<mediumの結果>" "results\<maxの結果>" "results\<opus48の結果>"
python -m pytest
```

## 検証の範囲

`tests/test_spec_set2_ground_truth.py` は、正解JSONから制約を生成せず、本文を別に読んでモデル化した21の関連要件群を検証する。
条件別に有限の入力・出力状態を列挙し、各群の全要件部分集合から最小不充足集合を探索する。既知の正解集合だけを検査する方式ではなく、発見した集合すべてを正解と照合する。
時系列では未完了と順序順位を含め、完了義務を外すと未完了のままにできること、順序制約を1つ外すと処理順を選べることも確認する。
実数の全時刻・全金額を列挙するのではなく、相対順序、境界時刻、料金比率、条件区分を有限状態へ射影している。本文の誤読を自動で排除できるわけではない。
群をまたぐ条件と共有属性、例外の対象ID、情報不足、正常要件はREVIEW.mdの対応表も使って確認する。全仕様の全日本語解釈に対する形式的証明とは主張しない。
