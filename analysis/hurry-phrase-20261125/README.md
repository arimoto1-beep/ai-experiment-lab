# AI実験室 #14: B27「急いで答えて」で回答品質は下がるか

- [事前登録](preregistration.md)、[固定問題と正解](cases.json)、[正解の別計算](verify_cases.py)
- [結果と考察](report.md)、[集計値](summary.json)、[公開用40試行](public-runs.json)
- [匿名化プリフライト](preflight-public.json)、[実行監査](audit.json)、[公開前監査](publication-audit.md)
- [ランナー](run.py)、[採点・集計](analyze.py)、[公開データの再集計](verify_public.py)

## 実行条件と結果

固定 Docker CLI イメージと分離認証 volume を使い、Claude Haiku 5.5 / effort medium で10問×各条件2回の40試行を実行した。Aは通常、Bは文末に「急いで答えて。」を追加した。40件が正常終了し、実モデル一致、独立セッション40件、ツール呼び出し0件を確認した。事前定義の「整数だけ」の正答は A 16/20、B 15/20。形式違反は A 4件、B 5件。全形式違反に正しい数値が含まれていた。

`results/hurry_phrase_20261125/` にプロンプト、CLI生ストリーム、stderr、内部記録をローカル保存し、Gitには含めない。公開記録には回答、時間、使用量、API換算費用、ハッシュを保存する。モデルに正解・採点コード・リポジトリはマウントしない。

## 再現手順

認証分離済み Docker 環境、固定CLIイメージ、`ai-lab-claude-auth` volume がある環境で、独立した端末から実行する。`run` は新規モデル呼び出しを伴い、CLIのサブスクリプション枠を使用する。既存の `results/hurry_phrase_20261125/` がある場合は重複実行を拒否する。

```powershell
.\.harbor-react-lead-form-venv\Scripts\python.exe analysis\hurry-phrase-20261125\verify_cases.py
.\.harbor-react-lead-form-venv\Scripts\python.exe analysis\hurry-phrase-20261125\run.py preflight
.\.harbor-react-lead-form-venv\Scripts\python.exe analysis\hurry-phrase-20261125\run.py run
.\.harbor-react-lead-form-venv\Scripts\python.exe analysis\hurry-phrase-20261125\analyze.py
```

公開ファイルだけで採点と主要集計を再確認するときは次を実行する。公開リポジトリには生ログと認証volumeがないため、元のCLI呼び出し・生ストリーム照合は再現できない。

```powershell
.\.harbor-react-lead-form-venv\Scripts\python.exe analysis\hurry-phrase-20261125\verify_public.py
```
