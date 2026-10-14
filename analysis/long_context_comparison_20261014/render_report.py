"""Render the verified nine-trial snapshot; no model calls or source-result writes."""

import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA = json.loads((ROOT / "analysis.json").read_text(encoding="utf-8"))
DETAILS = DATA["details"]
LENGTHS = ("short", "medium", "long90k")
LABELS = {"short": "短文・1万目標", "medium": "中程度・5万目標", "long90k": "長文・9万目標"}
FACT_LABELS = {
    "base_fee": "基本料金", "standard_route": "通常の処理経路",
    "discount_percent": "割引率", "discount_segment": "割引対象区分",
    "exception_kind": "例外規定の対象種別", "exception_surcharge": "例外規定の追加料金",
    "exception_route": "例外規定の処理経路", "grace_period_days": "対象製品の猶予日数",
}


def condition(detail):
    record = detail["record"]
    return "4.5 default" if record["effort"] == "default" else f"5.5 {record['effort']}"


def select(length, effort):
    return next(d for d in DETAILS if d["record"]["case_config"]["length"] == length and d["record"]["effort"] == effort)


def table(headers, rows):
    def cell(value):
        return str(value).replace("|", "\\|").replace("\n", " ")
    return "\n".join([
        "| " + " | ".join(map(cell, headers)) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
        *("| " + " | ".join(map(cell, row)) + " |" for row in rows),
    ])


def write_csv(name, rows):
    with (ROOT / name).open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


summary = []
fact_rows = []
cost_rows = []
for detail in DETAILS:
    r = detail["record"]
    s, t, c = r["scoring"], r["tokens"], r["context"]
    primary_ids = set(detail["expected_answer"]["final"]["sources"])
    cited_ids = [sid for fact in detail["actual_answer"]["facts"].values() for sid in fact["sources"]]
    cited_ids.extend(detail["actual_answer"]["final"]["sources"])
    foreign_ids = sorted(set(cited_ids) - primary_ids)
    assert not foreign_ids
    row = {
        "experiment": detail["experiment"], "case_id": r["case_id"],
        "length": r["case_config"]["length"], "condition": condition(detail), "problem_seed": 101,
        "position": r["case_config"]["position"], "distraction": r["case_config"]["distraction"],
        "target_document_tokens": r["case_config"]["target_tokens"],
        "document_tokens_measured": None, "document_bytes": r["case_config"]["document_bytes"],
        "prompt_bytes": detail["prompt_bytes"], "prompt_sha256": r["prompt_sha256"],
        "requested_model": r["model"], "assistant_models": ";".join(c["assistant_models"]),
        "model_check": r["model_check"]["status"], "requested_effort": r["effort"],
        "effort_flag": detail["metadata"]["reasoning_settings"]["effort_flag"],
        "per_turn_effort_active": detail["raw_verification"]["per_turn_effort_active"],
        "effective_effort_level_verified": False, "effective_thinking_budget": None,
        "cli_version": detail["metadata"]["claude_version"], "started_at": r["started_at"],
        "wall_seconds": r["wall_seconds"], "cli_duration_ms": r["claude"]["duration_ms"],
        "cli_duration_api_ms": r["claude"]["duration_api_ms"],
        "normal_input_tokens": t["input"], "cache_read_tokens": t["cache_read"], "cache_write_tokens": t["cache_write"],
        "cache_write_1h_tokens": r["cost"]["cache_write_tokens_by_ttl"]["1h"],
        "cache_write_5m_tokens": r["cost"]["cache_write_tokens_by_ttl"]["5m"],
        "total_input_tokens": c["reported_prompt_tokens"], "cache_read_share": detail["cache_read_share"],
        "output_tokens_including_thinking": t["output"], "thinking_tokens": r["claude"]["thinking_tokens"],
        "output_tokens_excluding_thinking": detail["visible_output_tokens"],
        "api_equivalent_usd_saved": r["cost"]["api_equivalent_usd"],
        "api_equivalent_usd_recomputed": detail["recomputed_api_equivalent_usd"],
        "cli_total_cost_usd": r["claude"]["cli_total_cost_usd"],
        "long_context_rate_multiplier": r["cost"]["long_context_multiplier"],
        **detail["normalized_costs"],
        "extraction_correct": s["extraction_correct"], "composition_correct": s["composition_correct"],
        "facts_correct_count": detail["fact_correct_count"], "facts_total": 8,
        "wrong_fact_fields": ";".join(f["field"] for f in detail["fields"] if not f["correct"]),
        "fact_accuracy": s["fact_accuracy"], "prerequisites_correct": s["prerequisites_correct"],
        "citation_id_correct_count": detail["citation_id_correct_count"], "citation_id_total": 9,
        "citation_accuracy": s["citation_accuracy"], "unsupported_citations": s["unsupported_citations"],
        "facts_with_correct_value_and_sources": detail["value_supported_fact_count"],
        "omitted_facts": s["omitted_facts"], "fabricated_values_by_existing_scorer": s["fabricated_values"],
        "wrong_entity_values_by_existing_scorer": s["wrong_entity_values"],
        "explicit_foreign_entity_source_ids": ";".join(foreign_ids),
        "original_json_valid": s["original_json_valid"], "fence_recovered": s["fence_recovered"],
        "schema_valid": s["schema_valid"], "format_compliant": s["format_compliant"], "strict_success": s["strict_success"],
        "final_amount": detail["actual_answer"]["final"]["amount"], "final_route": detail["actual_answer"]["final"]["route"],
        "boundary_probes_match": s["boundary_probes_match"], "comparison_eligible": r["comparison_eligible"],
        "cli_status": r["claude"]["status"], "reported_turns": c["reported_turns"],
        "context_alerts": ";".join(r["context_alerts"]), "stdin_echo_status": c["stdin_echo_status"],
        "observed_compaction_event_count": len(c["compaction_events"]),
        "compaction_status": c["compaction_status"], "truncation_status": c["truncation_status"],
        "api_payload_integrity": c["api_payload_integrity"],
        "stderr_bytes": detail["raw_verification"]["stderr_bytes"],
    }
    summary.append(row)
    cost_rows.append({key: row[key] for key in (
        "experiment", "length", "condition", "total_input_tokens", "cache_read_share",
        "output_tokens_including_thinking", "api_equivalent_usd_saved", "api_equivalent_usd_recomputed",
        "long_context_rate_multiplier", "all_input_uncached_usd", "all_input_cache_write_1h_usd", "all_input_cache_read_usd",
    )})
    for field in detail["fields"]:
        fact_rows.append({
            "experiment": detail["experiment"], "length": row["length"], "condition": row["condition"],
            "field": field["field"], "expected_value": json.dumps(field["expected"]["value"], ensure_ascii=False),
            "actual_value": json.dumps(field["actual"]["value"], ensure_ascii=False),
            "expected_sources": ";".join(field["expected"]["sources"]), "actual_sources": ";".join(field["actual"]["sources"]),
            **{key: field[key] for key in ("correct", "source_correct", "omitted", "fabricated_value", "wrong_entity_value", "unsupported_citations")},
        })
write_csv("summary.csv", summary)
write_csv("fact_details.csv", fact_rows)
write_csv("cost_scenarios.csv", cost_rows)

quality_rows = [[LABELS[row["length"]], row["condition"], "正解", "正解", f"{row['facts_correct_count']}/8",
                 f"{row['citation_id_correct_count']}/9", row["unsupported_citations"], "遵守" if row["format_compliant"] else "囲みあり・不遵守",
                 "成功" if row["strict_success"] else "不成功"] for row in summary]
usage_rows = [[LABELS[row["length"]], row["condition"], f"{row['wall_seconds']:.3f}",
               *(f"{row[key]:,}" for key in ("normal_input_tokens", "cache_read_tokens", "cache_write_tokens", "total_input_tokens",
                                            "output_tokens_including_thinking", "thinking_tokens")), f"${row['api_equivalent_usd_saved']:.6f}"] for row in summary]
fact_table = []
for field, label in FACT_LABELS.items():
    expected = DETAILS[0]["expected_answer"]["facts"][field]["value"]
    values = [select(length, "default")["actual_answer"]["facts"][field]["value"] for length in LENGTHS]
    fact_table.append([f"{label} `{field}`", "null" if expected is None else expected,
                       *("null" if value is None else value for value in values), "正解・3/3", "正解・3/3"])

condition_quality = []
condition_time = []
condition_thinking = []
condition_cost = []
cache_table = []
comparisons = []
for length in LENGTHS:
    old, medium, high = [select(length, effort) for effort in ("default", "medium", "high")]
    group = (old, medium, high)
    condition_quality.append([LABELS[length], *(f"補助{d['fact_correct_count']}/8、ID{d['citation_id_correct_count']}/9、JSON{'○' if d['record']['scoring']['format_compliant'] else '×'}" for d in group)])
    condition_time.append([LABELS[length], *(f"{d['record']['wall_seconds']:.3f}秒" for d in group)])
    condition_thinking.append([LABELS[length], *(f"{d['record']['claude']['thinking_tokens']:,}" for d in group)])
    condition_cost.append([LABELS[length], *(f"${d['normalized_costs']['all_input_cache_write_1h_usd']:.6f}" for d in group)])
    cache_table.append([LABELS[length], *(f"{d['cache_read_share']*100:.2f}%" for d in group)])
    comparisons.append({
        "length": length, "medium_seconds_vs_45_percent": (medium["record"]["wall_seconds"] / old["record"]["wall_seconds"] - 1) * 100,
        "high_seconds_vs_medium_percent": (high["record"]["wall_seconds"] / medium["record"]["wall_seconds"] - 1) * 100,
        "high_thinking_vs_medium_percent": (high["record"]["claude"]["thinking_tokens"] / medium["record"]["claude"]["thinking_tokens"] - 1) * 100,
        "high_all_write_cost_vs_medium_percent": (high["normalized_costs"]["all_input_cache_write_1h_usd"] / medium["normalized_costs"]["all_input_cache_write_1h_usd"] - 1) * 100,
        "45_all_write_cost_div_medium": old["normalized_costs"]["all_input_cache_write_1h_usd"] / medium["normalized_costs"]["all_input_cache_write_1h_usd"],
    })
write_csv("condition_comparisons.csv", comparisons)

quality_changes = []
for effort in ("default", "medium", "high"):
    short = select("short", effort)
    for length in ("medium", "long90k"):
        longer = select(length, effort)
        for metric in ("extraction_correct", "composition_correct", "fact_accuracy", "citation_accuracy", "omitted_facts", "fabricated_values", "wrong_entity_values", "strict_success"):
            before, after = short["record"]["scoring"][metric], longer["record"]["scoring"][metric]
            quality_changes.append({"condition": condition(short), "length": length, "metric": metric,
                                   "short_value": before, "longer_value": after, "longer_minus_short": after - before,
                                   "independent_problems": 1, "runs_per_cell": 1})
write_csv("quality_length_changes.csv", quality_changes)

report = f"""# Haiku 4.5と5.5の長文処理比較：保存済み9試行

分析日：2026-10-14。既存結果・正解・採点基準は変更せず、追加の実モデル実行も行っていない。

## 結論と、確認できる範囲

**この1問題では、Haiku 5.5の補助情報・根拠・JSON形式の品質が4.5より良く、実行時間とAPI換算費用にも優位な観測結果がある。一方、「資料が長くなったときの正解率低下が5.5で小さい」という仮説を支持する差は確認できない。**

| 区分 | 今回の判断 |
| --- | --- |
| 事実 | 主要情報抽出と最終結論は9/9試行で正解。最終料金は4,830、経路はreview。 |
| 事実 | 4.5は全長で補助5/8、Markdown囲み付き。5.5 medium/highは全長で補助8/8、根拠ID9/9、JSON形式遵守。 |
| 事実 | 4.5の補助正解数は短文→中程度→9万版で5→5→5。5.5は両Effortとも8→8→8。 |
| 推測 | 4.5の誤りは例外規定そのものと、今回の取引に適用した値の混同で説明できる可能性がある。内部の読み取り過程は確認できない。 |
| 未検証の仮説 | 独立した問題、例外が適用される条件、反復、異なる根拠位置でも5.5の品質や速度が優位か。 |

## 対象と比較条件

独立した業務問題は**seed 101の1問**である。同じ問い・正解の3種類の資料長を3モデル条件で各1回実行した9試行であり、独立した9問でも、各条件3回の同一入力反復でもない。各セルの観測数は1。統計的有意差、一般的なモデル能力差、長文耐性の因果効果は結論づけない。

{table(["資料", "ケースID", "資料ASCII文字・バイト", "送信プロンプトのバイト", "目標資料トークン"], [[LABELS[length], select(length, "default")["record"]["case_id"], f"{select(length, 'default')['record']['case_config']['document_bytes']:,}", f"{select(length, 'default')['prompt_bytes']:,}", f"{select(length, 'default')['record']['case_config']['target_tokens']:,}"] for length in LENGTHS])}

目標値は4文字/トークンの近似。資料だけの実測トークン数は全試行で未測定（null）。以下の総入力は、CLIの通常入力＋キャッシュ読み込み＋キャッシュ書き込みであり、CLIのシステム入力等を含む。モデル間では同じプロンプトSHA256・バイト列を送信しているが、報告入力数は異なる。9万相当でも5.5の総入力は約12万である。

中央配置は基本料金・通常経路の根拠を中央に置く設定で、他の2根拠は約5%・95%に分散する。similarは約20%の無関係レコードに似たIDを使う。資料長が増えると無関係レコード数と根拠間の絶対距離も増えるため、文章量だけの完全な分離には限界がある。

質問はP4190-Aのeducation区分、migration取引。基本料金6,900に30%割引を適用し、renewalだけの例外追加料金500・経路manualは今回適用しない。したがって4,830・reviewが最終正解。例外が適用されない分岐の1問なので、例外規定の抽出に失敗しても最終結論が正しくなる余地がある。

条件は4.5/default（Effort指定なし）と5.5/medium・high。**推論設定は同等ではない。** 共通の出力予約8,000はThinkingを含み、Thinking予算の上書きは記録上なし。有効なThinking予算は不明である。5.5のEffortフラグと機能有効は記録できるが、実効レベルの名前・数値をCLI出力から独立確認できない。

全試行はClaude Code 2.1.299、claude.ai認証、単一ユーザーメッセージを標準入力で送信。各資料長で実行順は4.5→5.5 medium→5.5 high。highは常にmediumの後なので、順序とキャッシュの影響が交絡している。

## 回答品質の横並び比較

{table(["資料", "Haiku 4.5 default", "Haiku 5.5 medium", "Haiku 5.5 high"], condition_quality)}

{table(["資料", "条件", "主要抽出", "最終結論", "補助項目", "根拠ID一致", "値を支えない引用", "JSON形式", "厳格成功"], quality_rows)}

補助8項目には主要抽出の2項目（基本料金・通常経路）を含む。7項目に明示値があり、猶予日数は対象製品にないためnull・根拠空リストが正解。根拠ID一致はこの8項目＋最終結論の計9項目のID集合一致を測る。**IDが正しくても、その箇所が回答値を支えているとは限らない。**

### 4.5の3項目の誤りはどう変わったか

{table(["項目", "正解", "4.5短文", "4.5中程度", "4.5・9万版", "5.5 medium", "5.5 high"], fact_table)}

例外3項目の正しい根拠はすべてS367640。

{table(["項目", "短文：値／引用ID", "中程度：値／引用ID", "9万版：値／引用ID"], [[field, *[f"{json.dumps(select(length, 'default')['actual_answer']['facts'][field]['value'], ensure_ascii=False)} / {','.join(select(length, 'default')['actual_answer']['facts'][field]['sources']) or '空リスト'}" for length in LENGTHS]] for field in ("exception_kind", "exception_surcharge", "exception_route")])}

短文→中程度では例外対象種別の引用IDがS559257からS367640に改善するが、値migrationは誤ったまま。これによりID一致率は8/9→9/9になるが、回答値を支えない引用は3件のままで、内容品質の完全な改善を意味しない。9万版では対象種別の引用が空になり、追加料金・処理経路がnullに変わる。補助正解数は5/8のまま、見落としが0→0→2件となった。

{table(["資料・条件", "見落とし", "採点上の捏造値", "採点上の別対象値", "値と根拠が両方正しい補助項目"], [[LABELS[d['record']['case_config']['length']]+' / '+condition(d), d['record']['scoring']['omitted_facts'], d['record']['scoring']['fabricated_values'], d['record']['scoring']['wrong_entity_values'], f"{d['value_supported_fact_count']}/8"] for d in DETAILS])}

`fabricated_values`は同名フィールドの資料内値一覧にない値、`wrong_entity_values`は不正解だが同名フィールドとして別の資料レコードにはある値という既存分類である。4.5短文・中程度の0/reviewは「例外追加料金・例外経路」の明示値ではないため採点上は捏造2件だが、今回は追加料金なし・通常経路reviewという適用結果自体は正しい。自由な作り話をしたと断定せず、**規定の明示値と適用結果の混同の可能性**として解釈する。

4.5のmigrationも質問自身の取引種別と一致する。採点上の別対象値1件は、実際に別製品から借用した証明ではない。9回答とも明示的に別製品の根拠IDを引用した箇所はない。5.5の6回答では既存採点で見落とし・捏造値・別対象値・非支持引用はすべて0。観測できない内部の混入まで不存在とは断定しない。

4.5は3回答すべて単一JSONのMarkdown囲み付きで、生JSON形式には不遵守。既存の囲み除去だけで解析可能になり、スキーマは全9回答で有効。内容誤りと形式不備を分けて扱っている。5.5 medium/highは全長で生JSON・スキーマとも遵守。

## 実行時間、使用量、API換算費用

出力トークンはThinkingを含む。Thinkingを別に加算しない。時間は保存された壁時計時間で、CLI起動等も含む。CLI報告のAPI時間はsummary.csvにも収録したが、純粋なモデル計算時間とは呼ばない。

{table(["資料", "条件", "秒", "通常入力", "キャッシュ読", "キャッシュ書", "総入力", "出力〔Thinking込み〕", "Thinking", "API換算USD"], usage_rows)}

全キャッシュ書き込みはログで1時間TTLと報告され、5分TTLは0。通常入力だけが2・9トークンでも、巨大資料を送っていないという意味ではない。キャッシュ書き込み・読み込みも入力に含める。

API換算費用は保存済みtrial.jsonの値。元のusageと料金から再計算した未丸め値はCLIのtotal_cost_usdと一致した。保存済み値との差は最大0.0000009 USDの丸め差であり、元結果は修正していない。サブスクリプションの追加請求額を示すものではない。

### キャッシュの影響を分けた費用比較

{table(["キャッシュ読み込み比率", "4.5 default", "5.5 medium", "5.5 high"], cache_table)}

highは97.64%→99.44%→99.68%をキャッシュから読み込み、mediumは3.26%→3.25%→1.85%、4.5は0%。highの実測費用の低さには、先行medium実行からのキャッシュ再利用と整合する大きな影響がある。どのトークンが先行実行由来かの全対応は確認できない。

費用だけを同じキャッシュ条件にそろえるため、各試行の実測総入力・実測出力・適用料金帯を維持して、総入力がすべて1時間キャッシュ書き込みだった場合を計算した。これは反実仮想の算術換算であり、実際に再実行した値ではない。出力・Thinkingや速度にキャッシュが与える影響まで補正するものでもない。

{table(["全入力を1時間書き込みに換算", "4.5 default", "5.5 medium", "5.5 high"], condition_cost)}

同条件換算でも5.5は安いが、4.5に対するmediumの価格比は短文約8.50倍、中程度約7.71倍、9万版約1.56倍へ縮小する。9万版highの実測$0.011490をmediumの$0.121960と比較して、high固有の費用効率だと判断してはいけない。同条件換算ではhighの方が約1.4%高い。

Haiku 5.5は1リクエストの総入力が100,000を超えると、入力・出力・キャッシュの全単価が5倍になる。キャッシュ読み書きも閾値判定に含む。9万相当の資料でも総入力120,705/120,704なので該当し、ログの倍率5とCLI費用も整合する。[Anthropic公式料金表](https://platform.claude.com/docs/en/about-claude/pricing)（2026-10-14確認）

今回の単価（USD/100万トークン）は4.5が通常入力1・出力5・1時間書込2・読込0.1、5.5の10万以下が0.1・0.5・0.2・0.01、10万超が0.5・2.5・1・0.05。同料金表の数値を保存済み単価と照合した。`cost_scenarios.csv`には全入力通常課金・全入力1時間書込・全入力キャッシュ読込の3換算を収録した。

mediumの費用増は$0.003932→$0.013937→$0.121960。中程度→9万版で入力は約1.76倍だが費用は約8.75倍となり、資料量増加に加えて5倍料金帯の影響がある。highも$0.000972→$0.001620→$0.011490で、Thinking増と料金帯の両方が影響する。安さは推論能力の向上の証拠ではなく、単価・キャッシュ・使用量を含む運用上の結果である。

## 疑問A：資料長でどちらの正確性が低下するか

**主要抽出・最終結論・補助正解数について、今回どちらにも長さに伴う正解率低下は観測されなかった。** 4.5は補助5/8の不正解が最初から存在し、5.5は8/8を維持している。主要指標も補助正解率も、9万版−短文の変化量は全条件0。したがって5.5と4.5の「長さによる変化量の差」も0である。

根拠ID一致は4.5で8/9→9/9→8/9と非単調、5.5は9/9で一定。4.5の9万版では補助2項目がnullになり、欠落への変化を観測したが、これだけで長文による因果的劣化と断定しない。根拠本文は存在し、境界確認も通るが、その事実からモデル内部で例外規定を完全保持したとは分からない。

最終結論が全正解という天井効果に加え、今回は例外が非適用の分岐である。今回のデータは「長文で5.5だけ正解を維持した」という証拠ではない。5.5の品質差は短文から存在する。

## 疑問B：進化は品質より速度・費用に出ているか

品質にも明確な観測差があり、速度・費用だけの差ではない。全長で5.5は補助8/8・正しい根拠・JSON形式を満たす一方、4.5は補助5/8・形式不備である。ただしこの1問と設定の組み合わせでの比較であり、モデル単体の一般的な進化を切り分けた結果ではない。

{table(["実測の壁時計時間", "4.5 default", "5.5 medium", "5.5 high"], condition_time)}

mediumは4.5より短文33.6%、中程度34.0%、9万版58.5%短い実測時間。mediumのキャッシュ読込は各長さで低いため、highだけの大量キャッシュ読込ではこの傾向を説明できない。一方、起動・配信・負荷・生成量などを統制しておらず、費用換算から時間を補正することもできない。純粋な読み取り速度やtokens/secondの比較とは扱わない。

{table(["Thinkingトークン", "4.5 default", "5.5 medium", "5.5 high"], condition_thinking)}

4.5のThinkingは1,076→783→1,837、mediumは1,188→931→1,037、highは1,155→1,406→1,722。4.5・mediumは単調増加ではなく、highは今回単調に増えた。Thinkingの少なさ自体を高い品質・推論効率の証明にはしない。短文ではmediumのThinkingと出力は4.5より多いのに壁時計時間は短い。

## 疑問C：mediumとhighに違いがあるか

品質は全長で同じ満点。highによる品質改善は今回観測できない。短文のhighはmediumより0.404秒短くThinkingが33少ない。一方、中程度は2.194秒長くThinkingが475多く、9万版は2.084秒長くThinkingが685多い。後者2サイズでは時間約24〜26%増、Thinking約51〜66%増である。

この増加は高いEffortと整合するが、各1回・固定実行順・大きく異なるキャッシュ状態のため、Effortによる因果効果とは断定しない。highは大量キャッシュ読込があっても中程度・9万版でmediumより遅かった、という観測事実までが言える。時間のキャッシュ補正を推定してmedium/highの固有速度を比較する根拠はない。

全入力1時間書込へ換算するとhighの費用はmedium比で短文−0.4%、中程度＋1.7%、9万版＋1.4%。高い実測キャッシュ読込によるhighの安さと、Effortの出力増による費用差を分けて扱う。

## モデル・コンテキスト・ログの確認範囲

4.5のassistantモデル記録はclaude-haiku-4-5-20251001、集計モデルはclaude-haiku-4-5。5.5のassistant・集計記録はclaude-haiku-5-5で、全9試行とも要求モデルに一致する。5.5はEffort機能有効、4.5は非アクティブと記録される。報告窓は4.5が200,000、5.5が1,000,000だが、共通運用上限180,000は別の安全方針であり、今回引き上げていない。

全試行で正常終了・1ターン・usage iterations 1・解析不能stdout行0・stderr空・context_alerts空・comparison_eligible true。受信エコーSHA256、保存stdin、保存プロンプトが一致し、先頭・中央・末尾の境界値も正解。ツール使用は観測0、initのツールとMCP一覧も空、compact_boundaryイベント0。追加モデルやモデル切り替えはログ上観測されない。

ただし、APIへの全入力配信、切り詰め、観測されなかった圧縮、内部のリトライやルーティングは確認できない。compaction_status・truncation_status・api_payload_integrityは全試行でunverifiedのまま。境界3点の一致は資料全体保持の証明ではない。1ターン・1 iterationは内部リトライ不存在を保証せず、費用の料金帯判定には報告1ターンを1リクエストとみなす仮定が残る。

9万版5.5のcost.notesには10万超の料金に関する注記が保存されている（日本語部分は文字化けあり）。これは切り詰め・圧縮の警告ではない。数値使用量・単価・倍率・CLI費用は照合できた。文字化けを含む既存記録は変更していない。

短文・中程度と9万版で生成器・CLIモジュールのソースハッシュは異なる（9万設定追加）。採点モジュールのハッシュは全9試行で同じ。保存入力を現在の生成器で再生成して一致を確認し、問い・採点対象の正解も全長で一致した。再採点は既存関数を読み取り検証に使っただけで、保存結果や採点基準を変更していない。

## 次に試すべきこと（提案のみ）

最初に、4.5の3項目の誤りが質問解釈の違いかを切り分けたい。新しいプロンプト版として「例外規定に書かれた値を、今回適用されなくてもそのまま抽出する」と明示する対照条件を設ける。既存版と結果は残し、別条件として比較する。これで改善するなら、今回の品質差の一部は長文検索能力ではなく指示解釈に由来する可能性が高まる。

次の能力比較では、異なるseedを使って割引の適用/非適用と例外の適用/非適用を含む独立問題を増やし、同じ問題の短文・9万版を対応させる。特に例外適用時には、例外規定の抽出失敗が最終料金・経路にも現れる。必要なら中程度を後で足す。既存の不変な正解計算と採点を再利用できる。

同一入力の反復と独立問題数を別に管理し、主要抽出・最終結論に加えて補助正解率、値を支える根拠、JSON形式の長文−短文差を事前に主指標として固定する。根拠位置とsimilar/neutralの比較は別の因子として追加し、長さ・紛らわしさの効果を分ける。

速度・Effort比較ではmedium/highの実行順を交互にし、可能な範囲でキャッシュ条件をそろえて記録する。キャッシュ条件をそろえられない場合は、coldに近い観測とwarm観測を別集計し、費用だけ算術換算、時間は未補正と明記する。出力・Thinking・CLI/API報告時間を継続保存し、試行間ばらつきを確認する。

この提案に伴う資料生成・実モデル実行は今回行っていない。実行件数と費用を事前確認し、共通安全枠は維持する。現時点ではmediumがこの問題に必要な品質を満たし、high追加の品質利得は検出できていない。

## 成果物と検証

| ファイル | 内容 |
| --- | --- |
| report.md | 本日本語レポート |
| summary.csv | 9試行、品質・具体的誤りの項目名・全使用量・費用・モデル/Effort・ログ確認範囲 |
| fact_details.csv | 9試行×8項目の72行。正解/回答値・根拠ID・既存採点フラグ |
| cost_scenarios.csv | 9試行の実測費用とキャッシュ条件3種の換算 |
| condition_comparisons.csv | 各長さの時間・Thinking・換算費用の条件間差 |
| quality_length_changes.csv | 補助・根拠・欠落・形式等を含む、短文からの対応差48行 |
| trials.csv | 既存レポート出力による9試行の明細 |
| paired_length_changes.csv / hypothesis_comparisons.csv | 既存主指標の長さ差・モデル間差。すべて0 |
| analysis.json | 検証済み詳細、正解/回答、単価、108ファイルのSHA256。既存Git方針で管理外 |
| render_report.py | analysis.jsonから表・CSV・レポートを再生成する分析専用スクリプト。モデル呼び出しなし |
| prepare_snapshot.py | 保存済み9試行を照合し、Git管理外のanalysis.jsonを再構築するスクリプト |
| pilot_config.json / README.md | 固定した資料・モデル条件と、資料生成・校正・分析の再現手順 |

分析を再生成するには、元の9試行をresults/long_context_runs/に配置し、リポジトリルートで `python -X utf8 -m analysis.long_context_comparison_20261014.prepare_snapshot`、続いて `python -X utf8 analysis/long_context_comparison_20261014/render_report.py` を実行する。生成資料と校正の再現手順はこのディレクトリのREADME.mdを参照。これらの手順ではモデルを呼ばない。

入力元はsummary.csvのexperiment列に示す9ディレクトリ（results/long_context_runs/以下）。108個の入力元ファイルのSHA256を読み取り前後で比較し、変更なしを確認した。元回答・元CLI usage・保存使用量・Thinking・保存採点・料金を照合した。対象の試行は9、独立問題は1、各セルは1試行、除外は0である。実験コードを追加変更せず、既存の正解・採点基準も変更していない。追加のモデルリクエスト、commit、push、タグ作成は0。
"""
(ROOT / "report.md").write_text(report, encoding="utf-8")
DATA["condition_comparisons"] = comparisons
DATA["quality_length_changes_extended"] = quality_changes
DATA["summary_columns"] = list(summary[0])
(ROOT / "analysis.json").write_text(json.dumps(DATA, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(f"Rendered {len(summary)} trials, {len(fact_rows)} fact rows and {len(quality_changes)} paired metric changes.")
