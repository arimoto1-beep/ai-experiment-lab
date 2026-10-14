# 長文情報抽出・条件の組み合わせ実験

仮説は「Haiku 5.5は短い問題の単発推論だけでなく、長い資料から必要な情報を扱う能力が改善している」です。結果を有利にするための課題調整は行わず、生成条件を試験前に固定します。今回の実装では実モデルを呼び出していません。

## 測る能力と条件

比較は Haiku 4.5/default、Haiku 5.5/medium、Haiku 5.5/high の3条件です。Haiku 4.5には `--effort` を渡しません。maxは選択できません。defaultはEffortやThinking予算を追加指定しない意味で、共通の出力上限8000は適用します。この上限自体がThinkingに影響する可能性もあります。純粋なモデル能力比較ではなく、モデルと推論設定の組み合わせによる実用上の比較です。

架空の英語業務マニュアルをPythonの固定シードから生成します。製品・顧客区分・例外規定を分け、費用と処理方法を機械的に決定します。AIによる正解生成は使いません。

1. **実験1**: 指定製品の基本料金と通常の処理方法を抽出する。2項目両方の正解率を主指標にします。根拠は同じ節で、先頭付近・中央・末尾付近に移動します。
2. **実験2**: 製品の料金、別章の顧客割引条件、さらに別章の例外条件を組み合わせ、最終料金と処理方法を答える。割引適用後に追加料金を加え、例外が適用される場合だけ処理方法を変えます。最終2項目両方の正解率を主指標にします。

同じ回答で必要な7事実も個別に回答させます。必要な事実が揃ったのに結論が誤る場合を、検索の失敗と区別します。存在しない対象製品の猶予期間を問う8番目の項目も用意し、適切な `null` と、別製品からの借用・捏造を区別します。

| 因子 | 既定値 | 固定するもの |
|---|---|---|
| 独立問題 | seed 101・103・104 | それぞれ異なるID・料金・適用条件 |
| 資料長 | short 1万 / medium 5万 / long 12万トークン目標 | 問い・正解・根拠の内容 |
| 基本料金の根拠位置 | 約5% / 50% / 95% | 他の2根拠も離したまま位置を循環 |
| 紛らわしさ | neutral / similar | 同じ資料バイト数、レコード数、数値・条件 |
| 独立再実行 | 同じ問題・条件を2回 | 各回は新しい空の作業場所と新規セッション |

similarでは約20%の無関係レコードに対象と似た製品・顧客・規定IDを使います。neutralでは同じ幅の別系統IDを使います。追加資料の事実も明示し、正解に必要な内容は変えません。短文の無関係レコードは、同じシードの長文に同じ順序・同じ内容で含まれます。

文量の効果は同一seed・位置・紛らわしさのshortとlongを比較します。紛らわしさの効果は同じ長さ・seed・位置のneutralとsimilarを比較します。位置の効果は同じ長さ・seed・紛らわしさで比較します。

## 客観採点

| 指標 | 意味 |
|---|---|
| `extraction_correct` | 基本料金・通常処理方法の完全一致 |
| `composition_correct` | 最終料金・最終処理方法の完全一致 |
| `prerequisites_correct` | 組み合わせに必要な7事実が全て正しい |
| `composition_failure_given_correct_facts` | 必要な事実が正しく、最終結論が誤る |
| `fact_accuracy` / `omitted_facts` | 8事実の正解割合 / 必要な値をnullまたは未回答にした数 |
| `fabricated_values` | 同名の事実フィールドとして資料内のどのレコードにも存在しない値と、資料内に存在しない最終処理方法の数 |
| `wrong_entity_values` | 資料にはあるが、指定対象の正解でない値の数 |
| `citation_accuracy` | 8事実と最終結論、計9項目の根拠ID集合の完全一致率 |
| `unsupported_citations` | 提示した事実値を裏付けない根拠IDと、最終結論で無関係な根拠IDを挙げた数 |
| `original_json_valid` / `schema_valid` / `format_compliant` | 生JSON解析、型・項目の遵守、生回答が両方を満たすか |
| `strict_success` | 実行正常・生JSON形式・全事実・結論・根拠が全て正しい |

生JSONが解析できない場合だけ、既存再採点と同じ「外側の単一JSONフェンス除去」を行います。補正後の内容は評価できますが、生回答の形式遵守は失敗のままです。前置き文章からのJSON抽出、欠落項目の補完、数値修復はしません。型不正や不足項目のある回答は、評価できる項目だけの内容点と形式失敗を併記します。

全試行を分母にした率と、モデル・実行・コンテキスト異常を除いた率を併記します。全試行率では異常試行を失敗と数えます。除外数を隠して高い精度を主張しません。境界確認の失敗はモデルの読み取り成績でもあるため、それだけで試行を除外しません。

仮説の中心指標は、同じ問題の **long正解率 − short正解率** です。Haiku 5.5と4.5でこの変化量を比較します。`haiku55_minus_haiku45_change` が正なら、5.5で文量増加に伴う低下が小さい方向です。絶対正解率、medium、位置、紛らわしさ、時間・費用も必ず一緒に示します。両モデルが短文・長文とも全問正解なら、仮説を支持する差を検出できていません。

集計はseedごとに反復を平均してから比較します。反復や配置違いを独立した別問題の数として扱いません。3独立問題だけで有意差や一般的な能力向上を結論づけません。結果を見て問題を増やす場合は、新しいシード群を別セットとして保存してください。

## トークン数、コンテキスト、料金

目標トークン数×4文字のASCII資料を既定で生成します。**4文字/トークンは近似で、Anthropicのトークナイザーによる計測ではありません。** 生成時の `document_tokens_measured` はnullです。全モデルには同じバイト列を渡します。CLIの `usage`・`modelUsage` からモデルごとの入力・キャッシュ読み書き・出力・Thinkingを保存します。入力合計にはCLIのシステムプロンプト等が含まれるため、資料だけの実測トークン数とは呼びません。

Haiku 4.5の公称上限は20万トークンです。[公式モデル仕様](https://platform.claude.com/docs/en/models/haiku-4-5/overview)（2026-10-14確認）。全比較条件に18万トークンの運用上限を置き、推定入力のほかCLI用2万・出力用8000トークンを予約します。出力予算は `CLAUDE_CODE_MAX_OUTPUT_TOKENS=8000` として記録し、Thinkingを出力内訳として扱います。有効な予算を厳密に確認したとは扱いません。

未校正では、UTF-8バイト数を入力の保守的な推定に使います。shortは実行できますが、medium/longは通常、この予算を超えてリクエスト前に拒否されます。short試験のCLI実測入力合計÷プロンプトのバイト数の最大値に15%の余裕を足し、モデルごとの校正値を作ります。校正にもシステム入力が含まれ、さらに2万トークンを予約するため保守的です。

校正は同じ資料生成設定・CLIバージョンでのみ再利用します。推定が上限を超える場合は、目標長・文字/トークンの設定を下げて**全モデル共通の新しい資料**を生成し、新しいshort試験から校正し直してください。特定モデルだけ入力を短くして比較しません。校正は保証ではなく、実測入力＋出力予約が上限を超えた場合は次の試行を停止します。

長文はWindowsのコマンド引数制限を避けて、単一のユーザーメッセージをJSON Linesの標準入力で渡します。`--tools "" --disallowedTools "*" --safe-mode --no-session-persistence --max-turns 1` を使い、MCP・ファイル参照を無効化します。正解はモデルの作業場所にもプロンプトにも置きません。既存のサブスクリプション認証確認と課金用環境変数除去を再利用します。[CLI公式リファレンス](https://code.claude.com/docs/en/cli-reference)。

`--replay-user-messages` の再送内容と送信SHA256の一致、実モデルID、報告コンテキスト窓、assistantの使用量、観測できた圧縮イベント・ツール使用を保存します。モデル不一致、受信内容不一致、観測された圧縮、複数ターン、使用量不明、上限超過は後続試行を停止します。生stdout/stderrも保持します。モデルに資料の先頭・中央・末尾にある確認値を返させますが、その一致は資料全体の保持を証明しません。

**CLIの受信一致は、APIに資料全体が渡った証明ではありません。圧縮イベントが見えないことも、圧縮なしの証明ではありません。** `api_payload_integrity`、`truncation_status`、観測されなかった圧縮は `unverified` のままです。キャッシュ率も条件ごとに確認してください。

既存料金計算を使い、この実験に限ってHaiku 5.5の長文料金を補います。入力＋キャッシュ読み書きの合計が10万トークンを超える報告単一ターンでは、入力$0.50・出力$2.50・5分書込$0.625・1時間書込$1.00・読込$0.05/100万トークンを使います。10万以下は既存単価です。[公式料金表](https://platform.claude.com/docs/en/about-claude/pricing)（2026-10-14確認）。複数ターンの合計からリクエスト別の料金帯を決めず、費用を未確定として参考範囲だけ保存します。単一ターンでも内部リトライを厳密に排除できません。既存実験の料金処理や過去結果は変更しません。

ローカルCLI **2.1.286** で標準入力・再送・safe mode関連のヘルプを確認済みです。ただし、[Haiku 5.5はClaude Code 2.1.293以降を使用](https://code.claude.com/docs/en/model-config)してください。新しい実験は古いバージョンでの5.5呼び出しを拒否します。CLIの更新は今回行っていません。

## 生成・検証・少数試験

まず資料と正解だけを作り、実行件数・概算を確認します。生成物は既存方針どおり `results/` に置き、Git管理外です。既存の資料・結果ディレクトリは上書きしません。

```powershell
python -m ai_lab.long_context_benchmark generate --output-dir results/long_context_corpus
python -m ai_lab.long_context_benchmark validate results/long_context_corpus
python -m ai_lab.long_context_benchmark plan results/long_context_corpus --runs 2
python -m pytest tests/test_long_context.py -q
```

### 9万トークン相当の追加資料

`long90k` は9万トークン目標（既定では36万ASCII文字）の追加設定です。既定の生成対象は引き続きshort・medium・longの54件で、12万トークン版のlongも残します。同じseed・位置・紛らわしさなら、問い、採点対象の事実、最終正解、根拠ID・本文は同じです。資料長に伴い根拠の文字位置と無関係レコード数は変わりますが、根拠の相対配置とsimilarの頻度（約20%）を維持します。

既存資料を上書きせず、別のコーパスへ生成します。4文字/トークンの近似設定を変えないので、同じ設定から作った中程度の校正値を利用できます。以下は生成・検証・dry-runだけで、実モデルを呼びません。

```powershell
python -m ai_lab.long_context_benchmark generate --output-dir results/long_context_corpus_90k --seeds 101 --lengths long90k --positions middle --distractions similar
python -m ai_lab.long_context_benchmark validate results/long_context_corpus_90k

$corpus = "results/long_context_corpus_90k"
$cal = "results/long_context_calibration_medium_20261014.json"
python -m ai_lab.long_context_benchmark run $corpus --case-id s101_long90k_middle_similar --model haiku45 --calibration $cal --limit 1 --dry-run
python -m ai_lab.long_context_benchmark run $corpus --case-id s101_long90k_middle_similar --model haiku --effort medium --calibration $cal --limit 1 --dry-run
python -m ai_lab.long_context_benchmark run $corpus --case-id s101_long90k_middle_similar --model haiku --effort high --calibration $cal --limit 1 --dry-run
```

校正値がない場合や推定が上限を超える場合は、安全チェックを通過しません。上限18万・CLI用2万・出力用8000の予約は変更しません。dry-runの通過は、実モデルの入力実測やコンテキスト保持の保証ではありません。

独立したPowerShellで、**同じ1問題を各条件1回、計3回**から始めます。まず `--dry-run` 付きで条件を確認してください。dry-runはClaudeを起動せず、校正なしの長文も条件表示だけを行います。実実行ではコンテキスト検査が別途働きます。

```powershell
python -m ai_lab.long_context_benchmark run results/long_context_corpus --case-id s101_short_middle_similar --model haiku45 --limit 1 --dry-run
python -m ai_lab.long_context_benchmark run results/long_context_corpus --case-id s101_short_middle_similar --model haiku45 --limit 1
python -m ai_lab.long_context_benchmark run results/long_context_corpus --case-id s101_short_middle_similar --model haiku --effort medium --limit 1
python -m ai_lab.long_context_benchmark run results/long_context_corpus --case-id s101_short_middle_similar --model haiku --effort high --limit 1
```

JSON形式、モデルID、再送ハッシュ、実測トークン、Thinkingの報告有無、壁時計時間、料金を確認します。3試行の保存先を使って校正します。Thinkingが未報告ならnullで、ゼロと解釈しません。

```powershell
python -m ai_lab.long_context_benchmark calibrate "results/long_context_runs/<Haiku45試験>" "results/long_context_runs/<Haiku55-medium試験>" "results/long_context_runs/<Haiku55-high試験>" --output-file results/long_context_calibration.json
```

次は同じseed・位置・紛らわしさのmedium、最後にlongを、3条件各1回ずつ計6回追加する計画です。たとえば：

```powershell
python -m ai_lab.long_context_benchmark run results/long_context_corpus --case-id s101_medium_middle_similar --model haiku45 --calibration results/long_context_calibration.json --limit 1
python -m ai_lab.long_context_benchmark run results/long_context_corpus --case-id s101_long_middle_similar --model haiku45 --calibration results/long_context_calibration.json --limit 1 --dry-run
```

同じコマンドのモデル設定をmedium/highにも変えます。初回longの実測・エラーを見て、長さとコンテキスト余裕を固定します。**今回、これらの実モデル試験は未実施です。** 既定 `--limit 1` で、多数の試行を自動で開始しません。

## 本番規模と分析

既定資料54件 × 2反復 × 3条件 = **324呼び出し、648問相当の回答**です。同じ応答に実験1と2の回答を含むため、648回モデルを呼ぶわけではありません。独立した業務問題は3個であり、54個の独立問題ではありません。

目標入力＋CLI入力2万、出力2000、キャッシュなしというシナリオと、全入力が1時間キャッシュ書込・出力8000というシナリオでAPI換算額を出します。324件の初期概算は **約$16〜$35** です。Thinkingは出力に含みます。キャッシュ読込なら下がることがあり、再試行や実測長の増加なら上がります。これは保証された上下限でも、サブスクリプション実支出でもありません。

各呼び出し60〜300秒を仮定すると、逐次実行で **約5.4〜27時間** です。長文モデルの実測に基づく予測ではありません。少数試験後に `trials.csv` の実測時間・入力・出力から再見積もりしてください。highが同じ出力予算内でも長くかかる可能性があります。

本番を行うと判断した後にだけ、たとえば1条件の全54件を2回ずつ実行するには `--runs 2 --limit 108 --calibration ...` を指定します。3条件を同じ順序で実行せず、ブロックごとにモデル順を変え、曜日・時間帯・キャッシュ・CLI版の差も記録してください。ケース順は `--schedule-seed` から再現できます。異常停止時に未実行の問題は自動再試行せず、原因を確認します。

```powershell
python -m ai_lab.long_context_benchmark report "results/long_context_runs/<実験A>" "results/long_context_runs/<実験B>" "results/long_context_runs/<実験C>" --output-dir analysis/long_context_comparison
```

`trials.csv` に個別の正誤・時間・入出力/キャッシュ/Thinking・費用・異常を、`summary.csv` に問題seed・長さ・位置・紛らわしさ別の反復集計を出します。対応する短文・長文がある場合は `paired_length_changes.csv`、さらに同じ問題の4.5/5.5がある場合は `hypothesis_comparisons.csv` を出します。未対応の組み合わせに差を捏造しません。CSVとレポートだけを必要に応じてGit管理し、詳細 `analysis.json` と元結果はGit管理外です。

## 保存物と限界

生成資料には `manual.txt`、`question.json`、`answer_key.json`、`prompt.txt`、設定とSHA256の `case.json` があり、コーパス全体のmanifestも保存します。正解にはフィールド値、根拠ID、根拠文字位置、資料内の値一覧を含みます。実験は資料・正解のスナップショット、CLI版、モデル・推論設定、校正、順序、コードSHA256を保存します。各試行は送信JSONL、回答、生ログ、採点、使用量、文脈診断を保存します。

英語・構造化された架空マニュアルの検索と簡単な算術に限られます。日本語、自然な長文、コード変更、ツール利用、多ターン開発全体の評価ではありません。無関係情報には定型文と同幅のレコードを使い、現実の重複・改訂履歴・曖昧さを完全には再現しません。必要な事実を回答に明示させる指示自体が組み合わせの補助になります。

根拠の文字位置は正確に保存しますが、実トークン列の位置は未測定です。入力長・根拠の距離・無関係情報数には関連が残ります。similarの「似たID」による難しさを、全種類の紛らわしさに一般化しません。null項目は捏造の限定的な対照で、自由文の全ての捏造を検出するものではありません。資料内にある別対象の値は、完全な捏造とは分けて報告します。

CLIの内部入力、管理ポリシー、課金帯のリクエスト単位、圧縮、応答の確率的変動には観測の限界があります。実モデル試験でこれらが不明のままなら、不明であることを結果に残します。未実施の結果や仮説の支持・否定は作りません。
