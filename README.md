# ai-experiment-lab
AIの能力・判断・協調・自律性を実験で検証するプロジェクト

## 第1回実験: 安いAIを何度も実行すれば、高性能AIの1回の実行に勝てるか

Claude Haiku 5.5 の複数回実行と、Claude Opus 5.5 の単独実行を比較するための小さな実験ツールです。
Python のプログラミング課題を AI に解かせ、成果物を隠しテストで客観的に評価し、時間・トークン・API換算コストを記録します。
実験は Claude Code CLI のサブスクリプション枠で行い、APIキーや Bedrock などの従量課金は使いません。

第1回は3問（`duration_parse`、`arithmetic_parser`、`inventory_allocation`）・合計23試行で全試行が合格しました。保存済みの結果は `data/exp001/` にあります。今回の追加は、同じ課題で Haiku 5.5 と Opus 4.8 の実務上の代替可能性を調べるための比較環境です。

## Haiku 5.5 と Opus 4.8 の比較

「以前 Opus 4.8 に任せていた仕事を Haiku 5.5 でも同等の品質で実行できるか」を、次の運用設定で比較します。
Effort が異なるので、**モデルと Effort の組み合わせによる実務上の比較**として扱います。純粋なモデル能力比較とは区別し、新しい実験の `experiment.json` と `summary.json` に `comparison_basis: "model_and_effort"` を保存します。

| 条件 | `--model` | 実際に指定するモデルID | `--effort` |
|---|---|---|---|
| Haiku 5.5 / medium | `haiku` | `claude-haiku-5-5` | `medium` |
| Haiku 5.5 / max | `haiku` | `claude-haiku-5-5` | `max` |
| Opus 4.8 / high | `opus48` | `claude-opus-4-8` | `high` |

`opus` は引き続き Opus 5.5（`claude-opus-5-5`）です。正式なモデルIDでも指定できます。
既存の `--effort` をそのまま使用します。[公式のモデル設定](https://code.claude.com/docs/en/model-config)で3条件のEffort対応を確認済みです（2026-10-11）。Haiku 5.5 には Claude Code **2.1.293 以上**を使用してください。

まず次の3コマンドを `--dry-run` 付きで確認します。モデルは呼び出されません。

```powershell
python -m ai_lab run --problem duration_parse --model haiku --effort medium --runs 3 --dry-run
python -m ai_lab run --problem duration_parse --model haiku --effort max --runs 3 --dry-run
python -m ai_lab run --problem duration_parse --model opus48 --effort high --runs 3 --dry-run
```

後日、独立したPowerShellターミナルで実験を行う場合は、同じ試行回数で次を実行します。今回の環境追加では実モデルによる実験は行っていません。

```powershell
python -m ai_lab run --problem duration_parse --model haiku --effort medium --runs 3
python -m ai_lab run --problem duration_parse --model haiku --effort max --runs 3
python -m ai_lab run --problem duration_parse --model opus48 --effort high --runs 3
```

`--problem` を `arithmetic_parser` または `inventory_allocation` に置き換えると、残りの既存課題でも同じ3条件を比較できます。課題文・初期実装・隠しテストは共通です。
実行後に表示された3つの保存先を、既存のレポートに渡します（パスは実際の保存先に置き換えてください）。

```powershell
python -m ai_lab report "results\<Haiku-mediumの実験フォルダ>" "results\<Haiku-maxの実験フォルダ>" "results\<Opus48-highの実験フォルダ>"
```

モデル・Effort・課題ごとに、合格率、平均実行時間（`mean_sec`）、平均API換算料金（`mean_api_usd`）を表示します。
実モデルIDは `trial.json` の `model_check.actual_model_ids` と `claude.model_usage` に保存します。指定モデルと異なるIDが報告された場合は `model_check.status: "mismatch"`、`modelUsage` がない場合は `"unverified"` とし、実行ログとレポートにも表示します。通常IDに対応する日付付きIDは一致として扱います。
合否は従来どおり隠しテストだけで決まり、モデル照合の異常は別に数えます。異常がある試行は指定した比較条件の成績として解釈しないでください。

### Opus 4.8 の料金設定

[Anthropic公式料金表](https://platform.claude.com/docs/en/about-claude/pricing)と[Opus 4.8の仕様](https://platform.claude.com/docs/en/models/opus-4-8/overview)を **2026-10-11** に確認しました。単価は通常モード・USD / 100万トークンです。

| 入力 | 出力 | キャッシュ読み込み | 5分キャッシュ書き込み | 1時間キャッシュ書き込み |
|---|---|---|---|---|
| $5.00 | $25.00 | $0.50 | $6.25 | $10.00 |

Opus 4.8 は100万トークンまで通常単価で、長文コンテキストの割増はありません。Fast mode の割増料金はこの比較の対象外です。
公式料金を確認できないモデルには単価を推測せず、未知モデルの使用量は料金に含めず `cost.complete: false` にします。すべて未知ならAPI換算料金は `null` です。
新しい実験条件には料金表URL・確認日・単価を保存し、計算できた試行の `cost` にも使用した単価と出典を保存します。CLI報告料金は引き続き別項目です。

## 仕様書の矛盾検出ベンチマーク

受注・出荷、経費申請・承認、会員・権限管理の3仕様書を追加しました。各20要件で、矛盾・条件違い・明示的例外・情報不足・正常要件を含みます。
Pythonコード課題とは独立した `ai_lab.spec_benchmark` で実行・採点します。既存のモデル、Effort、サブスクリプション認証確認、料金計算を再利用します。
正解は採点側に分離し、SHA256で固定しています。モデルには本文だけを渡し、ファイル操作とMCPのツールを無効にします。

```powershell
python -m ai_lab.spec_benchmark validate
python -m ai_lab.spec_benchmark run --spec all --model haiku --effort medium --runs 3 --dry-run
python -m ai_lab.spec_benchmark run --spec all --model haiku --effort max --runs 3 --dry-run
python -m ai_lab.spec_benchmark run --spec all --model opus48 --effort high --runs 3 --dry-run
```

後日の実実験では、独立したターミナルで `--dry-run` を外します。各条件につき3仕様書×3試行、計9試行です。
`python -m ai_lab.spec_benchmark report` に各条件の実験ディレクトリを渡すと、TP・FP・FN、Precision・Recall・F1、重大な見落とし、形式不正、平均時間・API換算費用を比較できます。
ID集合の一致で採点し、理由の妥当性は `reason_review.json` で別に確認します。詳細な採点規則、正解検証、隔離と実機の未確認事項は [仕様書ベンチマークの説明](benchmarks/spec_contradictions/README.md)を参照してください。

## 仕様書矛盾検出の第2セット

`subscription_billing`（契約・課金・返金）、`resource_booking`（施設予約・利用枠）、`notification_delivery`（通知・優先順位・再送）の3仕様書を追加しています。各28要件・矛盾5件で、条件、状態遷移、処理順序を含みます。
既存の採点規則と第1セットの固定ファイルは変更していません。`--set set2 --spec all` で新規3件だけを選べます。セットを省略した `--spec all` は従来どおり第1セット3件です。

```powershell
python -m ai_lab.spec_benchmark validate --set set2
python -m ai_lab.spec_benchmark run --set set2 --spec all --model haiku --effort medium --runs 3 --dry-run
```

実験前に [第2セットのレビュー資料](benchmarks/spec_contradictions_set2/REVIEW.md)で本文・正解・独立した形式モデルの対応を確認できます。3条件の実行手順は [第2セットREADME](benchmarks/spec_contradictions_set2/README.md)にあります。記録にはセット名を追加し、仕様書別とセット別に集計します。

## Sonnet 4.6 を加えた第2セットの比較

`--model sonnet46` は `claude-sonnet-4-6` を指定します。Pythonコード課題と仕様書ベンチマークの両方で使用でき、既存の `haiku`、`opus`、`opus48` も引き続き使用できます。
今回の比較条件は次の4通りです。すべて第2セット・`baseline`・各仕様書5試行とし、モデルとEffortの組み合わせで比較します。

| モデル | `--model` | `--effort` | `--prompt-variant` |
|---|---|---|---|
| Haiku 5.5 | `haiku` | `medium` | `baseline` |
| Haiku 5.5 | `haiku` | `max` | `baseline` |
| Sonnet 4.6 | `sonnet46` | `high` | `baseline` |
| Opus 4.8 | `opus48` | `high` | `baseline` |

既存3条件の保存済み結果をそのまま使用し、Sonnet 4.6だけを追加実行します。独立したPowerShellターミナルで、まず `--dry-run` により設定を確認してください。

```powershell
python -m ai_lab.spec_benchmark run --set set2 --spec all --model sonnet46 --effort high --prompt-variant baseline --runs 5 --dry-run
python -m ai_lab.spec_benchmark run --set set2 --spec all --model sonnet46 --effort high --prompt-variant baseline --runs 5
```

3仕様書×5回＝15試行です。サブスクリプション版Claude Codeの既存認証を使用します。今回の開発では実モデルを実行していません。
モデル照合、ツール無効化、プロンプト、採点、時間・トークン・料金の記録方式は共通です。`modelUsage` に別モデルが含まれる場合は `mismatch`、取得できない場合は `unverified` として保存・表示します。

実行後は、Sonnetの保存先と既存3条件の保存先をレポートに渡します（実際のパスに置き換えてください）。

```powershell
python -m ai_lab.spec_benchmark report "results\<Haiku-medium-baselineの実験フォルダ>" "results\<Haiku-max-baselineの実験フォルダ>" "results\<Sonnet46-high-baselineの実験フォルダ>" "results\<Opus48-high-baselineの実験フォルダ>"
```

モデル・Effort・プロンプト条件・セット・仕様書別に、F1、重大な見落とし、平均実行時間、平均API換算費用を表示します。保存済みの料金・成績を読み込み、再計算や書き換えは行いません。
記事 #2 はHaikuとOpusの結果、#3 はHaikuとSonnetの結果にOpusの参考比較を加えて使用できます。

### Sonnet 4.6 の料金設定

[Anthropic公式料金表](https://platform.claude.com/docs/en/about-claude/pricing)と[Sonnet 4.6の仕様](https://platform.claude.com/docs/en/models/sonnet-4-6/overview)を **2026-10-12** に確認しました。提示された参考値と一致しています。単価は通常モード・USD / 100万トークンです。

| 入力 | 出力 | キャッシュ読み込み | 5分キャッシュ書き込み | 1時間キャッシュ書き込み |
|---|---|---|---|---|
| $3.00 | $15.00 | $0.30 | $3.75 | $6.00 |

Sonnet 4.6は100万トークンまで通常単価で、長文コンテキストの割増はありません。既存モデルの単価も同日に再確認し、値は変更していません。新規結果には確認日・参照URL・単価を保存します。
既存の料金計算を再利用し、TTL内訳が得られる場合は5分と1時間を区別します。TTL内訳が不明な場合は従来どおり1時間単価を仮定し、`cost.notes` に記録します。API換算料金とCLI報告料金は別々に保存します。

## Haiku 4.5：前世代の小型モデルとの比較

`--model haiku45` は `claude-haiku-4-5` を指定します。[公式仕様](https://platform.claude.com/docs/en/models/haiku-4-5/overview)で、このIDが日付付き `claude-haiku-4-5-20251001` に対応することを確認しました。両IDを同じモデルとして照合し、実際の報告IDはそのまま保存します。

今回採用する推論設定は **Claude Code CLIのデフォルト（Effort・Thinking予算を追加指定しない）** です。
Haiku 4.5は[公式のモデル設定](https://code.claude.com/docs/en/model-config)ではEffort非対応で、固定予算のExtended Thinkingを使用します。Haiku 5.5のmediumやmaxへの換算は行いません。
ベンチマークで `--effort` を省略すると、Haiku 4.5だけは `effort: "default"` と記録し、Claude CLIには `--effort` を渡しません。`--effort default` と明示しても同じです。Haiku 4.5のlow / medium / high / xhigh / max指定はエラーにします。既存モデルの省略時設定は従来どおりmediumです。

第2セット・baseline・各5回（計15試行）の実行例です。最初は `--dry-run` で確認してください。

```powershell
python -m ai_lab.spec_benchmark run --set set2 --spec all --model haiku45 --prompt-variant baseline --runs 5 --dry-run
python -m ai_lab.spec_benchmark run --set set2 --spec all --model haiku45 --prompt-variant baseline --runs 5
```

後日の実験は独立したターミナルで行い、保存先を `python -m ai_lab.spec_benchmark report` に既存条件の保存先と一緒に渡します。レポートの `effort=default` はCLIフラグ省略を意味します。
対応機能の開発では実モデルを実行していません。その後に保存された15試行の成績・時間・費用は、[Haiku 4.5を加えた比較分析](analysis/spec_set2_json_normalization_with_haiku45_20261012/report.md)を参照してください。

### 推論設定とThinkingの記録

**2026-10-12** に、ローカルClaude Code **2.1.286** の `--version`・`--help` を確認しました。ヘルプには `--effort` の5段階が載っていますが、モデル別対応やThinking予算を直接指定するフラグはありません。[公式仕様](https://code.claude.com/docs/en/model-config#extended-thinking)ではThinkingの設定を `/config` の `alwaysThinkingEnabled`、セッションの `Alt+T`、環境変数 `MAX_THINKING_TOKENS` で制御します。APIの固定予算は `budget_tokens` ですが、今回APIは使用しません。
実験側はThinkingを有効・無効に切り替えず、予算も上書きしません。CLIの設定や継承した環境に委ね、`reasoning_settings` にフラグ省略・予算上書きなし、関連環境変数と実効予算不明（`null`）を保存します。CLIのバージョンも従来どおり記録します。

原ログの `usage`・`modelUsage` を保持し、Thinkingの報告値を `trial.json` の `claude.thinking_tokens` に保存します。`usage.output_tokens_details.thinking_tokens` を優先し、なければ全モデルに報告された `modelUsage.*.thinkingTokens` の合計を使います。未報告は `null` とし、Thinkingなしと推測しません。
新規仕様書レポートの `thinking_tokens` は試行合計です。未報告を含む場合や過去の集計には `-` を表示し、旧結果は書き換えません。[公式のThinking料金仕様](https://platform.claude.com/docs/en/build-with-claude/thinking-steering-and-cost#pricing)に従い、Thinkingは出力トークンに含まれる内訳として扱い、API換算費用へ再加算しません。

### Haiku 4.5 の料金設定

[Anthropic公式料金表](https://platform.claude.com/docs/en/about-claude/pricing)と[Haiku 4.5の仕様](https://platform.claude.com/docs/en/models/haiku-4-5/overview)を **2026-10-12** に確認しました。通常モード・USD / 100万トークンの単価です。

| 入力 | 出力 | キャッシュ読み込み | 5分キャッシュ書き込み | 1時間キャッシュ書き込み |
|---|---|---|---|---|
| $1.00 | $5.00 | $0.10 | $1.25 | $2.00 |

コンテキスト上限は20万トークンです。長文拡張を指定せず通常単価を使います。TTL内訳が得られる場合は5分と1時間を区別し、内訳不明の場合は従来どおり1時間単価を仮定して注記します。API換算料金とCLI報告料金は別々に保存します。
既存のモデル、仕様書、正解、採点、両プロンプト、保存済み実験・分析結果は変更しません。60試行用の独立した再採点CLIの対象条件もそのままです。

## プロンプトの最小性検証手順の比較

仕様書ベンチマークの `--prompt-variant` で `baseline`（既定）と `minimality` を選べます。
`baseline` は従来のプロンプトをそのまま使用します。`minimality` は仕様書本文の直前に、適用条件の同時成立、必要なIDの不足、IDを1つずつ外した場合の充足可能性、情報不足との区別を確認する一般的な指示だけを追加します。
JSON形式と情報不足の報告形式は共通です。検証過程の長文出力は要求せず、最終回答は要件ID集合と簡潔な理由とします。特定の課題・要件ID・正解は追加指示に含めません。

第2セットをHaiku / mediumで実行する例です。最初は末尾に `--dry-run` を付けて確認できます。

```powershell
python -m ai_lab.spec_benchmark run --set set2 --spec all --model haiku --effort medium --prompt-variant baseline --runs 3
python -m ai_lab.spec_benchmark run --set set2 --spec all --model haiku --effort medium --prompt-variant minimality --runs 3
```

同じ仕様書・モデル・Effort・試行回数で比較してください。モデル照合、ツール無効化、採点、時間・使用量・料金の取得は既存機能を使います。
`experiment.json`、`summary.json`、各 `trial.json` に `prompt_variant` を保存し、実際に送るプロンプトのSHA256も実験条件に保存します。新規結果のフォルダ名にもバリエーション名を含めます。
`python -m ai_lab.spec_benchmark report` は `prompt_variant` 列で条件を区別します。項目のない旧結果は `baseline` として読み込み、書き換えません。
追加指示による精度・時間・トークン・費用の変化は未確認です。この機能の開発では実モデルを呼び出していません。

## 保存回答のJSON形式補正・再採点

`ai_lab.spec_rescore` は保存済み回答だけを読む独立した分析用CLIです。実験の実行・採点・プロンプトは変更しません。
`experiment.json` と各 `trial.json` の条件を照合し、第2セット・`baseline` のHaiku / medium、Haiku / max、Sonnet 4.6 / high、Opus 4.8 / highを対象にします。
古い結果に `prompt_variant` がない場合は従来の `baseline` として扱い、`minimality` と第1セットは除外します。各条件・仕様書5試行、計60試行が揃わない場合や、固定データのハッシュ・メタデータが一致しない場合は分析を保存せずエラーにします。
読み取れない候補フォルダは分析JSONとレポートに記録します。対象の60試行が揃わなければエラーにし、読めた試行だけで比較結果を保存しません。

```powershell
python -m ai_lab.spec_rescore --results-dir results --output-dir analysis/spec_set2_json_normalization_20261012
```

出力先には、元結果の外にある未作成のディレクトリを指定してください。再度実行する場合は別名にします。既存の分析ファイルも上書きしません。

Haiku 4.5/defaultの15試行も比較する場合は、対象の実験フォルダを `--haiku45-dir` で明示します。事前確認の試行など、指定していないHaiku 4.5の実験は加えません。指定フォルダのモデル・推論設定・baseline・固定データを照合し、各仕様書5件と既存4条件60件、計75試行が揃うことを確認します。指定省略時は従来の60試行です。

```powershell
python -m ai_lab.spec_rescore --results-dir results --haiku45-dir "results/<Haiku45-default-baselineの15試行フォルダ>" --output-dir analysis/spec_set2_json_normalization_with_haiku45
```

この比較では `by_requirement_count.csv` も出力します。正解の最小要件ID集合が2・3・4個の場合それぞれについて、正解機会数、strict / normalizedの完全一致したTPとnormalizedのFN・再現率を保存します。15試行における正解機会は2要件45件・3要件15件・4要件15件です。IDが抜けた誤指摘は、元の正解集合の大きさに対する見落としとして扱い、別の大きさの正解にはしません。既存の正規化・スキーマ検証・採点ルールは変更しません。

補正は全モデル共通で、まず元回答を既存と同じJSON解析器で解析します。解析失敗時に限り、回答全体を囲む単一の `json` または言語指定なしMarkdownコードフェンスだけを除去し、内側の全内容を再解析します。バッククォート・チルダのフェンスと外側の空白に対応します。
説明文付き回答、複数ブロック、他言語指定、不完全なフェンスからJSONを抽出しません。JSON構文、要件ID、理由、内容の補完・修復はしません。重複キーや非JSON数値も既存どおり拒否します。
補正後は既存のスキーマ検証・ID集合の採点をそのまま使います。JSONが解析できてもスキーマ違反や実行エラーがあれば正解扱いしません。

| 出力 | 内容 |
|---|---|
| `analysis.json` | 元strict採点全体、normalized採点と理由レビュー、元実験ID・回答パス・ハッシュ、条件、時間・保存済み費用、情報不足の別採点 |
| `trials.csv` | 60試行のstrict / normalized、JSON解析・フェンス復旧・解析不能、TP / FP / FN・Precision / Recall / F1・重大な見落とし、時間・費用 |
| `summary.csv` | モデル・Effort別の全体および仕様書別集計（16行） |
| `report.md` | 集計の一覧表と指標の定義 |

Gitには、保存する比較の `report.md`、`summary.csv`、`trials.csv` と、出力される場合は `by_requirement_count.csv` を追加します。
元の実行ログを含む `results/` と、詳細な採点・理由を複製する生成物 `analysis/*/analysis.json` はGit管理外です。詳細JSONはローカルに残し、必要に応じて元結果から再生成します。
保存済みの比較は [4条件・60試行の分析](analysis/spec_set2_json_normalization_20261012/report.md) と [Haiku 4.5を加えた5条件・75試行の分析](analysis/spec_set2_json_normalization_with_haiku45_20261012/report.md) を参照してください。

`strict` は保存された採点結果を維持します。`normalized` は形式補正後の独立した採点です。元の `answer.txt`、`trial.json`、`summary.json`、`experiment.json`、`reason_review.json` は書き換えません。API換算費用と時間も保存値を使用し、再計算しません。
元JSONの解析成功率と、スキーマまで含めた保存済みstrict形式遵守率を分けて表示します。フェンス復旧率の分母は元JSON解析失敗数です。復旧対象がなければ率は空欄（一覧表は `—`）になります。
矛盾検出F1は合計TP / FP / FNによるmicro集計です。完全正解試行は採点成功かつFP=FN=0とし、理由の妥当性は別途レビューします。情報不足のID集合一致は `information_*` に別集計し、矛盾検出F1には混ぜません。

## 構成

| パス | 内容 |
|---|---|
| `ai_lab/` | 実験ツール本体（CLI、Claude Code 呼び出し、評価、集計） |
| `problems/<課題名>/` | 課題。`duration_parse`（期間の解析）、`arithmetic_parser`（四則演算）、`inventory_allocation`（注文の在庫引当のバグ修正）。各課題は `problem.md`（課題文）、`starter/`（初期ファイル）、`tests/`（隠しテスト。AI には渡さない） |
| `tests/` | 開発用テスト。偽の CLI（`tests/fixtures/fake_claude.py`）を使い、実モデルは呼び出さない |
| `benchmarks/` | 仕様書ベンチマークの固定データ、正解、検証手順 |
| `analysis/` | 保存済み比較のレポートとCSV（詳細な生成JSONはGit管理外） |
| `results/` | 実験結果（Git 管理外） |
| `docs/DEVELOPMENT_LOG.md` | 開発中に発生した問題と修正の記録 |

## 前提

- Python 3.10 以上。依存関係は `pip install -r requirements.txt`（pytest のみ）。
- Claude Code CLI（`claude.exe` のネイティブ版を推奨）をインストールし、サブスクリプションでログインしておく。`claude auth status` の `authMethod` が `claude.ai` になっていること。
- 実験は**独立したターミナル**（PowerShell など）で実行する。Claude Code のセッション内（Bash ツールなど）からは本実行を拒否する。入れ子実行を避けるためです。
- `ANTHROPIC_API_KEY` などの従量課金用の環境変数は、子プロセスには渡さないようにしてあります。念のため端末では設定しないでください。

## テスト

```
python -m pytest
```

pytest の一時ディレクトリにアクセスできない環境では、作業用のパスを指定してください。再採点の出力先保護も検証するため、リポジトリの `results/`、`data/`、`benchmarks/`、`problems/` の外に置いてください。

```
python -m pytest --basetemp=C:\some\writable\dir
```

## 実行手順

### 1. 実行内容の確認（モデルは呼び出さない）

```
python -m ai_lab run --problem duration_parse --model haiku --effort medium --runs 3 --dry-run
```

1試行で実行される `claude` のコマンドと、この端末が本実行できる状態かを表示します。

### 2. 動作確認（まず1回だけ）

独立したターミナルで実行してください。

```
python -m ai_lab run --problem duration_parse --model haiku --effort medium --runs 1
```

`results/<実験名>/trial_01/claude_stdout.txt` と `trial.json` を確認し、想定どおりの形式で記録されているかを見てください。

### 3. 本実験

```
python -m ai_lab run --problem duration_parse --model haiku --effort medium --runs 3
python -m ai_lab run --problem duration_parse --model opus --effort medium --runs 1
```

主なオプション:

- `--model`: `haiku` / `opus` / `opus48` / `sonnet46` / `haiku45`、またはモデルID（`claude-haiku-5-5` など）
- `--effort`: `default` / `low` / `medium` / `high` / `xhigh` / `max`（省略時はHaiku 4.5のみ `default`、他は従来どおり `medium`）
- `--runs`: 独立した試行の回数（既定 1）
- `--timeout`: 1試行の上限秒数（既定 1200）
- `--claude-bin`: `claude.exe` の場所（既定は PATH 上の `claude`）。`.cmd` のラッパーは、課題文の記号が cmd.exe で崩れるため拒否します。

### 第2課題（arithmetic_parser）

```
python -m ai_lab run --problem arithmetic_parser --model haiku --effort medium --runs 1 --dry-run
python -m ai_lab run --problem arithmetic_parser --model haiku --effort medium --runs 1
python -m ai_lab run --problem arithmetic_parser --model opus --effort medium --runs 1
```

1回ずつ、独立したターミナルで実行してください。課題文は `problems/arithmetic_parser/problem.md` にあります。

### 第3課題（inventory_allocation：バグ修正）

既存の在庫引当プログラムを、課題文の仕様に合わせて修正する課題です。
同順位の受付順、同一商品の明細合算、拒否時の在庫保持、入力在庫の保持に4つの不具合があります。
この不具合一覧は開発者向けで、AI に渡す課題文には修正箇所や解答を含めていません。

```powershell
python -m ai_lab run --problem inventory_allocation --model haiku --effort medium --runs 3 --dry-run
python -m ai_lab run --problem inventory_allocation --model haiku --effort medium --runs 3
python -m ai_lab run --problem inventory_allocation --model opus --effort medium --runs 1
```

独立したターミナルで実行してください。Haiku を3回、Opus を1回、同じ effort で比較します。
参照実装は `tests/fixtures/inventory/reference.py`、課題の検証は `tests/test_problem_inventory_allocation.py` にあります。
AI の作業ディレクトリにコピーされるのは初期実装の `solution.py` だけです。
採点テスト36件は参照実装に依存せず、各不具合の単独検出と通常機能の回帰を確認します。
課題自体の検証だけを実行する場合は、次のコマンドを使います（実モデルは呼びません）。

```
python -m pytest tests/test_problem_inventory_allocation.py -q -p no:cacheprovider
```

### 4. 比較

```
python -m ai_lab report results\<Haiku の実験フォルダ> results\<Opus の実験フォルダ>
```

## 仕組み

- **試行の独立性**: 試行ごとに `starter/` を新しい作業ディレクトリにコピーし、`claude -p` を1回呼び出します。会話は引き継がず（`--no-session-persistence`）、作業ディレクトリも共有しません。
- **AI にできること**: 作業ディレクトリ内の読み取り・書き込み・編集（`Read,Write,Edit`）だけです。コードは実行できません（Bash は与えません）。CLAUDE.md・フック・MCP は読み込みません（`--safe-mode`）。
- **評価**: 隠しテストは `problems/<課題>/tests/` にあり、作業ディレクトリにはコピーしません。試行後に pytest で評価し、結果を JUnit XML で数えます。CLI が異常終了していても、作業ディレクトリに残った成果物は評価します。
- **課金の安全策**: 試行の前に `claude auth status` を確認し、認証方式が `claude.ai` か `oauth_token`（サブスクリプション）以外なら実行しません。`--bare` は使いません（APIキーが必要になるためです）。
- **入れ子実行の防止**: `CLAUDECODE` などの環境変数が設定されている端末では、本実行を拒否します。

## 結果の保存先

```
results/<日時>_<課題>_<モデル>_<effort>_x<回数>/
  experiment.json        実験条件（CLI のバージョン、認証方式、プロンプトのハッシュなど）
  summary.json           集計（試行ごとに更新されるので、途中でも確認できます）
  trial_01/
    trial.json           試行の記録（結果、CLI の状態、トークン、API換算コスト、注記）
    workspace/           AI が作った成果物（solution.py など）
    pytest_output.txt    評価の出力
    junit.xml            評価の集計（テスト数・失敗数など）
    claude_stdout.txt    CLI の標準出力（生データ）
    claude_stderr.txt    CLI の標準エラー出力
  trial_02/ ...
```

## 記録する項目と計算方法

- **実行時間**: 外側で測った壁時計時間（`wall_seconds`）。CLI が報告する `duration_ms` と `duration_api_ms` も保存します。
- **トークン**: CLI の `modelUsage`（無ければ `usage`）から取得します。取得できない場合は `null` にし、推測で埋めません。
- **API換算コスト**: 公式の料金表（2026-10-12 確認、単価は `ai_lab/pricing.py`）と、取得したトークン数から計算した推定値です。
  - 単一モデルで `usage.cache_creation` の5分・1時間TTL内訳が書き込み合計と一致する場合は、それぞれの公式単価で計算します（`cost.cache_write_tokens_by_ttl`）。内訳が不明、不一致、または複数モデルの場合は1時間TTLの単価と仮定します（`cache_write_ttl_assumed` と `cost.notes` に記録）。
  - `modelUsage` がない場合は、`usage` のトークン数だけを保存し、実モデルは未確認、API換算料金は `null` とします。
  - Claude Haiku 5.5 は1リクエストのプロンプトが10万トークンを超えると高価格帯になります。CLI の使用量はリクエストを合算した値しか得られないため、基本料金で計算し、平均プロンプトが閾値を超えた試行には注記を付けます。
  - Claude Code が報告する `total_cost_usd` は `cli_usd` として別に保存します（参考値）。Haiku 5.5 では CLI が誤った単価（Opus 5.5 相当）で計算しているため、**Haiku の比較には `api_usd` を使ってください**（第1課題の実機の結果で確認済み）。
- **effort**: `default` はCLIへのフラグ省略として記録し、それ以外は指定値を `--effort` に渡します。Haiku 4.5は `default` だけに対応します。
- **平均API換算料金**: 成否を含む全試行の合計を試行数で割ります。使用量や単価が不明な試行を含む場合は平均を表示しません。旧形式の結果も変更せず読み込めます。

## 注意

- 実験は、サブスクリプションの利用枠を消費します。
- 合否は隠しテストの結果だけで決まります。CLI の異常（`cli_not_ok`）は別に数えます。
- `cost_complete` が `no` の場合、一部の使用量が計算に含まれていません。`trial.json` の `cost.notes` を確認してください。
- 課題は3問です。1回の合否だけで結論を出さず、複数回の合格率・少なくとも1回合格したか・合計コストを比較してください。

## 確認済みの事項と未確認事項（2026-10-10 時点）

**確認済み（第1課題の実機の実行、Claude Code 2.1.286、`duration_parse` を Haiku / Opus で各1回）**

- `claude auth status` の `authMethod` は `claude.ai` でした。
- フラグ（`--effort`、`--tools`、`--safe-mode`、`--no-session-persistence`、`--max-turns`、`--permission-mode`）は、受け付けられて実行されました。
- JSON 出力は1つのオブジェクトで、`usage`、`modelUsage`、`total_cost_usd`、`num_turns`、`permission_denials` などが記録されていました。
- キャッシュ書き込みは全て1時間TTL（`usage.cache_creation`）で、`cache_write_ttl_assumed` の仮定と一致しました。
- Opus 5.5 の API換算コスト（`api_usd`）は、CLI の `total_cost_usd` と一致しました（0.093231 USD）。
- Haiku 5.5 の CLI の `total_cost_usd`（0.082396 USD）は、公式単価の計算（`api_usd` 0.002173 USD）と一致しません。CLI は `claude-haiku-5-5` を認識できず（`unrecognized_model` の警告）、Opus 5.5 の単価で計算していました。

**未確認**

- Pythonコード課題の3条件比較は未確認です。仕様書ベンチマークの保存済み比較は `analysis/` のレポートを参照してください。
- 作業ディレクトリの外にある隠しテストを、AI が読めないことは、権限の仕組みに頼っています（OS のサンドボックスではありません）。Claude Code は既定で起動ディレクトリの中だけを読めるものとして扱い、外側の読み取りは権限の確認になる、と公式ドキュメントにあります。実機の2試行では `permission_denials` が空で、外側の読み取りは確認されませんでしたが、意図的に試したことはありません。
- 利用している Claude Code のバージョンによっては、フラグが使えない場合があります。その場合は `claude --version` を確認し、`--dry-run` の表示とエラーを手がかりに修正してください。
- テストを実行したのは Python 3.14.3 だけです（3.10 以上を想定して書いています）。
