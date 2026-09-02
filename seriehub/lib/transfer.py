"""移籍報道の分類と確度判定。

移籍情報は本質的に飛ばし記事を含む。「誰が言っているか(tier)」と
「何と言っているか(kind)」を分けて評価し、確定・有力・噂の3段階に落とす。
判定根拠は reasons として残し、サイト上でも開示する。
"""

from __future__ import annotations

import re

from .matching import normalize

# kind ごとの検出語。順序に意味があり、上にあるものほど「話が進んでいる」。
_KIND_PATTERNS: list[tuple[str, list[str]]] = [
    ("signing", [
        # イタリア語
        r"ufficiale", r"\bfirmato\b", r"\bfirma\b", r"ha firmato", r"e un nuovo",
        r"benvenuto", r"annuncio", r"annunciato", r"tesserato", r"acquisto ufficiale",
        r"colpo chiuso", r"\bchiuso\b",
        # 英語
        r"\bsigns\b", r"\bjoins\b", r"\bcompleted\b", r"\bunveiled\b",
        # 日本語
        r"完全移籍", r"加入が決定", r"獲得を発表", r"移籍が決定", r"正式発表", r"契約締結",
    ]),
    ("medical", [
        r"visite mediche", r"idoneita sportiva",
        r"\bmedical\b", r"メディカルチェック", r"メディカル",
    ]),
    ("renewal", [
        r"\brinnovo\b", r"rinnovato", r"prolungamento", r"prolunga",
        r"contract extension", r"new deal", r"契約更新", r"契約延長",
    ]),
    ("exit", [
        r"\bcessione\b", r"\bceduto\b", r"\baddio\b", r"lascia il", r"\besubero\b",
        r"risoluzione", r"\bdeparture\b", r"\bleaves\b", r"退団", r"放出", r"契約解除",
    ]),
    ("talks", [
        r"\baccordo\b", r"\btrattativa\b", r"trattative", r"\bincontro\b", r"\bsummit\b",
        r"ai dettagli", r"fumata bianca", r"\bvicino\b", r"vicinissimo", r"in chiusura",
        r"\bofferta\b", r"\bagreement\b", r"\bdeal\b", r"advanced talks",
        r"交渉", r"オファー", r"合意", r"大詰め",
    ]),
    ("rumour", [
        r"\bsondaggio\b", r"\bidea\b", r"\bobiettivo\b", r"\bpiace\b", r"\binteresse\b",
        r"\binteressa\b", r"\bsuggestione\b", r"nome nuovo", r"\bcontatti\b", r"\bvoci\b",
        r"\bpista\b", r"\bsirene\b", r"\brumours?\b", r"\blinked\b", r"\btarget\b",
        r"関心", r"浮上", r"候補", r"噂",
    ]),
]

_COMPILED = [(kind, re.compile("|".join(pats))) for kind, pats in _KIND_PATTERNS]

# 「公式に発表された」と明言している語。tier が公式以外でも確定に引き上げる。
_OFFICIAL_MARKER = re.compile(r"ufficiale|comunicato ufficiale|\bofficial\b|公式発表|正式発表")

# 断定を避けている語。1段階引き下げる。
_HEDGE = re.compile(
    r"secondo (quanto|le)|si dice|indiscrezione|potrebbe|sarebbe|starebbe|"
    r"\breportedly\b|\bcould\b|\bmay\b|とみられる|模様|か\b|可能性"
)

_TIER_WEIGHT = {"official": 100, "primary": 40, "aggregator": 15, "translated": 10}
_KIND_WEIGHT = {"signing": 40, "medical": 30, "renewal": 25, "exit": 20, "talks": 15, "rumour": 0}

KIND_LABELS = {
    "signing": "加入・完了",
    "medical": "メディカル",
    "renewal": "契約更新",
    "exit": "退団・放出",
    "talks": "交渉中",
    "rumour": "噂・関心",
}

CONFIDENCE_LABELS = {
    "confirmed": "確定",
    "strong": "有力",
    "rumour": "噂",
}

TIER_LABELS = {
    "official": "公式",
    "primary": "一次報道",
    "aggregator": "まとめ",
    "translated": "翻訳・二次",
}


def classify(title: str, summary: str, tier: str) -> dict:
    """移籍報道かどうかを判定し、種別・確度・根拠を返す。

    戻り値の kind が "" の場合、移籍報道ではない（試合記事など）。
    """
    text = normalize(f"{title} {summary}")

    kind = ""
    for candidate, pattern in _COMPILED:
        if pattern.search(text):
            kind = candidate
            break
    if not kind:
        return {"kind": "", "confidence": "", "score": 0, "reasons": []}

    reasons: list[str] = []
    has_official_marker = bool(_OFFICIAL_MARKER.search(text))
    hedged = bool(_HEDGE.search(text))

    if tier == "official":
        confidence = "confirmed" if kind != "rumour" else "strong"
        reasons.append("リーグ/クラブ公式の発表")
    elif has_official_marker and kind in ("signing", "renewal", "exit", "medical"):
        confidence = "confirmed"
        reasons.append("記事が公式発表を明示")
    elif tier == "primary" and kind in ("signing", "medical", "renewal", "exit", "talks"):
        confidence = "strong"
        reasons.append("自社取材を持つ一次媒体の報道")
    elif tier == "aggregator" and kind in ("signing", "medical"):
        confidence = "strong"
        reasons.append("完了段階の報道だが伝聞媒体")
    else:
        confidence = "rumour"
        reasons.append("伝聞または関心段階")

    if hedged and confidence == "confirmed":
        confidence = "strong"
        reasons.append("断定を避けた表現のため1段階引き下げ")
    elif hedged and confidence == "strong":
        confidence = "rumour"
        reasons.append("断定を避けた表現のため1段階引き下げ")

    score = _TIER_WEIGHT.get(tier, 0) + _KIND_WEIGHT.get(kind, 0)
    return {"kind": kind, "confidence": confidence, "score": score, "reasons": reasons}
