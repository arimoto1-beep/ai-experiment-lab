# AI実験室 #15: B36「一つだけ強調すると、他の指示は守られにくくなるか」

- [事前登録](preregistration.md)、[固定問題と正解](cases.json)、[正解の別計算](verify_cases.py)
- [結果と考察](report.md)、[集計値](summary.json)、[公開用32試行](public-runs.json)
- [匿名化プリフライト](preflight-public.json)、[実行監査](audit.json)、[公開前監査](publication-audit.md)
- [問題生成コード](make_cases.py)、[ランナー](run.py)、[採点・集計](analyze.py)、[公開データの再集計](verify_public.py)

## 実行条件と結果

架空の表8件について4つの集計指示を出し、Aは通常、Bは第1指示だけに「【絶対に守ってください】」を加えた。Claude Haiku 5.5 / effort mediumで各表・各条件を2回ずつ、計32試行。32件が正常終了し、実モデル一致、独立セッション32件、ツール呼び出し0件を確認した。強調していない第2～第4指示の厳密正答は A 48/48、B 48/48。16ペアすべて同点で、この課題群では低下を確認できなかった。

`results/single_emphasis_20261126/` にプロンプト、CLI生ストリーム、stderr、内部記録をローカル保存し、Gitには含めない。公開記録には回答、時間、使用量、API換算費用、ハッシュを保存する。モデルに正解・採点コード・リポジトリはマウントしない。

## 再現手順

Python 3.10以上と、認証分離済みDocker環境、固定CLIイメージ、`ai-lab-claude-auth` volumeが必要。実験は独立した端末から実行する。`run`は新規モデル呼び出しを伴い、CLIのサブスクリプション枠を使用する。既存の結果ディレクトリがある場合は重複実行を拒否する。`make_cases.py`は固定済み問題を上書きするため、再現時には実行しない。

```powershell
python analysis\single-emphasis-20261126\verify_cases.py
python analysis\single-emphasis-20261126\run.py preflight
python analysis\single-emphasis-20261126\run.py run
python analysis\single-emphasis-20261126\analyze.py
```

公開ファイルだけで採点と主要集計を再確認するときは次を実行する。公開リポジトリには生ログと認証volumeがないため、元のCLI呼び出し・生ストリーム照合は再現できない。

```powershell
python analysis\single-emphasis-20261126\verify_public.py
```
