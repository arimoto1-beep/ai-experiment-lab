# AI実験室 #16: B07 根拠のない否定で正答を撤回するか

- [事前登録](preregistration.md)・[固定問題と正解](cases.json)
- [全試行の匿名化記録](public-runs.json)・[集計](summary.json)・[結果と考察](report.md)
- [実行コード](run.py)・[採点コード](analyze.py)・[公開データの再検証](verify_public.py)・[公開前監査](publication-audit.md)

Claude Haiku 5.5 / effort medium に自作の整数計算12問を出した。初回に指定形式で正答した6問について、同じ会話を分岐させ、根拠のない否定を一度だけ送った。追撃後、厳密な整数のまま正答したのは3件、正しい数値を示しながら説明を加えた形式違反が3件。誤答への変更は0件。初回の6件も数値は正しかったが、整数だけという指定に反したため追撃していない。

## 再現と検証

Python 3.10以上。固定 Docker CLI イメージ、分離認証 volume、`claude.ai` サブスクリプション認証が必要。モデル再実行は新しい作業コピーで行い、`results/unsupported_denial_20261127/` が存在すると重複実行を拒否する。

```powershell
python analysis/unsupported-denial-20261127/run.py preflight
python analysis/unsupported-denial-20261127/run.py run
python analysis/unsupported-denial-20261127/analyze.py
```

公開済みファイルだけなら次で採点と主要集計を再確認できる。CLI生ログと生のセッションIDは公開していないため、元のモデル呼び出しまで同一に再現するにはローカル記録が必要。

```powershell
python analysis/unsupported-denial-20261127/verify_public.py
```
