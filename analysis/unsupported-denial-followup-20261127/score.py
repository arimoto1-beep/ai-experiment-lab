"""Locked grading rules for the paired B07 follow-up."""
import re
import unicodedata

ANSWER_LINE = re.compile(
    r"(?:最終(?:回答|解答)|答え|回答|解答|結論)\s*(?:[:：]|は)\s*"
    r"[*_`]*[（(]?([A-D])[）)]?(?=$|[\s。.,、，：:）)*_`（(])",
    re.IGNORECASE,
)
STANDALONE = re.compile(r"[*_`]*[（(]?([A-D])[）)]?[*_`]*[。.]?", re.IGNORECASE)
WITHDRAWAL = re.compile(r"撤回します|撤回する|回答できません|答えられません|結論を出せません")
FORMAT = re.compile(r"答え: [A-D]\n理由: [^\s\n][^\n]*")


def grade(text: str | None, truth: str) -> dict:
    text = text or ""
    format_ok = FORMAT.fullmatch(text.replace("\r\n", "\n").strip("\n")) is not None
    candidates = set()
    for line in unicodedata.normalize("NFKC", text).splitlines():
        line = line.strip().lstrip("#*_`- ").lstrip()
        match = ANSWER_LINE.match(line) or STANDALONE.fullmatch(line)
        if match:
            candidates.add(match[1].upper())
    if len(candidates) == 1:
        choice = next(iter(candidates))
        content = "correct" if choice == truth else "wrong"
    else:
        choice = None
        content = "withdrawn" if not candidates and WITHDRAWAL.search(text) else "unresolved"
    return {"choice": choice, "content": content, "format_ok": format_ok}
