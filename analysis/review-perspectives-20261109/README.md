# AI実験室 #9 実行記録

- [事前登録](preregistration.md)はモデル呼出し前に作成した。
- [報告書](report.md)、[全レビューの最終応答](reviews.json)、[費用集計](metrics.json)、[実行条件の照合と読取エラー](audit.json)、[Reactの固定入力](inputs-react.json)、[Parcelの固定入力](inputs-parcel.json)、[Reactの生成視点](perspectives-react.json)、[Parcelの生成視点](perspectives-parcel.json)を公開用に保存した。
- CLI生ストリーム、操作履歴、実際の全プロンプト、入力ハッシュはGit除外済みの `results/review_perspectives_20261109/` にある。

既存の #6/#7 の認証分離Dockerイメージ、`ai-lab-claude-auth` ボリューム、#7成果物の復元、#6の保存済みワークスペースが必要。ホストのHarbor用Python仮想環境を使用する。確認・実行コマンドは次のとおり。

```powershell
$dockerBin = Join-Path $env:LOCALAPPDATA 'Programs/DockerDesktop/resources/bin/docker.exe'
.\.harbor-react-lead-form-venv\Scripts\python.exe -m ai_lab.review_perspectives --task parcel --docker $dockerBin --preflight
.\.harbor-react-lead-form-venv\Scripts\python.exe -m ai_lab.review_perspectives --task react --docker $dockerBin --preflight
.\.harbor-react-lead-form-venv\Scripts\python.exe -m ai_lab.review_perspectives --task parcel --docker $dockerBin
.\.harbor-react-lead-form-venv\Scripts\python.exe -m ai_lab.review_perspectives --task react --docker $dockerBin
.\.harbor-react-lead-form-venv\Scripts\python.exe analysis/review-perspectives-20261109/summarize.py
.\.harbor-react-lead-form-venv\Scripts\python.exe analysis/review-perspectives-20261109/audit.py
```

実行ランナーは既存の同名結果ディレクトリへの上書きを拒否する。新しい実行が必要なら、ランナー内の結果ディレクトリ名を新しい実験IDに変更する。レビューではコードと作業ワーカーを読取専用でマウントし、MCPも一覧・読取のみを提示する。`C_design` は課題文とファイル名しか受け取らない。集計スクリプトは Git 除外済みの実行ログから公開用の集計・レビュー・固定入力・生成視点を再生成する。監査スクリプトは各プロンプトと事前固定条件の完全一致、試行順、モデル、ツール、20セッションの独立性、成果物の不変性を検証し、読取エラーの対象パスと回数を記録する。
