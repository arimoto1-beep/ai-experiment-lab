# agentic_dev Docker 検証（2026-10-18）

実モデルは呼び出していない。Docker Desktop 4.95.0、Linux Engine 29.8.2 で `ai-lab-agent:1` をビルドした。イメージIDは `sha256:013471e9e1cc925a4b4ca0df503e52d21e56c29f010ad7149e3dcbb2b9e1d9c8`、コンテナ内の Claude Code は 2.1.302、pytest は 8.4.2。

`tests/test_agentic_docker.py` を、2課題×2モデル条件で実行した。各条件の課題文ハッシュとCLI引数を検査し、モデル用コンテナの同じマウント構成で Python の検査プログラムだけを動かした。Claude CLI は `--version` のみ実行した。

| 課題 | 条件 | 初期状態の非公開テスト | 参照実装の非公開テスト |
| --- | --- | ---: | ---: |
| parcel_manifest | Haiku 4.5 / default | 2/8 成功 | 8/8 成功 |
| parcel_manifest | Haiku 5.5 / medium | 2/8 成功 | 8/8 成功 |
| room_booking | Haiku 4.5 / default | 3/10 成功 | 10/10 成功 |
| room_booking | Haiku 5.5 / medium | 3/10 成功 | 10/10 成功 |

公開テストも初期状態で失敗し、参照実装では合格した。`src/` に書いた成果物がホストの試行用ディレクトリに回収されること、公開テストへの書き込みが拒否されることを確認した。非公開テストと元リポジトリはモデル用コンテナに存在せず、ホストの `.aws` と `.docker`、関連する認証環境変数も参照できなかった。検査時の Claude 認証ボリュームは新規作成した専用ボリュームで、終了後に削除した。実試行で使う専用 Claude 認証ボリュームはモデル用コンテナから読み取れる。

モデル用コンテナは bridge ネットワーク、採点用コンテナはネットワークなし。両方とも UID 1000、読み取り専用ルート、権限なし、権限昇格禁止で稼働した。実測した cgroup 制限は CPU 2個、メモリ4 GiB、最大256プロセス。モデル用コンテナのルート領域への書き込みは拒否され、採点用コンテナからの外向き接続も失敗した。

Docker を含む全自動テストは `python -m pytest tests -q -s -p no:cacheprovider` で **762件成功**。Windows の pytest 出力捕捉と Docker 子プロセスを併用すると `WinError 6` が出るため、Docker テストには `-s` を指定する。実モデル呼び出し、Claude 認証ログイン、commit、push、タグ作成は行っていない。
