# AI実験室 #15 追加実験 B45

初回 B36 では短い表の集計で、強調していない指示が通常条件・強調条件ともに48/48だった。今回は一つの出力に複数の制約がかかるキーワード課題で、同じ問いを調べる。

- [初回 B36 の記録](../single-emphasis-20261126/README.md)
- [追加実験の事前登録](protocol.md)、[問題と正解例](cases.json)
- [予備の回答](pilot-runs.json)、[予備の集計](pilot-summary.json)、[予備の実行監査](pilot-audit.json)
- [本実験前に固定した条件と順序](main-lock.json)
- [本実験の回答](main-runs.json)、[本実験の集計](main-summary.json)、[本実験の実行監査](main-audit.json)
- [結果と考察](report.md)、[公開前監査](publication-audit.md)

## 公開データから検証する

Python 3.10以上で、リポジトリのルートから実行する。元のモデルを呼び出さずに、全39正解例、公開回答の採点、プロンプトのハッシュ、難易度の選択、集計を確認できる。

```powershell
python analysis/instruction-constraints-20261126/analyze.py cases
python analysis/instruction-constraints-20261126/analyze.py verify pilot
python analysis/instruction-constraints-20261126/analyze.py verify main
```

## 新しいモデル試行を行う

固定 Docker CLI イメージ、分離認証 volume `ai-lab-claude-auth`、サブスクリプション認証が必要。独立した端末で、書き込み可能な別のチェックアウトから実行する。結果は Git 管理外の `results/instruction_constraints_20261126/` に置かれる。フェーズの結果ディレクトリがある場合、ランナーは再試行を拒否する。採点の `audit` と難易度を確定する `lock` は、そのチェックアウトに新しい結果ファイルを書き出す。

```powershell
python analysis/instruction-constraints-20261126/run.py preflight
python analysis/instruction-constraints-20261126/run.py pilot
python analysis/instruction-constraints-20261126/analyze.py audit pilot
python analysis/instruction-constraints-20261126/analyze.py lock
python analysis/instruction-constraints-20261126/run.py main
python analysis/instruction-constraints-20261126/analyze.py audit main
```

新しい実行では予備試行の結果によって難易度が変わり得る。今回と同じ難易度で本実験だけを再実行する場合は、公開済みの予備ファイルと `main-lock.json` を使い、`run.py main` から行う。元の生ストリーム確認には公開リポジトリに含まれない実行時ログが必要。
