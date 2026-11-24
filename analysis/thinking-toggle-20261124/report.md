# AI実験室 #13 結果: B01 Thinking には本当に効果があるのか

実施日: 2026-11-24 JST。

## 今回の疑問と仮説

同一モデル・同一 effort のまま Thinking を切り替えると、正答率、時間、トークン、API 換算費用は変わるか。推論問題で正答率が上がり、時間・費用が増える可能性を予想した。これは検証前の仮説であり、結果ではない。

## 条件と実測結果

[事前登録](preregistration.md)では Claude Haiku 5.5 / medium、6問、各条件2回、合計24試行、1試行45秒・CLI予算 $0.01、客観採点を固定した。最初のゲートは、実験で使う認証分離済み CLI で Thinking の有効・無効を effort から独立に設定できるかの確認とした。今回はローカル CLI の機能確認でゲートが成立せず、分離環境でのモデル試行は開始しなかった。

[プリフライト](preflight.json)で Claude Code CLI 2.1.299 のヘルプには `--effort` があり、Thinking 切替フラグはなかった。サブスクリプション認証方式は `claude.ai`。公式 [API の Thinking 仕様](https://platform.claude.com/docs/en/build-with-claude/thinking)は Haiku 5.5 / medium で `thinking: {"type":"disabled"}` を受け付けるが、[Claude Code の環境変数仕様](https://code.claude.com/docs/en/env-vars)は `MAX_THINKING_TOKENS=0` による Haiku 5.5 の無効化を保証していない。CLI から API の設定を独立に指定する手段を確認できなかった。

| 指標 | Thinking 有効 | Thinking 無効 |
| --- | --- | --- |
| 問題試行 | 0 / 計画12 | 0 / 計画12 |
| 正答率 | 比較不能 | 比較不能 |
| 実行時間 | 未測定 | 未測定 |
| トークン | 未測定 | 未測定 |
| API 換算費用 | 未算出 | 未算出 |

問題試行を行っていないため、実測成績はない。プリフライトの CLI ヘルプと認証確認はモデルの問題回答試行ではない。推測した数値や既存実験の数値を今回の結果に流用していない。

## 確認できたこと、確認できなかったこと

- 確認できたこと: API と現在の CLI では Thinking 無効化に関する公開設定が異なる。今回の CLI では同じ effort のまま明示的に切り替える実行手段を確認できなかった。
- 確認できなかったこと: Thinking の正答率・速度・トークン・費用への効果。CLI 内部の実際の API リクエストに Thinking 設定がどう送られるか。別バージョンや API での比較結果。
- 読者への価値: 「Thinking の効果」を測る前に、Thinking と effort を独立に操作できるかを確認する必要がある。切替が不明な比較を Thinking の効果として解釈しないための判断材料になる。

## 新たな疑問とバックログ

Haiku 5.5 の Thinking をサブスクリプション認証・同じ effort のまま明示的に切り替えられる CLI または安全な実行手段があるか。`BACKLOG.md` の B01 を「保留」とし、#13 の確認範囲と残る条件を記載した。effort の変更は B02、簡単な質問に限った効果は B03 として別に維持した。
