# 第2セット baseline：保存回答のJSON形式補正・再採点

対象: 75試行。strictは保存済み採点、normalizedは外側の単一フェンス除去後の既存採点です。

| model | effort | spec | trials | strict_json_valid_rate | strict_format_compliance_rate | fence_recovered | fence_recovery_rate | strict_f1 | normalized_f1 | normalized_perfect | normalized_missed_critical | normalized_unparseable | normalized_invalid_schema | mean_wall_seconds | mean_api_equivalent_usd | information_f1 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| claude-haiku-5-5 | medium | ALL | 15 | 100.0% | 100.0% | 0 | — | 0.696774 | 0.696774 | 2 | 21 | 0 | 0 | 32.344333 | 0.003739 | 0.682353 |
| claude-haiku-5-5 | medium | subscription_billing | 5 | 100.0% | 100.0% | 0 | — | 0.545455 | 0.545455 | 0 | 10 | 0 | 0 | 31.686400 | 0.003771 | 0.645161 |
| claude-haiku-5-5 | medium | resource_booking | 5 | 100.0% | 100.0% | 0 | — | 0.760000 | 0.760000 | 2 | 6 | 0 | 0 | 31.892600 | 0.003637 | 0.692308 |
| claude-haiku-5-5 | medium | notification_delivery | 5 | 100.0% | 100.0% | 0 | — | 0.800000 | 0.800000 | 0 | 5 | 0 | 0 | 33.454000 | 0.003810 | 0.714286 |
| claude-haiku-5-5 | max | ALL | 15 | 100.0% | 100.0% | 0 | — | 0.767296 | 0.767296 | 3 | 14 | 0 | 0 | 286.268733 | 0.034471 | 0.365217 |
| claude-haiku-5-5 | max | subscription_billing | 5 | 100.0% | 100.0% | 0 | — | 0.581818 | 0.581818 | 0 | 9 | 0 | 0 | 258.503400 | 0.031540 | 0.382979 |
| claude-haiku-5-5 | max | resource_booking | 5 | 100.0% | 100.0% | 0 | — | 0.851852 | 0.851852 | 1 | 2 | 0 | 0 | 289.390000 | 0.034704 | 0.437500 |
| claude-haiku-5-5 | max | notification_delivery | 5 | 100.0% | 100.0% | 0 | — | 0.880000 | 0.880000 | 2 | 3 | 0 | 0 | 310.912800 | 0.037170 | 0.277778 |
| claude-sonnet-4-6 | high | ALL | 15 | 0.0% | 0.0% | 15 | 100.0% | 0.000000 | 0.794702 | 2 | 15 | 0 | 0 | 59.767000 | 0.091474 | 0.983051 |
| claude-sonnet-4-6 | high | subscription_billing | 5 | 0.0% | 0.0% | 5 | 100.0% | 0.000000 | 0.800000 | 1 | 5 | 0 | 0 | 52.334800 | 0.082890 | 1.000000 |
| claude-sonnet-4-6 | high | resource_booking | 5 | 0.0% | 0.0% | 5 | 100.0% | 0.000000 | 0.760000 | 1 | 6 | 0 | 0 | 59.566000 | 0.089732 | 1.000000 |
| claude-sonnet-4-6 | high | notification_delivery | 5 | 0.0% | 0.0% | 5 | 100.0% | 0.000000 | 0.823529 | 0 | 4 | 0 | 0 | 67.400200 | 0.101798 | 0.947368 |
| claude-opus-4-8 | high | ALL | 15 | 100.0% | 100.0% | 0 | — | 1.000000 | 1.000000 | 15 | 0 | 0 | 0 | 49.130200 | 0.123999 | 0.928571 |
| claude-opus-4-8 | high | subscription_billing | 5 | 100.0% | 100.0% | 0 | — | 1.000000 | 1.000000 | 5 | 0 | 0 | 0 | 45.832800 | 0.119688 | 1.000000 |
| claude-opus-4-8 | high | resource_booking | 5 | 100.0% | 100.0% | 0 | — | 1.000000 | 1.000000 | 5 | 0 | 0 | 0 | 50.991400 | 0.124976 | 0.888889 |
| claude-opus-4-8 | high | notification_delivery | 5 | 100.0% | 100.0% | 0 | — | 1.000000 | 1.000000 | 5 | 0 | 0 | 0 | 50.566400 | 0.127334 | 0.888889 |
| claude-haiku-4-5 | default | ALL | 15 | 0.0% | 0.0% | 15 | 100.0% | 0.000000 | 0.743243 | 4 | 17 | 0 | 0 | 75.958600 | 0.066081 | 0.421053 |
| claude-haiku-4-5 | default | subscription_billing | 5 | 0.0% | 0.0% | 5 | 100.0% | 0.000000 | 0.640000 | 0 | 9 | 0 | 0 | 77.646600 | 0.060307 | 0.571429 |
| claude-haiku-4-5 | default | resource_booking | 5 | 0.0% | 0.0% | 5 | 100.0% | 0.000000 | 0.750000 | 1 | 6 | 0 | 0 | 77.429000 | 0.070571 | 0.000000 |
| claude-haiku-4-5 | default | notification_delivery | 5 | 0.0% | 0.0% | 5 | 100.0% | 0.000000 | 0.840000 | 3 | 2 | 0 | 0 | 72.800200 | 0.067364 | 0.571429 |

矛盾を構成する最小要件ID集合の大きさ別の正解数です。分母は、その大きさの正解が出現する機会数です。

| model | effort | 要件ID数 | normalized TP / 正解機会 | 見落としFN |
| --- | --- | --- | --- | --- |
| claude-haiku-5-5 | medium | 2 | 45 / 45 | 0 |
| claude-haiku-5-5 | medium | 3 | 7 / 15 | 8 |
| claude-haiku-5-5 | medium | 4 | 2 / 15 | 13 |
| claude-haiku-5-5 | max | 2 | 45 / 45 | 0 |
| claude-haiku-5-5 | max | 3 | 9 / 15 | 6 |
| claude-haiku-5-5 | max | 4 | 7 / 15 | 8 |
| claude-opus-4-8 | high | 2 | 45 / 45 | 0 |
| claude-opus-4-8 | high | 3 | 15 / 15 | 0 |
| claude-opus-4-8 | high | 4 | 15 / 15 | 0 |
| claude-sonnet-4-6 | high | 2 | 45 / 45 | 0 |
| claude-sonnet-4-6 | high | 3 | 11 / 15 | 4 |
| claude-sonnet-4-6 | high | 4 | 4 / 15 | 11 |
| claude-haiku-4-5 | default | 2 | 42 / 45 | 3 |
| claude-haiku-4-5 | default | 3 | 8 / 15 | 7 |
| claude-haiku-4-5 | default | 4 | 5 / 15 | 10 |

情報不足の指摘は矛盾検出と別に、要件ID集合の一致で採点します。

| model | effort | TP | FP | FN | Precision | Recall | F1 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| claude-haiku-5-5 | medium | 29 | 26 | 1 | 0.5272727272727272 | 0.9666666666666667 | 0.682353 |
| claude-haiku-5-5 | max | 21 | 64 | 9 | 0.24705882352941178 | 0.7 | 0.365217 |
| claude-sonnet-4-6 | high | 29 | 0 | 1 | 1.0 | 0.9666666666666667 | 0.983051 |
| claude-opus-4-8 | high | 26 | 0 | 4 | 1.0 | 0.8666666666666667 | 0.928571 |
| claude-haiku-4-5 | default | 8 | 0 | 22 | 1.0 | 0.26666666666666666 | 0.421053 |

Haiku 4.5はCLIデフォルト設定の指定した15試行だけを使用します: D:\work\ai-experiment-lab\results\20261012-222645_spec_haiku45_default_baseline_x5_gjd1d14k
他のHaiku 4.5実験は集計に加えません。従来4条件の再採点ルール・対象条件は共通です。

strict_json_valid_rateは元回答のJSON解析成功率、strict_format_compliance_rateは保存済みstatus=okの割合です。
fence_recovery_rateは元JSON解析失敗試行のうち、外側フェンス除去でJSON解析が成功した割合です（該当なしは—）。スキーマ違反と実行エラーは復旧後も採点失敗です。
F1は合計TP/FP/FNによるmicro集計です。完全正解はstatus=okかつFP=FN=0の試行数で、理由の妥当性を保証しません。
information_f1は情報不足の要件ID集合一致を別集計した値で、矛盾検出F1に混ぜていません。
平均時間・費用は保存値を使用し、費用未確認の試行があれば平均費用は—です。モデル照合の異常はsummary.csvで確認できます。
75試行の詳細はtrials.csv、指摘ID・理由のレビューと元strict採点全体はanalysis.jsonに保存しています。
元ファイル・課題・正解・採点・プロンプトは変更せず、CLIや実モデルは呼び出していません。

読み取れなかった候補フォルダを以下に記録します。採点対象の各条件・仕様書5件、計75件の検証は通過しています。

- D:\work\ai-experiment-lab\results\inventory-full-validation: [WinError 5] アクセスが拒否されました。: 'D:\\work\\ai-experiment-lab\\results\\inventory-full-validation'
- D:\work\ai-experiment-lab\results\inventory-validation: [WinError 5] アクセスが拒否されました。: 'D:\\work\\ai-experiment-lab\\results\\inventory-validation'
