# AI実験室 #11

- [事前登録](preregistration.md): 対象、既知欠陥、共通プロンプト、採点規則。
- [結果と考察](report.md): 15レビューの比較、時間・トークン・費用、見落としと誤指摘。
- [固定入力](frozen-inputs.json): 対象コード全ファイルと課題・プロンプトのSHA-256、モデルと順序。
- [方法別の数値](metrics.json)、[15試行の使用量・時間・費用](public-runs.json)、[指摘ごとの採点](grading.json)、[レビュー回答](reviews.json)、[実行監査](audit.json)。
- [新規指摘の根拠](evidence.md)、[隔離再現結果](validation.json)。
- [medium 3回目のみが発見したX1の原文とコード根拠](x-a3-x1.md)。

レビューには #7 の保存成果物をそのまま読取専用で渡した。CLI生ストリーム、正確な実行プロンプト、個人用パスや認証volumeはGit除外済みの `results/repeated_review_20261116/` にある。公開回答には認証文字列やホストの絶対パスがないことを走査した。元成果物のハッシュは事後検証後も固定入力と一致した。

既存の分離済みDockerイメージ、`ai-lab-claude-auth` volume、#7の元成果物がある環境で、次のコマンドを使う。**ランナーはモデルを新たに15回呼ぶ**ため、今回の結果を確認するためだけには実行しない。既存の `results/repeated_review_20261116/` があれば安全のため再実行を拒否する。

```powershell
$env:RLFM_DOCKER = Join-Path $env:LOCALAPPDATA 'Programs/DockerDesktop/resources/bin/docker.exe'
.\.harbor-react-lead-form-venv\Scripts\python.exe -m analysis.repeated-review-20261116.run --preflight
.\.harbor-react-lead-form-venv\Scripts\python.exe -m analysis.repeated-review-20261116.run
```

既存の生ログから公開集計を再生成するコマンドはモデルを呼ばない。`grade.py` の個別判定表は人手の仕様・コード照合結果を固定したもので、新しい試行にそのまま適用する正解器ではない。

```powershell
.\.harbor-react-lead-form-venv\Scripts\python.exe -m analysis.repeated-review-20261116.grade
.\.harbor-react-lead-form-venv\Scripts\python.exe -m analysis.repeated-review-20261116.audit
```

代表的な新規指摘の事後検証には固定公式検証器イメージを使用した。`validate_new.ps1` は元成果物を一時コンテナへコピーし、ネットワークなしで `validate_new.ts` を実行する。元の成果物を変更せず、モデルも呼ばない。
