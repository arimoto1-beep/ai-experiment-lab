# 複数ファイル開発実験（Haiku 4.5 / 5.5）

## 固定済みの課題

- `parcel_manifest`: 受付行の集約、送料計算、集計を複数モジュールで修正する。
- `room_booking`: 優先順位、区間の重なり、予約時間、入力の独立性を複数モジュールで修正する。

各課題の `manifest.json` は課題文、初期コード、公開テスト、非公開テストの SHA-256 を固定しています。実行前に全ファイルを照合し、変更や追加があれば停止します。モデルの結果を見た後に課題を調整する場合は、別バージョンとして扱ってください。参照実装は `tests/fixtures/agentic_reference/` にあり、全テストに合格することを自動テストで確認します。初期コードが公開テストに失敗することも実行して確認しました。

## 隔離の仕組み

実モデル試行は Docker コンテナが必須です。CLI コンテナには Claude Code、専用認証ボリューム、試行専用 IPC ボリュームだけをマウントし、作業コピーを渡しません。作業コンテナには試行専用の作業コピーと IPC だけをマウントし、認証情報・Docker ソケット・外部ネットワークを渡しません。Claude Code の組み込みツールは `--tools ""` で無効化し、`--strict-mcp-config` と `--allowedTools` で今回の固定 MCP ツールだけを使用します。MCP は `src/` と `public_tests/` の一覧・読取、`src/` の Python ファイル書込、固定の公開 pytest 実行に限定します。公開テストは読み取り専用です。採点はモデル終了後、作業コピーと非公開テストを読み取り専用でマウントした別コンテナで行い、ネットワークを切ります。公開テストの改変や作業ディレクトリ外の成果物は不正として記録します。

全コンテナは UID 1000、権限削除、権限昇格禁止、読み取り専用ルート、CPU 2個、メモリとスワップ合計4 GiB、最大256プロセスで実行します。CLI コンテナだけ Claude API 接続のため Docker bridge ネットワークを使用します。作業・採点コンテナは `--network none` です。モデルの編集したコードは作業コンテナ内で実行され、そこには認証情報がありません。

Docker が使えない環境では実モデル試行を開始しません。Claude Code のネイティブWindows実行はコマンドにOSレベルのサンドボックスがないため、このガードを外さないでください。コンテナイメージと認証の準備は、独立したターミナルで行います。

```powershell
docker build -t ai-lab-agent:1 -f benchmarks/agentic_dev/Dockerfile benchmarks/agentic_dev
docker build -t ai-lab-agent-worker:1 -f benchmarks/agentic_dev/Worker.Dockerfile benchmarks/agentic_dev
docker volume create ai-lab-claude-auth
docker run --rm -it --mount type=volume,source=ai-lab-claude-auth,target=/home/lab/.claude ai-lab-agent:1 claude auth login
```

## 確認と少数試験

`dry-run` はモデル・Docker・認証を呼び出さず、固定ハッシュとコマンドを表示します。

```powershell
python -m pytest tests/test_agentic_dev.py -q -p no:cacheprovider
python -m ai_lab agentic --task parcel_manifest --model haiku45 --dry-run
python -m ai_lab agentic --task parcel_manifest --model haiku --dry-run
python -m ai_lab agentic --task room_booking --model haiku45 --dry-run
python -m ai_lab agentic --task room_booking --model haiku --dry-run
```

実コンテナのスモークテストは `AI_LAB_DOCKER_BIN` に Docker CLI のフルパスを設定して `python -m pytest tests/test_agentic_docker.py -q -s -p no:cacheprovider --basetemp=analysis/agentic_docker_tmp` で実行します。4条件それぞれで、MCP の許可操作、認証情報と外部通信の遮断、初期コードの公開・非公開テスト失敗、参照実装での合格、成果物の回収を確認します。実モデルは呼び出しません。Docker CLI が PATH にない場合は実モデル実行にも `--docker-bin` でフルパスを指定してください。

実モデルを使う次段階では、各条件1回ずつから開始します。両モデルの作業コピー、ツール、最大20ターン、900秒の上限を揃えます。Haiku 4.5には Effort 設定がないため `default`、Haiku 5.5には既定の `medium` を使用し、結果を「モデルとThinking設定の組み合わせ」として表示します。

```powershell
python -m ai_lab agentic --task parcel_manifest --model haiku45 --runs 1
python -m ai_lab agentic --task parcel_manifest --model haiku --runs 1
python -m ai_lab agentic --task room_booking --model haiku45 --runs 1
python -m ai_lab agentic --task room_booking --model haiku --runs 1
```

結果は `results/` に試行ごと保存します。`claude_stream.jsonl` は元の操作履歴、`history.json` は読取・編集・テストと失敗後の修正の抽出、`trial.json` は非公開テストの結果・時間・トークン・API換算費用です。`summary.json` は成功率、平均時間、費用、失敗種類を集計します。API換算費用は公式単価に基づく推定値で、サブスクリプションの請求額ではありません。
