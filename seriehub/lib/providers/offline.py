"""fixtures/ の JSON を読むだけのプロバイダ。

APIキーも外部通信も無い環境でパイプラインとサイト描画を検証するために使う。
返すデータは架空のサンプルであり、実在の試合結果ではない。
サイト側は offline ビルドである旨のバナーを必ず表示する。
"""

from __future__ import annotations

import json
from pathlib import Path

from ..models import Match, StandingRow
from .base import SERIE_A, SERIE_B, Provider


class OfflineProvider(Provider):
    name = "offline-fixtures"
    supported_leagues = (SERIE_A, SERIE_B)

    def __init__(self, fixtures_dir: Path):
        self.dir = Path(fixtures_dir)

    @property
    def configured(self) -> bool:
        return self.dir.exists()

    def _load(self, filename: str) -> dict:
        path = self.dir / filename
        if not path.exists():
            return {}
        return json.loads(path.read_text(encoding="utf-8"))

    def standings(self, league: str, season: int) -> list[StandingRow]:
        data = self._load("sample_standings.json")
        return [StandingRow.from_dict(r) for r in data.get(league, [])]

    def matches(self, league: str, season: int, days_back: int = 14, days_ahead: int = 14) -> list[Match]:
        data = self._load("sample_matches.json")
        return [Match.from_dict(m) for m in data.get(league, [])]

    def attach_lineups(self, matches: list[Match]) -> int:
        # サンプルデータにはあらかじめスタメンが入っている
        return sum(1 for m in matches if m.has_lineups)
