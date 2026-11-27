# 長文処理ベンチマーク予備実験　短文3試行と入力上限の事前検査

2026-10-14の中間分析。短文の保存済みログを読み取り、再採点と校正を行い、次の6条件を dry-run で検査した。この分析での追加モデル呼び出しは0件。短文3試行は同日確定した9試行の一部である。短文の実測に基づく校正で、5万トークン目標版は全条件で通過し、12万トークン目標版は全条件で上限を超えた。当時の校正値と判定を、次の実行条件を決めるまでの経緯として保存する。[9試行の最終分析](../long_context_comparison_20261014/report.md)

最終分析（`521e37a`）に収録された資料長は1万・5万・9万トークン目標。以下の12万目標版の時間・費用は当時の計画値であり、事前検査で拒否された条件のモデル成績はない。9万目標版の実測は最終分析を参照。[最終版の固定条件](../long_context_comparison_20261014/pilot_config.json)

## 短文の比較

全て `s101_short_middle_similar`、同一プロンプトSHA256、CLI 2.1.299。通常入力・キャッシュ読込・キャッシュ書込の合計が実測の総入力で、CLIのシステム入力も含む。Thinkingは出力の内訳で、費用へ再加算しない。

| 項目 | Haiku 4.5/default | Haiku 5.5/medium | Haiku 5.5/high |
|---|---:|---:|---:|
| 壁時計時間（秒） | 13.205 | 8.774 | 8.370 |
| 通常入力 | 9 | 2 | 2 |
| キャッシュ読込 | 0 | 535 | 16,026 |
| キャッシュ書込（全て1時間TTL） | 13,812 | 15,876 | 386 |
| 総入力 | 13,821 | 16,413 | 16,414 |
| 出力（Thinking込み） | 1,327 | 1,502 | 1,469 |
| Thinking | 1,076 | 1,188 | 1,155 |
| API換算費用（USD） | 0.034268 | 0.003932 | 0.000972 |
| 情報抽出の主指標 | 正解 | 正解 | 正解 |
| 条件の組み合わせの主指標 | 正解 | 正解 | 正解 |
| 生JSON形式の遵守 | 不遵守・フェンス除去で復旧 | 遵守 | 遵守 |
| 補助事実8項目の完全一致 | 5/8 | 8/8 | 8/8 |
| strict_success | false | true | true |

Haiku 4.5のassistantログは `claude-haiku-4-5-20251001`、modelUsageの正規名は `claude-haiku-4-5`。5.5は両試行とも `claude-haiku-5-5`。モデル照合は全てmatch。Effortは保存されたCLI指定がdefault（フラグ省略）/medium/high。生ログの `per_turn_effort_active` は4.5がfalse、5.5がtrueだが、medium/highの実効レベルやThinking予算自体は報告されていない。

Haiku 4.5の例外規定の補助抽出は、適用種別がmigration（正解renewal）、追加料金が0（正解500）、例外処理方法がreview（正解manual）。今回の質問はmigrationなので実際の追加料金は0、最終処理方法はreviewで、最終回答4830 credits/reviewは正しい。規定そのものと適用後の値を混同した可能性がある。採点器は資料のフィールド値一覧との一致で捏造2件・別対象の値1件・未裏付け引用3件と数えるが、これだけで自由な作り話と断定しない。根拠ID集合一致は8/9で、値の裏付けとは別指標。

highでは総入力の97.6%がキャッシュ読込。全入力を1時間キャッシュ書込として揃える参考換算では、medium=$0.0040336、high=$0.0040173となり、観測した大きな費用差の主因はキャッシュである。各1回なので、highが常に速い・安いという結論にはしない。短文だけでは長文能力向上の仮説を検証できない。

全てCLI正常・1ターン・usage.iterationsの記録1件、stderr空、ツール使用0、context_alerts空。送信プロンプトとCLI再送ハッシュは一致し、先頭・中央・末尾の確認値も一致。圧縮イベントは観測されていないが、圧縮なし・切り詰めなし・APIへの全内容配送はunverifiedのまま。報告コンテキスト窓は4.5が200,000、5.5が1,000,000で、ベンチマーク側の運用上限180,000とは区別する。

元結果:

- results/long_context_runs/long_context_haiku45_default_n19syylh
- results/long_context_runs/long_context_haiku_medium_12j2gphu
- results/long_context_runs/long_context_haiku_high_wsyk4egh

## 校正の意味と保存先

校正するのは「次の入力サイズをCLI実行前に見積もる係数」であり、問題生成や採点ではない。既存の校正式はモデル別に `最大(実測総入力 / プロンプトUTF-8バイト数) × 1.15`。次のプロンプトのバイト数に掛け、さらにCLI入力20,000・出力8,000を予約し、180,000以内か検査する。

未校正では1バイトを1トークンとして扱うため、中・長文は保守的な上限検査で拒否される。校正はこれを実測に基づく推定へ置き換える。システム入力も係数に含まれ、別途20,000も予約するため、特に短文からの長文推定は過大になりやすい。正確なトークナイザー計測や収容保証ではない。

作成済み: `results/long_context_calibration_short_20261014.json`（Git管理外）。係数は4.5が0.384883524、5.5が0.457092697。5.5はmedium/highの大きい方を採用。校正元CLIは2.1.299で、同じ生成設定・CLI版で使う。

```powershell
python -m ai_lab.long_context_benchmark calibrate results/long_context_runs/long_context_haiku45_default_n19syylh results/long_context_runs/long_context_haiku_medium_12j2gphu results/long_context_runs/long_context_haiku_high_wsyk4egh --output-file results/long_context_calibration_short_20261014.json
```

上のファイルは今回作成済み。同じ保存先で再実行すると上書きを拒否するので、再作成する場合は別名を指定する。元結果36ファイルのハッシュが変わっていないことを確認した。元資料も変更していない。校正値を変えても問い・正解・資料は変わらない。`--chars-per-token` による資料の再生成は別操作で、校正とは区別する。

## 6試行の見積もりと実行可否

seed=101、middle、similarを維持。中程度は200,000バイト・50,000トークン目標、長文は480,000バイト・120,000トークン目標。問い、正解の事実値・最終値・根拠IDが元の短文と同一であることを検証済み。無関係レコードが増え、根拠の文字位置は文量に合わせて移動する。

| 条件 | 中程度の入力概算 | 中程度の予約込み検査値 | 長文の入力概算 | 長文の予約込み検査値 |
|---|---:|---:|---:|---:|
| 4.5/default | 67,371 | 105,476：通過 | 161,081 | 213,243：拒否 |
| 5.5/medium | 80,005 | 120,011：通過 | 191,290 | 247,997：拒否 |
| 5.5/high | 80,010 | 120,011：通過 | 191,302 | 247,997：拒否 |

入力概算は短文の実測総入力/バイト数を単純に拡大した値。予約込み検査値には15%余裕、CLI20,000、出力8,000を含む。両方とも実測値ではない。中程度3条件は現在の校正でdry-runの検査を通過した。長文3条件は現在の校正で実行前に拒否されるため、6試行を連続実行できる状態ではない。

まず中程度3試行を行う計画とし、その実測だけから別の校正ファイルを作り、長文を再度dry-runする。短文を新校正へ含めるとmax方式で元の保守的な係数が残るため、中程度のみを指定する。次の例のパスは将来の中程度実験の実際の保存先に置き換える。今回は中程度の実モデル実行も新校正の作成も行っていない。

```powershell
python -m ai_lab.long_context_benchmark calibrate "results/long_context_runs/<中程度Haiku45>" "results/long_context_runs/<中程度Haiku55-medium>" "results/long_context_runs/<中程度Haiku55-high>" --output-file results/long_context_calibration_medium_20261014.json
```

現行式で元の長文を通すには、余裕込み係数が約0.315814以下である必要がある。中程度の実測総入力がモデルごとに55,280以下ならこの条件を満たす。5.5はmedium/highの最大値で判断する。実測がこの値を上回る場合、再校正だけでは長文を通せない。その場合は固定CLI入力と文量に比例する入力を分ける校正式や、報告されたモデル別窓と共通運用上限の扱いを見直す理由がある。数値を任意に下げて突破せず、コード変更前に設計を確認する。今回はコードを変更していない。

| 条件 | 中程度・全入力1h書込費用 | 長文・全入力1h書込費用 | 中程度の時間目安 | 長文の時間目安 |
|---|---:|---:|---:|---:|
| 4.5/default | $0.1414 | $0.3288 | 64秒 | 154秒 |
| 5.5/medium | $0.0168 | $0.1950 | 43秒 | 102秒 |
| 5.5/high | $0.0167 | $0.1950 | 41秒 | 98秒 |

費用は上の入力概算・各短文と同じ出力数（Thinking込み）・全入力1時間キャッシュ書込を仮定。合計約$0.894。全入力をキャッシュ読込とする参考シナリオは約$0.066、同じ入力概算で出力が各8,000なら全書込シナリオは約$1.00。新しい資料で全入力がキャッシュヒットする保証はない。これは上下限でもサブスクリプション実支出でもない。5.5は入力合計10万を超える長文で高価格帯を使用する。[公式料金表](https://platform.claude.com/docs/en/about-claude/pricing)を2026-10-14に再確認した。

時間は短文の壁時計時間を入力概算に比例させた粗い目安で、6件合計約8.4分。キャッシュ・起動時間・Thinkingが比例する保証はないため、計画枠は10〜30分程度とし、中程度の実測後に更新する。長文の費用・時間はガードが通った場合の仮定で、現状の拒否状態では長文リクエストは送られない。

## 当時の計画用コマンド

以下は全てdry-run。中程度は作成済みの短文校正を使用し、長文は将来作る中程度校正で再確認する。実行の承認後にだけ `--dry-run` を外す。長文はその前に3条件ともガードが通ることを確認する。

```powershell
$corpus = "results/long_context_corpus"
$shortCal = "results/long_context_calibration_short_20261014.json"
$mediumCal = "results/long_context_calibration_medium_20261014.json" # 中程度試行後に作成

python -m ai_lab.long_context_benchmark run $corpus --case-id s101_medium_middle_similar --model haiku45 --calibration $shortCal --limit 1 --dry-run
python -m ai_lab.long_context_benchmark run $corpus --case-id s101_medium_middle_similar --model haiku --effort medium --calibration $shortCal --limit 1 --dry-run
python -m ai_lab.long_context_benchmark run $corpus --case-id s101_medium_middle_similar --model haiku --effort high --calibration $shortCal --limit 1 --dry-run

python -m ai_lab.long_context_benchmark run $corpus --case-id s101_long_middle_similar --model haiku45 --calibration $mediumCal --limit 1 --dry-run
python -m ai_lab.long_context_benchmark run $corpus --case-id s101_long_middle_similar --model haiku --effort medium --calibration $mediumCal --limit 1 --dry-run
python -m ai_lab.long_context_benchmark run $corpus --case-id s101_long_middle_similar --model haiku --effort high --calibration $mediumCal --limit 1 --dry-run
```

独立問題は1個、各条件は1試行。モデルと推論設定の組み合わせによる比較であり、有意差や一般的な能力差は結論づけない。

## 記録の照合と公開前監査

2026-11-27 JST。短文3試行は、最終版の試行ID、ケースID `s101_short_middle_similar`、採点結果、時間、使用量、API換算費用と一致した。最終版に保存された3試行共通の送信プロンプトSHA-256は `3bd194a490ad86fca7247014571f141a865de421a659293dc0c26daa7a555eca`。中間版の `trials.csv` は最終版の先頭3試行と全列一致し、`summary.csv` の78セルは同じ試行と集計条件で照合できた。数値データの参照先は最終版に一本化する。[試行明細](../long_context_comparison_20261014/trials.csv)・[集計](../long_context_comparison_20261014/summary.csv)・[採点と再現手順](../long_context_comparison_20261014/README.md)

当時の短文校正係数と入力上限の計算式から、5万目標版の検査値105,476・120,011、12万目標版の検査値213,243・247,997を再計算し、記録と一致した。いずれもCLI入力20,000と出力8,000の予約を含む推定値で、上限は180,000。5.5の2設定は同じ校正係数を使う。費用はAPI換算額または計画時の試算であり、実請求額は計測していない。[入力上限の実装](../../ai_lab/long_context_benchmark.py)・[ベンチマーク条件](../../benchmarks/long_context/README.md)

対象3ファイルを確認し、認証情報、個人用の絶対パス、CLI生ログ、公式課題の非公開コピー、非公開テスト・参照実装の掲載はなかった。資料は自作の架空マニュアルを用いた実験の集計と要約。元記録は相対パスと試行IDで参照し、詳細 `analysis.json`、生ログ、校正JSONは既存の管理外に置く。公開対象は校正と事前検査の経緯を残すこの中間レポートとした。[公開方針](../../docs/PUBLICATION_POLICY.md)
