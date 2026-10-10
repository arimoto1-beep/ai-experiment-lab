# ai-experiment-lab
AIの能力・判断・協調・自律性を実験で検証するプロジェクト

## 第1回実験: 安いAIを何度も実行すれば、高性能AIの1回の実行に勝てるか

Claude Haiku 5.5 の複数回実行と、Claude Opus 5.5 の単独実行を比較するための小さな実験ツールです。
Python のプログラミング課題を AI に解かせ、成果物を隠しテストで客観的に評価し、時間・トークン・API換算コストを記録します。
実験は Claude Code CLI のサブスクリプション枠で行い、APIキーや Bedrock などの従量課金は使いません。

現時点の状態: 3問（`duration_parse`、`arithmetic_parser`、`inventory_allocation`）を実装済みです。最初の2問は Haiku 5.5 / Opus 5.5 が初回で全テストに合格しました（第2課題の実行結果はユーザー報告）。第3課題は既存プログラムのバグ修正で、まだ実モデルでは実行していません。

## 構成

| パス | 内容 |
|---|---|
| `ai_lab/` | 実験ツール本体（CLI、Claude Code 呼び出し、評価、集計） |
| `problems/<課題名>/` | 課題。`duration_parse`（期間の解析）、`arithmetic_parser`（四則演算）、`inventory_allocation`（注文の在庫引当のバグ修正）。各課題は `problem.md`（課題文）、`starter/`（初期ファイル）、`tests/`（隠しテスト。AI には渡さない） |
| `tests/` | 開発用テスト。偽の CLI（`tests/fixtures/fake_claude.py`）を使い、実モデルは呼び出さない |
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

pytest の一時ディレクトリにアクセスできない環境では、作業用のパスを指定してください。

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

- `--model`: `haiku` / `opus`、またはモデルID（`claude-haiku-5-5` など）
- `--effort`: `low` / `medium` / `high` / `xhigh` / `max`（既定 `medium`）
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
- **API換算コスト**: 公式の料金表（2026-10-10 取得、単価は `ai_lab/pricing.py`）と、取得したトークン数から計算した推定値です。
  - キャッシュ書き込みは、サブスクリプションのメイン会話の既定である1時間TTLの単価と仮定します（`cache_write_ttl_assumed`）。
  - Claude Haiku 5.5 は1リクエストのプロンプトが10万トークンを超えると高価格帯になります。CLI の使用量はリクエストを合算した値しか得られないため、基本料金で計算し、平均プロンプトが閾値を超えた試行には注記を付けます。
  - Claude Code が報告する `total_cost_usd` は `cli_usd` として別に保存します（参考値）。Haiku 5.5 では CLI が誤った単価（Opus 5.5 相当）で計算しているため、**Haiku の比較には `api_usd` を使ってください**（第1課題の実機の結果で確認済み）。
- **effort**: 指定した値をそのまま `--effort` に渡します。

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

- 第3課題（`inventory_allocation`）は、まだ実モデルで実行していません。Haiku / Opus の差が出る難易度かも未確認です。
- 作業ディレクトリの外にある隠しテストを、AI が読めないことは、権限の仕組みに頼っています（OS のサンドボックスではありません）。Claude Code は既定で起動ディレクトリの中だけを読めるものとして扱い、外側の読み取りは権限の確認になる、と公式ドキュメントにあります。実機の2試行では `permission_denials` が空で、外側の読み取りは確認されませんでしたが、意図的に試したことはありません。
- 利用している Claude Code のバージョンによっては、フラグが使えない場合があります。その場合は `claude --version` を確認し、`--dry-run` の表示とエラーを手がかりに修正してください。
- テストを実行したのは Python 3.14.3 だけです（3.10 以上を想定して書いています）。
