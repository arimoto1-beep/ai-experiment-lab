# AI実験室 #17 B46 否定の口調の強さと正答維持

Claude Haiku 5.5 / `medium` に自作の4択問題を出し、同じ初回正答から中立・弱い否定・強い否定に分岐した。弱い否定と強い否定では確信を示す副詞だけを変えた。

- [結果と考察](report.md)・[公開前監査](publication-audit.md)
- [事前登録](preregistration.md)・[#16追加実験から再利用した問題と正解](../unsupported-denial-followup-20261127/cases.json)
- [全回答と照合値](public-runs.json)・[集計と固定条件](summary.json)

## 公開データの再検証

リポジトリのルートから Python 3.10 以上で実行する。公開回答の採点、条件と順序、分岐元の一致、API換算費用と全体集計を再計算する。

```powershell
python -X utf8 analysis/denial-strength-20261128/audit_b46.py verify
```

## モデルを使った再現

書き込み可能な別チェックアウトで事前登録コミット `ef23b30` を使う。#16と同じ固定Dockerイメージ、分離認証 volume、Claude Code の `claude.ai` サブスクリプション認証が必要。実行はサブスクリプション枠を使用する。`results/denial_strength_20261128/` が存在すると重複実行を拒否する。

```powershell
python -X utf8 analysis/denial-strength-20261128/run_b46.py
python -X utf8 analysis/denial-strength-20261128/audit_b46.py audit
```

`audit` はローカルの生ストリーム、送信文、実行順とハッシュを照合し、作業コピーに公開用JSONを生成する。元の実行に対する生記録の監査には、Git管理外の生ストリームと実行記録が必要。
