# AI実験室 #10: Haiku 5.5のエフォート別コードレビュー

実施日: 2026-11-12 JST。判定基準と既知不具合はモデル実行前の[事前登録](preregistration.md)で固定した。**予定6件のうち4件が正常終了、A-maxは600秒でタイムアウト、B-maxは異常時停止規則により未実行**。したがってmaxの発見性能は評価できない。再試行・代替設定・commit・pushはしていない。

## 復元・実行条件

- 固定コミット `452bf305c6daa62fc59061d22133a7cbc7c1572e` のGit blobへ#7の保存差分を適用。A `rlfm-aa5796866708` の17ファイル、B `rlfm-1170a1288c0a` の21ファイルが、各元試行の `artifacts/app` と全パス・全SHA-256で一致した。[復元マニフェスト](restoration.json)。公式課題の作業ツリーには既存の差分があるため、復元元に使わなかった。
- レビュー対象モデルは全件 `claude-haiku-5-5`、固定コンテナ内のClaude Code CLIは **2.1.302**。ホスト側のCLI 2.1.299は使用していない。固定CLIのヘルプと[Anthropicのeffort説明](https://platform.claude.com/docs/en/build-with-claude/effort)で `medium`、`high`、`max` が指定可能と確認した。
- #9方式Aの課題文、共通指示、一般レビュー役割を完全再利用。実行時プロンプトSHA-256 `1ce91c7cb2c74db044d394cba176b973369ce298ec64944715ed9c4b4071847b` は#9の方式Aと同じ。各試行は新規CLIプロセス・セッション。35ターン、600秒、CLIのAPI換算予算上限 $0.20 を共通化した。
- コードは別の読取専用workerコンテナのみにマウントし、CLIには認証ボリュームと試行専用IPCのみ。公開ツールは `list_files` と `read_file`。workerはネットワークなし、Dockerソケットなし。既知不具合、非公開テスト結果、過去レビューはプロンプトに含めていない。試行前後のハッシュ一致、編集・コマンド実行0を確認した。
- 指定エフォートの証拠は各試行の `invocation.json` の `--effort`、CLIが拒否せず開始した `stream.jsonl` の `per_turn_effort_active: true`、assistantメッセージの実モデルID、thinkingイベント。CLIの最終JSONは実際のAPIリクエストの `output_config.effort` を表示しないため、サーバー側の適用値まで独立に読み取れたという意味ではない。maxは最終応答・`modelUsage`がない。部分ストリームのassistantモデルIDは `claude-haiku-5-5`。

## 試行結果

発見数は事前登録の独立原因群を分母にした。新規は事前の既知集合以外の肯定的指摘で、コードと仕様に照合できたもの。誤指摘と根拠未確定は別扱い。時間はworker起動・後片付けを含む壁時計秒数。費用は[AnthropicのHaiku 5.5料金](https://platform.claude.com/docs/en/about-claude/pricing)とCLI使用量からのAPI換算で、実請求額ではない。各リクエストの10万トークン超過を復元できない場合は高価格帯を反映できない。

| 対象・effort | 既知発見/総数 | 見落とし | 確認済み新規 | 誤指摘 | 未確定の肯定的指摘 | 読取/エラー | 秒 | input / cache書込 / cache読取 / output（thinking） | API換算USD |
| --- | ---: | --- | ---: | ---: | ---: | ---: | ---: | --- | ---: |
| A medium | 6/7 | A7 | 5 | 0 | 4 | 13/0 | 108.868 | 6 / 22,399 / 9,942 / 24,102 (18,050) | 0.016631 |
| B medium | 1/1 | なし | 0 | 0 | 0 | 18/0 | 133.370 | 10 / 18,765 / 51,102 / 30,696 (27,947) | 0.019613 |
| A high | 7/7 | なし | 5 | 0 | 0 | 13/0 | 166.621 | 6 / 18,016 / 14,475 / 38,383 (31,645) | 0.022940 |
| B high | 1/1 | なし | 1 | 1 | 0 | 21/0 | 220.352 | 8 / 49,253 / 38,029 / 51,727 (48,035) | 0.036095 |
| A max | 判定不可 | 判定不可 | 判定不可 | 判定不可 | 判定不可 | 17/0 | 601.277 | 最終使用量なし。部分ストリーム末尾のthinking推定16,850は総量ではない | 算定不可 |
| B max | 未実行 | 未実行 | 未実行 | 未実行 | 未実行 | — | — | — | — |

正常終了の4件はCLI `status=ok`、戻り値0、`modelUsage`の実モデルID一致、コードハッシュ不変、stderr空、ツールエラー0。各回のモデルID・CLIバージョン・指定effort・時間・使用量・料金と生ログのSHA-256は[公開用試行要約](public-runs.json)に記録した。4件の[レビュー最終回答](reviews)はCLIの `result_text` をUTF-8でそのまま抽出した。生ストリームと認証情報はGitに含めない。

A-maxはホスト側の600秒制限で `status=timeout`、CLI実行600.042秒、後片付けを含む601.277秒。部分ストリームは533イベントで、最後は `system.thinking_tokens`、最終 `result` イベントは0件だった。17回の読取、編集・コマンド実行・ツールエラー0、コードハッシュ不変。最終 `modelUsage`、総トークン数、API換算費用は得られなかった。部分ログでは3つのrequest IDに付いたusageスナップショットがあり、最新値をIDごとに拾うと input 6、cache書込 19,045、cache読取 14,589、output 35。これは**最終会計ではなく**、合計消費量として使えない。末尾のthinking推定16,850も進行中の推定値で、試行全体のthinking総数ではない。rate-limitイベントの状態は `allowed`。タイムアウトの原因をログから断定しない。レビュー用コンテナは後片付けされ、B-maxは開始していない。

## 指摘の採点

**Aの既知7群:** A1フォームラベル、A2時刻fallback、A3営業日・営業時間補正、A4必須source群、A5破損sourcesの記録、A6出力の原子性、A7同一再送時のCRM不変性。[A-medium原文](reviews/a-medium-b0fee227.md)はA1〜A6を具体的に指摘し、A7を見落とした。[A-high原文](reviews/a-high-3d50edd3.md)はA1〜A7をすべて具体的に指摘した。A-highのA7は余分な `notes` キーを含む例だが、`writeLedgers()` が同一再送でもCRMを書き直す原因を正しく説明している。#7の[保存差分](../react-lead-form-replication-20261031/patches/rlfm-aa5796866708.patch)には `processLead()` の同一判定時に受理を返す経路と、`writeLedgers()` が毎回 `crm_leads.json` を書く経路が残る。公式仕様の `matchedSubmission.identicalDuplicate` はledger再書込を禁止する。[B-medium](reviews/b-medium-c004ad44.md)と[B-high](reviews/b-high-45cf5def.md)も、B1（A7と同種）をともに具体的に指摘した。

**A-mediumの確認済み新規5件:** (1) 不完全レコード更新後の `missingFields` をマージ済みレコードでなく新規入力だけから算出、(2) 破損ledgerを記録しても `reconciliation.quarantinedLedgers` が常に空、(3) JSONとして読めるが形が不正なledgerを `invalid_shape` でなく `invalid_json` と扱う経路、(4) マッチしたレコードの `source` を後続入力で上書きし初回接触の監査値を失う、(5) UTCオフセット付きの有効 `receivedAt` を `Z` 形式へ変換しない。いずれも `submitLead.ts` の分岐と `lead_schema.json` の該当契約で確認した。特に(1)はA-highでは指摘されず、既知7群以外ではhighがmediumの発見をすべて包含していない。

**A-highの確認済み新規5件:** 上記(2)〜(5)に加え、既存の不完全レコードAを同一再送した時に `processLead()` の結果を捨てて配列末尾Bを返し、返却payloadと `missingFields` がBのものになる。`pipelineApi.incompleteResult` とコードで確認した。A-mediumの「batchで別レコードを返すかもしれない」は再現条件が十分でなく未確定扱いとし、highの単一再送による具体的な条件と区別した。

**A-mediumの未確定4件:** 「未完成の入力1件で既存レコードとマージすれば完成するのでpromotion必須」は、仕様の `later complete submission` の解釈が必要。既存CRMがそもそも必須項目を欠く例、追加の任意 `notes` キーを持つ監査レコードの保存要件、batchで受理0件の場合の戻りpayloadは、規範文だけでは断定できない。いずれも発見・誤指摘に算入しなかった。`suspicions` 欄の項目も発見に数えていない。

**B-highの確認済み新規1件と誤指摘1件:** [原文](reviews/b-high-45cf5def.md)は、カスタムsource `constructor` とテストファイル不在を別々に指摘した。前者は仕様上許されるが、#7の[保存差分](../react-lead-form-replication-20261031/patches/rlfm-1170a1288c0a.patch)にある `ledger.ts` の `projectSources()` が通常のオブジェクトで `groups[source] ??= []` の後に `.push()` を呼ぶため、継承された関数に当たってTypeErrorになる。Node 24.15.0で同じ式を実行し、TypeErrorを確認した。同根の `__proto__` 衝突は#9で別成果物について既に観測されており、プロジェクト全体として未知の種類ではない。後者の「配布appにテストファイルがないので `npm test` が実装不具合」は誤指摘。公式検証器がテストを注入する環境でVitestが動作し、#7でBは11/11成功している（[診断記録](../react-lead-form-diagnostic-20261031/README.md)）。B-mediumはこの誤指摘を `suspicions` に留めた。

## 解釈

- **mediumで見落とした既知不具合をhighが発見したか:** A7について該当。Aは6/7→7/7、Bは1/1→1/1。ただしA/Bはコード難易度が異なり、各条件1回である。
- **単調増加か:** 正常終了したmedium→highの既知発見数はAで増加、Bで同数。maxはタイムアウトのため、3段階の単調性は判定不能。新規指摘の内容もA-mediumとA-highで完全には包含関係にならない。
- **誤判断:** B-highはB-mediumが疑いに留めたテスト不在を確定的な不具合として誤指摘した。高エフォートで誤指摘が増える可能性を示す観測だが、一般化はできない。
- **費用と時間:** A-highはA-medium比で+57.753秒、+$0.006309（約38%）で既知1群を追加発見し、誤指摘は増えなかった。この1試行では追加費用に対応する改善があった。B-highは+86.982秒、+$0.016482（約84%）で既知の追加発見はなく、珍しいcustom sourceの不具合を1件追加した一方で誤指摘も1件増えた。4件合計ではhighがmediumより+144.735秒、+$0.022791、既知発見が7/8→8/8。maxは600秒の時間枠を使い切り、完成レビューがなく、費用対効果は算定不能。
- **種類:** mediumでもラベル、時刻、source群、破損ledger、原子性を発見した。highが追加で捕らえた既知群は、同一入力の再送とファイルのバイト不変性という状態・保存条件だった。B-highの追加指摘はカスタムsourceのプロトタイプ衝突という境界値。ここから種類別の一般的効果は推定できない。

この結果は「Haiku 5.5でeffortを上げれば常に新しい不具合を発見できる」という証拠ではない。今回はhighがAの既知未発見1群を見つけ、Bでは既知発見数が同じで誤指摘が増えた。maxは完走できず、能力比較の結論は保留する。

**観測と因果の区別:** Aでhighの既知発見数がmediumより1群多いことは観測事実。effortを上げたこと自体が改善の原因だったという説明は、各条件1回で試行間の確率的な揺れを測っていないため未検証の仮説。maxはタイムアウトし、完成回答がないため品質を評価できない。
