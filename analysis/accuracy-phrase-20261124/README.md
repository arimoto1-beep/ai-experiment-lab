# AI実験室 #13: B26「絶対に間違えないで」の正答率

- [事前登録](preregistration.md)、[固定問題と正解](cases.json)、[正解の独立検算](verify_cases.py)
- [結果記事](report.md)、[集計値](summary.json)、[公開用40試行記録](public-runs.json)
- [匿名化したプリフライト](preflight-public.json)、[実行監査](audit.json)、[公開前監査](publication-audit.md)
- [実行プログラム](run.py)、[集計・監査プログラム](analyze.py)、[公開データの再集計](verify_public.py)

## 実行条件と結果

固定 Docker CLI イメージ、分離認証 volume、Claude Haiku 5.5 / effort medium を使用した。A/B の違いは質問末尾の `絶対に間違えないで。` の有無だけ。10問×各条件2回の40試行はすべて正常終了し、実モデル一致、独立セッション40件、ツール呼出し0件を確認した。事前定義の整数のみの正答は A 17/20、B 16/20。全条件の API 換算費用合計は約 $0.005637 で、実請求額ではない。

`results/accuracy_phrase_20261124/` に各試行のプロンプト、CLI生ストリーム、stderr と中間記録をローカル保存し、Gitには含めない。公開記録には回答、使用量、時間、API換算費用、原記録の SHA-256 を保存した。モデルに正解・採点コード・リポジトリはマウントしていない。

## 再現手順

既存の認証分離済み Docker 環境、固定 CLI イメージ、`ai-lab-claude-auth` volume がある環境で次を実行する。`run` は新しいモデル呼出しとCLI予算消費を伴い、既存の `results/accuracy_phrase_20261124/` がある場合は重複実行を拒否する。

```powershell
.\.harbor-react-lead-form-venv\Scripts\python.exe analysis\accuracy-phrase-20261124\verify_cases.py
.\.harbor-react-lead-form-venv\Scripts\python.exe analysis\accuracy-phrase-20261124\run.py preflight
.\.harbor-react-lead-form-venv\Scripts\python.exe analysis\accuracy-phrase-20261124\run.py run
.\.harbor-react-lead-form-venv\Scripts\python.exe analysis\accuracy-phrase-20261124\analyze.py
```

集計・監査のみを行う場合は最後のコマンドだけを使う。公開リポジトリには生ログと認証 volume がないため、公開記録からは全試行の原ストリーム再照合はできない。各公開行の回答・採点・集計値、ハッシュ、実行コードは確認できる。

公開ファイルだけで採点と主要集計を再確認する場合は、`verify_public.py` を実行する。
