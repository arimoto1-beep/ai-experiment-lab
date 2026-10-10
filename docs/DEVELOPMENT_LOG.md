# 開発ログ: 第1回実験（安いAIの複数回実行 vs 高性能AIの単独実行）

記録日: 2026-10-10。開発中に発生した問題、その原因と修正、判断の理由、検証の範囲を後から追えるように残す。

## 1. 守った制約

- 開発中に使用するモデルは Claude Haiku 5.5 のみ（この開発では、実験対象モデルを一度も呼び出していない）。サブエージェントは起動していない。公式ドキュメントの取得（WebFetch）は、取得後の要約を内部の小型モデルで行うが、そのモデルはこちらから指定していない。
- Claude Code CLI の入れ子実行はしていない。テストは `tests/fixtures/fake_claude.py`（偽の CLI）で行い、本物の `claude` は `tests/conftest.py` の設定で探索できないようにした。
- 実験結果とトークン使用量は作っていない。テストに出てくる数値（100 / 50 / 3000 / 2000 トークンなど）は、偽の CLI が返す固定値であり、実験結果ではない。
- GitHub への push はしていない（人間の確認後に行う）。コミットもしていない（変更は作業ツリーに残してある）。

## 2. 判断事項と理由

| 判断 | 理由 |
|---|---|
| 課題は `duration_parse`（期間文字列を秒数に変換する関数）1問 | 指示どおり、まずは1問で動作確認できれば十分とした。仕様の境界（空白、大文字小文字、重複単位、不正入力）が多く、モデルによって差が出やすい。 |
| AI にはコードを実行させない（ツールは Read / Write / Edit のみ） | 1回の生成の質を測る設計にした。Bash を与えると試行ごとの作業量が変わり、比較の条件がずれるため。将来の拡張候補。 |
| 隠しテストは `problems/<課題>/tests/` に置き、作業ディレクトリにはコピーしない | AI がテストを見たり書き換えたりできないようにするため。作業ディレクトリ外は読まない旨も指示する。 |
| `claude -p` の課題文は引数で渡す | 公式ドキュメントの基本形で、`claude.exe` を直接起動するため cmd.exe を通らない。 |
| `--safe-mode` を付ける | CLAUDE.md・フック・MCP を読み込まず、全試行の条件を揃えるため。認証は通常どおり使われる（公式ドキュメント）。 |
| `--bare` は使わない | 公式ドキュメントに、--bare は OAuth（サブスクリプション）を読まず、APIキーを要求すると書かれているため。 |
| `--effort` の既定値は `medium` と明示する | 記録を曖昧にしないため。Claude Code の既定値に任せると、記録から実際の値が分からなくなる。 |
| 試行の前に `claude auth status` を確認する | authMethod が `claude.ai` / `oauth_token` 以外（APIキーなど）なら実行しない。従量課金を防ぐため。 |
| 子プロセスから `ANTHROPIC_API_KEY` などを取り除く | 環境に APIキーがあっても、サブスクリプションの認証だけを使うため。 |
| API換算コストは公式単価 × トークン数で計算し、CLI の `total_cost_usd` は参考値として別に保存する | 単価と計算式を明示できるようにするため。CLI の値は、CLI 内部の単価表に依存する。 |
| キャッシュ書き込みは1時間TTLの単価と仮定する | 公式ドキュメントに、サブスクリプションのメイン会話は既定で1時間TTLだと書かれているため。実際の内訳は取得できないので、仮定として記録する（`cache_write_ttl_assumed`）。 |
| Haiku 5.5 の10万トークン超の高価格帯は基本料金で計算する | 高価格帯はリクエスト単位で決まるが、CLI の使用量は合算値しか得られないため。平均プロンプトが閾値を超えた試行には注記を付ける。 |

## 3. 料金と CLI 仕様の確認方法

- **単価**: 公式の料金表（`https://platform.claude.com/docs/en/about-claude/pricing`）を WebFetch で取得し、Opus 5.5 と Haiku 5.5 の行を確認した。claude-api スキルの表（2026-10-06 時点）とは、入力・出力単価が一致した。Opus 5.5 のキャッシュ単価もスキル内の記述と一致した（Haiku 5.5 のキャッシュ単価はスキルに記載がなく、料金表の値を採用した）。
  - Opus 5.5: 入力 $4 / 出力 $20 / キャッシュ書き込み 5分 $5・1時間 $8 / キャッシュ読み出し $0.20（MTok）。
  - Haiku 5.5（10万トークン以下）: 入力 $0.10 / 出力 $0.50 / 書き込み 5分 $0.125・1時間 $0.20 / 読み出し $0.01。
  - Haiku 5.5（10万トークン超）: 入力 $0.50 / 出力 $2.50 / 書き込み 5分 $0.625・1時間 $1 / 読み出し $0.05（未反映。注記で対応）。
- **CLI のフラグ**: 公式 CLI リファレンス（`https://code.claude.com/docs/en/cli-reference`）で確認した。`--effort`、`--tools`、`--permission-mode`、`--max-turns`、`--no-session-persistence`、`--safe-mode`、`--output-format json`。
- **JSON の項目**: 公式ドキュメント（コスト追跡、ヘッドレス実行）と、インストール済みの `claude.exe` の中の文字列を読んで確認した（`total_cost_usd`、`duration_api_ms`、`num_turns`、`modelUsage`、`costUSD`、`inputTokens`、`cacheReadInputTokens`、`cacheCreationInputTokens`）。`claude.exe` は実行していない（読み取りのみ）。
- **ツール名**: `Read`、`Write`、`Edit`、`Bash` を公式のツール一覧で確認した。

## 4. 発生した問題と修正

### P-1: pytest の一時ディレクトリにアクセスできず、`tmp_path` を使うテストが全件エラー（環境の問題）

- 症状: 初回の `python -m pytest` で、`tmp_path` を使うテストが setup の段階で ERROR になった（`PermissionError: [WinError 5] アクセスが拒否されました: 'C:\Users\aricy\AppData\Local\Temp\pytest-of-aricy'`）。`tests/test_problems.py` のように `tmp_path` を使わないテストは通った。
- 原因: 既存の `%TEMP%\pytest-of-aricy` へのアクセスが拒否されている。`icacls` で ACL を見ようとしたところ、同じく拒否された。**根本原因（ACL か、別プロセスによるロックか）は未特定。**
- 対処: 既存のディレクトリは削除せず、リポジトリ外のスクラッチ領域を `--basetemp` に指定して実行した。
- 結果: 全テストが通った（上記の `--basetemp` 指定時）。
- 残課題: ユーザー側の環境で同じ問題が出る場合は、`--basetemp` を指定するか、`%TEMP%\pytest-of-<ユーザー名>` の権限を確認する（README にも記載）。

### P-2: `.cmd` ラッパーの場合に課題文の記号が崩れるおそれ（47件の合格後のレビューで発見、修正してテストを追加）

- 内容: npm 版の `claude.cmd` のような `.cmd` / `.bat` は cmd.exe を経由して起動される。課題文には `|`（表）、`"`（例）、改行が含まれるため、引数が崩れて別のプロンプトで実行されるおそれがあった。
- 修正: `check_native_executable()` を追加し、`.cmd` / `.bat` を拒否して `--claude-bin` で `claude.exe` を指定するよう案内する。`find_claude_command()` と `--claude-bin` の両方で検査する。
- 検証: `tests/test_claude_cli.py::test_cmd_wrapper_is_refused_so_the_prompt_is_not_mangled_by_cmd_exe`。

### P-3: `claude auth status` が止まると、起動確認で例外の詳細がそのまま出る（47件の合格後のレビューで発見、修正してテストを追加）

- 内容: 起動確認の `subprocess.run` に timeout を付けていたが、`TimeoutExpired` が捕まらず、トレースバックが出る状態だった。
- 修正: `preflight()` で `TimeoutExpired` を `RuntimeError`（「起動確認がタイムアウトしました」）に変換する。
- 検証: `tests/test_claude_cli.py::test_preflight_reports_a_hung_cli_as_an_error`（偽の CLI の `FAKE_CLAUDE_AUTH_SLEEP` を使用）。

### P-4: テスト間で定数を共有するため `from .conftest import ...` と書いたが、`tests/` がパッケージではないため動かない（書いている途中に発見、テスト実行前に修正）

- 修正: 定数は各テストモジュールに直接書いた。`conftest.py` にはフィクスチャだけを残した。

## 5. 検証結果

| 実行内容 | 結果 |
|---|---|
| `python -m pytest --basetemp=<スクラッチ>`（修正前、47件） | 47 passed（16.67 秒） |
| 同（P-2、P-3 の修正後、49件） | 49 passed（17.62 秒） |
| `python -m ai_lab run --problem duration_parse --model haiku --effort medium --runs 3 --dry-run` | 実行コマンドと環境を表示。`results/` は作られない。モデルは呼ばない。 |
| `python -m ai_lab run --model opus --runs 1 --dry-run` | 同上（Opus の表示確認） |
| スクラッチ領域での結合確認（偽の CLI で `run_experiment` を2試行、`report` まで実行） | 成果物の配置（`workspace/solution.py` だけで、テストはない）、`trial.json`、`summary.json`、比較表の表示を確認。**偽の値による表示確認であり、実験結果ではない。** |

テストの内容:

- **料金**: Opus / Haiku の単価、キャッシュ書き込みの TTL 別単価、モデル名の対応づけ（日付付きの ID を含む）。
- **CLI の呼び出し**: 必須フラグ、`--bare` を使わないこと、APIキーの除去、入れ子実行の検出、出力の解析（オブジェクト・配列・前後に余計な行がある場合）、状態の判定（ok / error / timeout / unparsed）、認証の確認（サブスクリプション以外は拒否、未ログイン、起動確認のタイムアウト）、`.cmd` の拒否。
- **評価**: 参照解は全件合格（29件）、素朴な不完全解は不合格、解答なし・構文エラー・無限ループは不合格（タイムアウトも記録）、評価で作業ディレクトリが汚れないこと。
- **試行の独立性と記録**: 試行ごとに別の作業ディレクトリ、APIキーが子プロセスに渡らないこと、作業ディレクトリに隠しテストがないこと、CLI の異常でも成果物を評価すること、タイムアウト・解析不能時はトークンとコストを `null` にすること、コストの計算（偽の値で検算）、Haiku の高価格帯の注記。
- **CLI**: dry-run が本実行をせず `results/` を作らないこと、入れ子実行を拒否すること、未知のモデル・不正な試行回数・存在しない `claude` のパスを拒否すること、比較表の表示。
- **課題**: 課題文に隠しテストの内容が含まれないこと、初期ファイルが `solution.py` だけであること、課題名の検証。

## 6. まだ確認できていないこと（未検証）

> 2026-10-10 追記: 第1課題の実機の初回実行（ユーザーが実施）で確認できた項目は、第8.4節に記載しました。以下の一覧は、実機の実行より前に書いたものです。

- **実際の Claude Code CLI の実行（未実施）。** 開発中は入れ子実行を避けるため、一度も本物の `claude` を起動していない。次の確認が必要:
  - JSON 出力に `usage`、`modelUsage`、`total_cost_usd`、`num_turns`、`subtype`、`is_error` がその形式で入っているか。
  - `--effort`、`--safe-mode`、`--tools`、`--no-session-persistence`、`--max-turns` が、利用中のバージョンで使えるか。
  - `claude auth status` の `authMethod` が、サブスクリプションでのログイン時に `claude.ai` になるか。
  - 課題文を引数で渡したときに、Haiku / Opus が正しく `solution.py` を書くか。
- **キャッシュ書き込みの TTL の内訳**: 実際の内訳は取得していない。1時間TTLの仮定が正しいかは未確認。
- **Haiku 5.5 の高価格帯**: 基本料金で計算している。平均プロンプトが閾値を超えた試行には注記が出る。
- **課題の難易度**: 1問のみ。Haiku と Opus の差が出る課題かどうかは未確認。
- **料金の更新**: 単価は 2026-10-10 時点の値。料金表が変わった場合は `ai_lab/pricing.py` を更新する。

## 7. 次の作業（人間の確認後）

1. 独立したターミナルで `--runs 1` の動作確認を行い、`claude_stdout.txt` と `trial.json` を確認する。
2. 出力形式が想定と違う場合は `ai_lab/claude_cli.py` と `ai_lab/experiment.py` を直す（テストに実際の出力形式を反映する）。
3. 本実験（Haiku 複数回、Opus 単独）を実行し、`report` で比較する。
4. 結果を確認してから、コミットと push を判断する。

## 8. 第2課題: arithmetic_parser（四則演算の数式パーサー）

記録日: 2026-10-10。依頼: 第1課題より難しく、能力差が出やすい課題の追加。制約は第1課題と同じ（Haiku 5.5 のみ、入れ子実行なし、実モデルの実行なし、commit / push なし）。

### 8.1 追加・変更したファイル

| ファイル | 種別 | 内容 |
|---|---|---|
| `problems/arithmetic_parser/problem.md` | 追加 | 実験対象AIに渡す仕様書（課題文） |
| `problems/arithmetic_parser/starter/solution.py` | 追加 | 初期ファイル（`NotImplementedError` を送出する関数） |
| `problems/arithmetic_parser/tests/test_solution.py` | 追加 | 隠しテスト（評価専用）。165 件 |
| `tests/fixtures/arithmetic/reference.py` | 追加 | 参照実装（正解）。AI には渡さない |
| `tests/fixtures/arithmetic/eval_based.py` | 追加 | 不完全な実装（`eval()` を使う変異体） |
| `tests/test_problem_arithmetic_parser.py` | 追加 | 参照実装の合格、変異体の不合格、期待値の検算（281 件） |
| `tests/test_problems.py` | 変更 | 両課題を対象にするようパラメータ化（テストのみ） |
| `ai_lab/report.py` | 変更 | `cli_usd` の注記の文言だけを変更（計算は変えていない） |
| `README.md` / `docs/DEVELOPMENT_LOG.md` | 変更 | 課題の説明、実行手順、確認済み・未確認の事項 |

既存の実行基盤（実行・評価・記録の処理）は変更していません。課題の追加に必要なのは `problems/` 以下の3ファイルだけで、`load_problem` と `evaluate` はそのまま使えます。

### 8.2 仕様の要点と判断

課題文は、隠しテストで判定できるように具体化しました。実装ごとに解釈が分かれやすい点は、次のとおり明記しています。

- **空白**: 半角スペース、タブ、改行に限定しています（全角スペースや NBSP は定義していません。テストもしていません）。
- **構文の検査が先**: `1/0+` は `ValueError`（ゼロ除算より構文エラーを優先）。
- **単項演算子**: 連続できる（`--3`）。二項演算子の直後にも置ける（`2*-3`）。乗除算より強く結びつく。
- **数値**: 先頭の `0` は可（`007`）。小数点は1つで、前後に数字が必要（`1.`、`.5` は不正）。指数（`1e3`）、桁区切り（`1_000`）、16進数（`0x1F`）は不正。
- **括弧**: 入れ子は少なくとも50段。`()` は不正。
- **戻り値**: 整数の結果も `float`（`5.0`）。判定は相対誤差 `1e-9`（期待値が0のときは絶対誤差 `1e-12`）。
- **禁止事項**: `eval`、`exec`、`compile`、`__import__`、`ast` の import、外部の数式ライブラリ。隠しテストは AST で検査しますが、`getattr` などで名前を組み立てる迂回は検出できません。

### 8.3 検証結果

- **隠しテスト**: 165 件（有効な式 91、不正な式 54、構文エラーとゼロ除算の組み合わせ 6、ゼロ除算 13、禁止事項 1）。参照実装は全件合格。
- **不完全な実装（変異体）8 種**: 全て不合格になり、想定したテストで落ちることをテスト名で照合しました。
  - 置換で作った7種: 優先順位なし（`same_precedence`）、加減算の右結合（`right_assoc`）、単項演算子なし（`no_unary`）、小数なし（`integers_only`）、整数の結果を `int` で返す（`int_result`）、解析後の残りを無視（`trailing_ignored`）、構文検査の前にゼロ除算を送出（`zero_check_at_parse_time`）。
  - `eval()` を使う変異体（`eval_based`）: 不正な式の検査と禁止事項の検査で落ちる。
- **期待値の独立検算**:
  - 有効な式 91 件: CPython の式評価（別実装の構文解析と計算）と、Fraction による有理数の厳密計算のいずれとも一致。
  - 不正な式 54 件: 37 件は CPython も構文エラー。残り 17 件（`1e3`、`2(3)`、`()`、`a+1` など）は CPython が受理するため、理由を記録しました（仕様では不正）。一覧の項目が本当に受理されることも確認しています。
  - ゼロ除算 13 件: 構文は正しく、CPython でも `ZeroDivisionError`。
  - 構文エラーとゼロ除算の組み合わせ 6 件: CPython でも構文エラー。
  - 検算が誤りを検出できることも確認しました。別のスクリプトで、優先順位・右結合・単項演算子の誤った期待値4件を与えると不一致になり、正しい期待値は一致しました。
- **全テスト**: `python -m pytest` で 332 件合格（既存 49 件、第2課題の検証 281 件、`tests/test_problems.py` の追加 2 件）。`duration_parse` の既存テストを含みます。

### 8.4 実機の初回実行（第1課題、ユーザーが実施）から判明したこと

ユーザーが独立したターミナルで実行した `duration_parse` の結果（`results/` にある2件）を確認しました。この作業では、実モデルは実行していません。

- 両方とも 29 件中 29 件合格。CLI の状態は ok、`cost_complete` は yes。
- Claude Code 2.1.286。`authMethod` は `claude.ai`。
- CLI の JSON 出力は、実装が想定していた形式どおり（1オブジェクト、`usage`、`modelUsage`、`total_cost_usd`、`permission_denials` など）。
- キャッシュ書き込みは全て1時間TTL（`usage.cache_creation.ephemeral_1h_input_tokens`）で、仮定と一致。
- **Opus 5.5**: API換算コスト 0.093231 USD（公式単価で計算）と、CLI の `total_cost_usd` 0.0932314 USD が一致。
- **Haiku 5.5**: API換算コスト 0.002173 USD（公式単価）に対し、CLI の `total_cost_usd` は 0.082396 USD。内訳（入力6、出力1935、キャッシュ読み22600、キャッシュ書き込み4894）を Opus 5.5 の単価（$4 / $20 / $0.20 / $8）で計算すると、ちょうど 0.082396 USD になります。CLI は `costBasis: unknown` と `unrecognized_model` の警告を出しており、Haiku 5.5 を認識していません。→ Haiku の比較には `api_usd` を使います。`report` の注記も更新しました。
- `permission_denials` は両方とも空。

### 8.5 開発中に発生した問題と修正

- **P-5（検算の出力）**: CPython で `2(3)` と `(1)(2)` を評価すると `SyntaxWarning` が出ました。検算の目的では不要なので、`warnings.catch_warnings()` で抑制しました（結果には影響しません）。
- 上記以外に、テストの失敗は出ませんでした。初回の実行で、検証281件と隠しテスト165件（参照実装）は全件合格しています。

### 8.6 未解決の問題

1. **隠しテストが作業ディレクトリから参照可能（制約）**: 隠しテストは `problems/arithmetic_parser/tests/test_solution.py` にあり、作業ディレクトリ（`results/<実験>/trial_NN/workspace/`）からは相対パス `../../../../problems/...` で指せます。
   - 既定の動作: 公式ドキュメントによると、Claude Code は起動したディレクトリの中のファイルを権限の確認なしで読めます。外側の読み取りは権限の確認になり、`-p` では確認に答える相手がいないため拒否されるものと考えられます（推定。実機で意図的に試していません）。
   - 実機の結果: 第1課題の2試行とも `permission_denials` が空でした。外側の読み取りを試みた形跡はありません。
   - 隔離の強さ: OS のサンドボックスではなく、権限の仕組みに頼っています。プロンプトにはテストの場所を書いていません。
   - 強化の候補（未適用。基盤の変更になるため）:
     - (a) `permissions.blockReadsOutsideWorkingDirectories` を有効にする。設定の索引には「every permission mode で、ファイルツールが作業ディレクトリ外の読み取りを拒否する」とあります。`--settings` で渡せるか、どのバージョンから有効かは未確認です。
     - (b) 試行用の作業ディレクトリをリポジトリの外（例: `%TEMP%`）に置く。
     - どちらも、実機で数試行のログを見て効果を確認してから採用するのがよいと考えます。
2. **AI がコードを実行できない**（設計どおり）。難しい課題ほど、実装の誤りを本人が見つけられません。結果が能力ではなく「実行できないこと」で決まる可能性があります。
3. **課題文が長い**（約2,100字）。仕様を詳しくしたことで、実装の差が出にくくなる可能性もあります。課題文の妥当性は、人のレビューを待っています。
4. **第2課題の実モデル実行は未実施**です。
5. **CLI の Haiku 単価の誤り**は Claude Code 側の問題で、このプロジェクトでは修正できません。本リポジトリは公式単価で計算しています（`ai_lab/pricing.py`）。
6. 観測した不一致（記録のみ）: CLI は Haiku 5.5 の `contextWindow` を 200000 と報告しています。skill 内の料金・モデル表（2026-10-06 時点）は 1M と記載しています。今回の計算には使っていません。

### 8.7 実モデルで第2課題を1回実行するコマンド

独立したターミナルで、1回ずつ実行してください（この作業では実行していません）。

```
python -m ai_lab run --problem arithmetic_parser --model haiku --effort medium --runs 1
python -m ai_lab run --problem arithmetic_parser --model opus --effort medium --runs 1
python -m ai_lab report results\<Haiku の実験フォルダ> results\<Opus の実験フォルダ>
```

## 9. 第3課題: inventory_allocation（注文の在庫引当のバグ修正）

記録日: 2026-10-10。最初の2課題で両モデルが初回合格したとのユーザー報告を受け、
既存コードの理解と修正を測る課題を1問追加しました。実モデルの実行、commit、push はしていません。

### 9.1 追加・変更したファイル

| ファイル | 内容 |
|---|---|
| `problems/inventory_allocation/problem.md` | AIに渡す仕様。入力、優先度・受付順、明細合算、注文単位の引当、入力保持を定義 |
| `problems/inventory_allocation/starter/solution.py` | 4つの不具合を含む実行可能な初期実装 |
| `problems/inventory_allocation/tests/test_solution.py` | 独立した採点テスト36件。参照実装をimportせず、固定期待値で評価 |
| `tests/fixtures/inventory/reference.py` | 正しい参照実装。AIには渡さない |
| `tests/test_problem_inventory_allocation.py` | 課題の検証36件。期待値検算28件、参照・初期実装の評価2件、単独不具合4件、偽CLI2件 |
| `tests/test_problems.py` | 新課題を既存の課題文・配布ファイル検証に追加（2件増加） |
| `README.md` | 第3課題の説明と実行コマンドを追加。第2課題の状態をユーザー報告に合わせて更新 |

`ai_lab/`、既存課題のソース・採点テスト、依存関係は変更していません。
既存の `load_problem`、試行ごとの初期実装コピー、`evaluate` をそのまま使います。
AIに渡すものは仕様のプロンプトと `starter/solution.py` だけです。
Read / Write / Edit の設定とコード実行なしの条件も既存のままです。

### 9.2 仕込んだ不具合と独立検出

| 不具合 | 初期実装の挙動 | 代表的な検出テスト | 単独の不具合を戻した場合の採点結果 |
|---|---|---|---|
| 同順位の順序 | 受付順の代わりに注文IDで並べる | `test_fifo[scarce_stock]` | 30合格 / 6不合格 |
| 同一商品の合算 | 同じ商品の前の数量を上書きする | `test_duplicate_quantities[total_exceeds_stock]` | 27合格 / 9不合格 |
| 拒否時の原子性 | 後の明細が不足しても、前の明細の在庫を減らしたままにする | `test_rejection_is_atomic[followup_uses_unspent_stock]` | 30合格 / 6不合格 |
| 入力在庫の保持 | 入力辞書を直接変更し、戻り値とも共有する | `test_stock_is_unchanged[accepted]` | 32合格 / 4不合格 |

各単独不具合の実装で、他の3つの代表テストは合格することも検証しています。
参照実装にこの4つの不具合だけを戻すと初期実装と同じコードになることを、
冒頭の説明文を除いたASTの比較で確認しています。
単純な構文エラーはありません。

### 9.3 検証結果

- 採点テスト36件: 通常動作12件、受付順4件、明細合算5件、拒否時の在庫保持4件、
  複合条件3件、入力在庫保持2件、注文・明細保持1件、入出力辞書の独立性2件、
  複数呼び出しの独立性1件、明細順に依存しないこと2件。
- 参照実装: **36 / 36合格**、失敗・エラー・スキップ0件。
- バグ入り初期実装: **13合格 / 23不合格**、エラー・スキップ0件。
  4つの代表テストすべてが不合格、通常動作12件はすべて合格。
- 固定期待値28件: 受付可否の全組合せ（最大32通り）を列挙し、処理順に従って受付を
  優先した実現可能な組合せから検算。参照実装の逐次引当アルゴリズムは使用しない。
- 偽CLI: Haiku / Opus の両指定で、初期実装だけの作業ディレクトリ、課題文だけのプロンプト、
  `Read,Write,Edit`、採点結果の記録を確認。本物のClaude CLIは起動していない。
- 変更前の既存テスト: **332件合格**。既存のpytestキャッシュへの書き込みで警告が1件出たため、
  以下の確認ではキャッシュを無効にした。
- 新課題検証と課題管理テスト: **44件合格**（7.63秒）。
- 全体: **370件合格**（33.14秒）。既存332件に新課題の検証36件と課題管理検証2件を追加。
- 新課題のHaiku 3回の `--dry-run` は正常終了。実モデルは呼び出していない。

実行した検証コマンド:

```
python -m pytest tests/test_problem_inventory_allocation.py tests/test_problems.py -q -p no:cacheprovider --basetemp=results/inventory-validation
python -m pytest -q -p no:cacheprovider --basetemp=results/inventory-full-validation
```

`results/` 配下の検証用ディレクトリには、参照実装・初期実装・単独不具合の採点ログと
JUnit XMLが残ります。Git管理対象ではありません。開発中はローカルのPython 3.14.3を使用しました。

### 9.4 実モデルで実行するコマンド

独立したターミナルで実行してください。同じeffortでHaikuの独立3試行とOpusの1試行を比較します。

```
python -m ai_lab run --problem inventory_allocation --model haiku --effort medium --runs 3
python -m ai_lab run --problem inventory_allocation --model opus --effort medium --runs 1
python -m ai_lab report results\<Haiku の実験フォルダ> results\<Opus の実験フォルダ>
```

### 9.5 未解決・未確認

- 実モデルでの実行は未実施。両モデルの差が出る難易度かは未確認。
- AIへの配布から隠しテスト・参照実装を除外することは検証済みですが、作業域外の
  読み取り拒否は既存のClaude CLIの権限管理に依存します。実機で意図的に域外読み取りを
  試した検証は、今回も行っていません。第8.6節の既知の制約を引き継ぎます。
