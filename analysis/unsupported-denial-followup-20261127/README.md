# AI実験室 #16 追加実験 B07

論理・条件整理・仕様読解の18問を使い、同じ初回正答から中立的な再確認と根拠のない単発の否定に分岐した。対象は Claude Haiku 5.5 / `medium`。

- [結果と考察](report.md)・[公開前監査](publication-audit.md)
- [事前登録](preregistration.md)・[固定問題と正解](cases.json)
- [全ケースの回答と照合値](public-runs.json)・[集計と固定条件](summary.json)・[ターン別使用量](usage-summary.json)
- [初回実験](../unsupported-denial-20261127/report.md)・[初回の開発AI記録](../unsupported-denial-20261127/developer-ai.md)

## 公開データからの再検証

リポジトリのルートから Python 3.10 以上で以下を実行する。公開回答・採点と集計、条件文のハッシュ、同一初回セッションから分岐した記録を照合する。

```powershell
python -X utf8 analysis/unsupported-denial-followup-20261127/analyze.py verify
python -X utf8 analysis/unsupported-denial-followup-20261127/audit_usage.py verify
```

## モデルを使った再現

書き込み可能な別チェックアウトを使う。既存の固定 Docker CLI イメージ、分離認証 volume、Claude Code の `claude.ai` サブスクリプション認証が必要。ランナーは事前固定ファイルとコミットの一致を検査する。既存の `results/unsupported_denial_followup_20261127/` がある場合は重複実行を拒否する。実モデルを呼ぶため、サブスクリプション枠を使用する。

```powershell
python -X utf8 analysis/unsupported-denial-20261127/run.py preflight
python -X utf8 analysis/unsupported-denial-followup-20261127/runner.py
python -X utf8 analysis/unsupported-denial-followup-20261127/analyze.py audit
python -X utf8 analysis/unsupported-denial-followup-20261127/audit_usage.py audit
```

`audit` は保存した生ストリームから応答・使用量・ハッシュを再照合し、作業コピーに集計と公開用データを書き出す。分岐の `modelUsage` とCLI費用は親セッションを含むため、使用量の比較にはターン別集計を使う。使用量の補足スクリプトは今回の全件有効・キャッシュ書き込み1時間TTLの記録を対象とする。元の実行の監査には、リポジトリ外の生記録が必要。
