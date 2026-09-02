"""記事本文からクラブを同定する。

RSS の見出しは "Inter, accordo per il rinnovo" のように主語が略される。
クラブ辞書の別名を使って本文を走査し、言及クラブの slug を返す。

ラテン文字の別名は単語境界付きで照合する。これをしないと
"Milano"(都市名) が "Milan"(クラブ) に、"Interesse" が "Inter" に誤爆する。
日本語の別名には単語境界が無いので部分一致で照合する。
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from .models import Club

# 単独で現れると誤爆しやすく、文脈語とセットでのみ採用する別名
_AMBIGUOUS = {"roma", "milano", "torino", "genova", "napoli", "parma", "como", "monza"}
# 上の語がクラブを指していると判断できる周辺語
_CLUB_CONTEXT = re.compile(
    r"(calcio|serie\s*[ab]|allenatore|mister|mercato|derby|stadio|squadra|club|"
    r"gol|partita|formazione|panchina|acquisto|cessione|rinnovo|as\s+roma|"
    r"fc|ssc|us\b|ac\b|セリエ|移籍|監督|試合|クラブ)",
    re.IGNORECASE,
)


def normalize(text: str) -> str:
    """アクセント記号を落として小文字化する（Südtirol / Sudtirol を同一視）。"""
    if not text:
        return ""
    decomposed = unicodedata.normalize("NFD", text)
    stripped = "".join(c for c in decomposed if unicodedata.category(c) != "Mn")
    return unicodedata.normalize("NFC", stripped).lower()


def _is_latin(s: str) -> bool:
    return all(ord(c) < 0x3000 for c in s)


def _boundary(alias: str) -> str:
    """ラテン文字の別名を語として照合する正規表現。

    左端はアポストロフィを許す。イタリア語では冠詞が省略されて
    "l'Inter" / "dell'Inter" と書かれるのが普通で、これを弾くと
    肝心の記事を取りこぼす。右端は英数字を禁じ、"interesse" が
    "Inter" に、"Milano" が "Milan" に誤爆するのを防ぐ。
    """
    return rf"(?<![0-9a-z]){re.escape(alias)}(?![0-9a-z])"


@dataclass(frozen=True)
class _Alias:
    text: str                    # 正規化済みの別名
    pattern: re.Pattern | None   # ラテン文字のときだけ単語境界付きパターン
    slug: str
    ambiguous: bool


class ClubMatcher:
    """クラブ辞書から別名インデックスを組み、テキストを照合する。"""

    def __init__(self, clubs: list[Club]):
        self.clubs = {c.slug: c for c in clubs}
        # 別名ごとに (正規化した別名, 照合用パターン, slug, 曖昧フラグ) を持つ。
        # 正規表現から別名を復元するのは壊れやすいので、別名そのものを保持する。
        self._aliases: list[_Alias] = []
        for club in clubs:
            names = {club.name_it, club.short_it, club.name_ja, *club.aliases}
            for raw in names:
                if not raw or len(raw) < 2:
                    continue
                norm = normalize(raw)
                ambiguous = norm in _AMBIGUOUS
                pattern = re.compile(_boundary(norm)) if _is_latin(norm) else None
                self._aliases.append(_Alias(norm, pattern, club.slug, ambiguous))
        # 長い別名を先に当てて "Juve Stabia" が "Juve" に食われないようにする
        self._aliases.sort(key=lambda a: -len(a.text))

    def find(self, title: str, body: str = "") -> list[str]:
        """言及クラブの slug を、確からしい順に返す。

        見出しでの一致は本文での一致より強い証拠として扱う。
        """
        norm_title = normalize(title)
        norm_body = normalize(body)
        haystack = f"{norm_title} {norm_body}"
        has_context = bool(_CLUB_CONTEXT.search(haystack))

        scores: dict[str, int] = {}
        for alias in self._aliases:
            if alias.pattern is not None:
                in_title = bool(alias.pattern.search(norm_title))
                in_body = bool(alias.pattern.search(norm_body))
            else:
                in_title = alias.text in norm_title
                in_body = alias.text in norm_body
            if not (in_title or in_body):
                continue
            # 曖昧な別名は、サッカー文脈が確認できるときだけ採用する
            if alias.ambiguous and not has_context:
                continue
            weight = 3 if in_title else 1
            scores[alias.slug] = max(scores.get(alias.slug, 0), weight)

        # "Juve Stabia" と "Juventus" が同時に立った場合、より長い一致だけ残す
        if "juventus" in scores and "juve-stabia" in scores:
            if re.search(r"(?<![\w'])juve\s*stabia(?![\w'])", haystack):
                if not re.search(r"(?<![\w'])juventus(?![\w'])", haystack):
                    scores.pop("juventus", None)

        return [slug for slug, _ in sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))]

    def resolve(self, api_name: str) -> str | None:
        """API が返すチーム名 ("Hellas Verona FC" 等) を slug に解決する。"""
        norm = normalize(api_name)
        if not norm:
            return None
        best: tuple[int, str] | None = None
        for alias in self._aliases:
            if alias.text and alias.text in norm:
                cand = (len(alias.text), alias.slug)
                if best is None or cand > best:
                    best = cand
        return best[1] if best else None
