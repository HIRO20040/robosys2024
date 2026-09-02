"""サイト全体で受け渡すデータ構造。

収集層 (news / providers) がこれらを組み立て、描画層 (render) はこれ以外を
知らない。JSON に落として `data/` に貯めるので、すべて to_dict/from_dict を持つ。
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any


def _iso(dt: datetime | None) -> str | None:
    return dt.astimezone(timezone.utc).isoformat() if dt else None


def _parse_iso(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None


@dataclass
class Club:
    slug: str
    name_it: str
    short_it: str
    name_ja: str
    aliases: list[str] = field(default_factory=list)
    city: str = ""
    city_ja: str = ""
    stadium: str = ""
    founded: int | None = None
    colors: list[str] = field(default_factory=lambda: ["#444444", "#FFFFFF"])
    site: str = ""
    # 実行時に順位表/APIから解決される所属リーグ ("SA" / "SB" / "")
    league: str = ""

    @property
    def primary_color(self) -> str:
        return self.colors[0] if self.colors else "#444444"

    @property
    def secondary_color(self) -> str:
        return self.colors[1] if len(self.colors) > 1 else "#FFFFFF"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Article:
    """1本の記事。原文を正とし、訳文は付加情報として並走させる。"""

    id: str
    title: str                      # 原文見出し
    url: str
    source_id: str
    source_name: str
    tier: str                       # official / primary / aggregator / translated
    lang: str
    published: datetime | None = None
    summary: str = ""               # 原文要約（RSS の description を短縮したもの）
    title_ja: str = ""              # 翻訳された見出し（無い場合は空）
    summary_ja: str = ""
    clubs: list[str] = field(default_factory=list)   # 言及クラブの slug
    leagues: list[str] = field(default_factory=list)
    # 移籍報道としての分類（該当しない場合 kind は ""）
    transfer_kind: str = ""         # signing / talks / rumour / renewal / exit / medical
    transfer_confidence: str = ""   # confirmed / strong / rumour
    transfer_score: int = 0

    @property
    def is_transfer(self) -> bool:
        return bool(self.transfer_kind)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["published"] = _iso(self.published)
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Article":
        d = dict(d)
        d["published"] = _parse_iso(d.get("published"))
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in d.items() if k in known})


@dataclass
class PlayerSlot:
    """スタメン/ベンチの1枠。"""

    name: str
    number: int | None = None
    position: str = ""
    grid: str = ""          # "4:2" のようなフォーメーション上の位置（API 由来）

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class TeamLineup:
    club_slug: str
    club_name: str
    formation: str = ""
    coach: str = ""
    start: list[PlayerSlot] = field(default_factory=list)
    bench: list[PlayerSlot] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "club_slug": self.club_slug,
            "club_name": self.club_name,
            "formation": self.formation,
            "coach": self.coach,
            "start": [p.to_dict() for p in self.start],
            "bench": [p.to_dict() for p in self.bench],
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "TeamLineup":
        return cls(
            club_slug=d.get("club_slug", ""),
            club_name=d.get("club_name", ""),
            formation=d.get("formation", ""),
            coach=d.get("coach", ""),
            start=[PlayerSlot(**p) for p in d.get("start", [])],
            bench=[PlayerSlot(**p) for p in d.get("bench", [])],
        )


@dataclass
class Match:
    id: str
    league: str                     # SA / SB
    matchday: int | None
    kickoff: datetime | None
    status: str                     # SCHEDULED / LIVE / FINISHED
    home_slug: str
    away_slug: str
    home_name: str
    away_name: str
    home_score: int | None = None
    away_score: int | None = None
    venue: str = ""
    source: str = ""                # 取得元プロバイダ名（出典明示のため）
    home_lineup: TeamLineup | None = None
    away_lineup: TeamLineup | None = None

    @property
    def has_lineups(self) -> bool:
        return bool(self.home_lineup and self.home_lineup.start)

    @property
    def score_text(self) -> str:
        if self.home_score is None or self.away_score is None:
            return "-"
        return f"{self.home_score} - {self.away_score}"

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["kickoff"] = _iso(self.kickoff)
        d["home_lineup"] = self.home_lineup.to_dict() if self.home_lineup else None
        d["away_lineup"] = self.away_lineup.to_dict() if self.away_lineup else None
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Match":
        d = dict(d)
        d["kickoff"] = _parse_iso(d.get("kickoff"))
        for side in ("home_lineup", "away_lineup"):
            d[side] = TeamLineup.from_dict(d[side]) if d.get(side) else None
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in d.items() if k in known})


@dataclass
class StandingRow:
    position: int
    club_slug: str
    club_name: str
    played: int = 0
    won: int = 0
    drawn: int = 0
    lost: int = 0
    goals_for: int = 0
    goals_against: int = 0
    points: int = 0

    @property
    def goal_diff(self) -> int:
        return self.goals_for - self.goals_against

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["goal_diff"] = self.goal_diff
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "StandingRow":
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in d.items() if k in known})


@dataclass
class SourceHealth:
    """フィードごとの死活。サイトの「情報源」ページに出して透明性を確保する。"""

    source_id: str
    name: str
    tier: str
    url: str
    ok: bool
    entries: int = 0
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
