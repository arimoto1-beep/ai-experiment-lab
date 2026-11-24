# AI実験室 #13: Thinking の独立切替を確認できず、成績比較を保留

- [事前登録](preregistration.md): 仮説、6問と正解、24試行、上限、採点規則、実行ゲート。
- [プリフライト記録](preflight.json): 実行環境と切替可否の要約。
- [結果と考察](report.md): 今回確認できたこと、未確認事項、次の条件。
- [公開前監査](audit.md): 公開範囲、秘密情報、結果表記の確認。

2026-11-24 JST、ローカル Claude Code CLI 2.1.299 のヘルプに `--effort` はあるが Thinking 有効・無効の切替フラグはない。CLI のサブスクリプション認証方式は `claude.ai` と確認した。公式 [Claude Platform の Thinking 説明](https://platform.claude.com/docs/en/build-with-claude/thinking)では Haiku 5.5 の API に `thinking: {"type":"disabled"}` を effort `high` 以下で設定できる。一方、公式 [Claude Code 環境変数の説明](https://code.claude.com/docs/en/env-vars)では、`MAX_THINKING_TOKENS=0` による無効化の対象から Haiku 5.5 が除かれている。この API と CLI の差があるため、CLI で B01 の有効・無効を独立に切り替えられるとみなさなかった。

問題をモデルに提示する試行は0件。成績やトークンの実測値はない。将来、同じ認証・安全・予算条件のもとで独立切替が検証できれば、事前登録した問題セットと採点基準で再開できる。CLI の仕様が変わった場合は、変更を記録してから実行する。
