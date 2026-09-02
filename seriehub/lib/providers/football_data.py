"""football-data.org プロバイダ（セリエA）。

無料プランで Serie A (コード SA) の順位表と日程・結果が取れる。
セリエBとスタメンは無料プランの対象外なので、そこは API-Football に任せる。
APIキー: 環境変数 FOOTBALL_DATA_TOKEN
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from ..models import Match, StandingRow
from .base import SERIE_A, HttpProvider

_STATUS_MAP = {
    "FINISHED": "FINISHED", "AWARDED": "FINISHED",
    "IN_PLAY": "LIVE", "PAUSED": "LIVE",
    "TIMED": "SCHEDULED", "SCHEDULED": "SCHEDULED",
    "POSTPONED": "POSTPONED", "SUSPENDED": "POSTPONED", "CANCELLED": "POSTPONED",
}


class FootballDataProvider(HttpProvider):
    name = "football-data.org"
    supported_leagues = (SERIE_A,)
    base_url = "https://api.football-data.org/v4"

    def __init__(self, api_key: str = "", matcher=None):
        super().__init__(api_key, request_pause=6.5)   # 無料プランは 10 req/min
        self.matcher = matcher

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def headers(self) -> dict[str, str]:
        return {"X-Auth-Token": self.api_key}

    def _slug(self, name: str) -> str:
        if self.matcher:
            return self.matcher.resolve(name) or ""
        return ""

    def standings(self, league: str, season: int) -> list[StandingRow]:
        data = self.get(f"/competitions/{league}/standings", {"season": season})
        rows: list[StandingRow] = []
        for table in data.get("standings", []):
            if table.get("type") != "TOTAL":
                continue
            for entry in table.get("table", []):
                team = entry.get("team", {})
                name = team.get("shortName") or team.get("name", "")
                rows.append(StandingRow(
                    position=entry.get("position", 0),
                    club_slug=self._slug(team.get("name", "") or name),
                    club_name=name,
                    played=entry.get("playedGames", 0),
                    won=entry.get("won", 0),
                    drawn=entry.get("draw", 0),
                    lost=entry.get("lost", 0),
                    goals_for=entry.get("goalsFor", 0),
                    goals_against=entry.get("goalsAgainst", 0),
                    points=entry.get("points", 0),
                ))
            break
        return rows

    def matches(self, league: str, season: int, days_back: int = 14, days_ahead: int = 14) -> list[Match]:
        today = datetime.now(timezone.utc).date()
        data = self.get(f"/competitions/{league}/matches", {
            "dateFrom": (today - timedelta(days=days_back)).isoformat(),
            "dateTo": (today + timedelta(days=days_ahead)).isoformat(),
        })
        out: list[Match] = []
        for m in data.get("matches", []):
            home, away = m.get("homeTeam", {}), m.get("awayTeam", {})
            score = (m.get("score") or {}).get("fullTime") or {}
            kickoff = m.get("utcDate")
            out.append(Match(
                id=f"fd-{m.get('id')}",
                league=league,
                matchday=m.get("matchday"),
                kickoff=datetime.fromisoformat(kickoff.replace("Z", "+00:00")) if kickoff else None,
                status=_STATUS_MAP.get(m.get("status", ""), "SCHEDULED"),
                home_slug=self._slug(home.get("name", "")),
                away_slug=self._slug(away.get("name", "")),
                home_name=home.get("shortName") or home.get("name", ""),
                away_name=away.get("shortName") or away.get("name", ""),
                home_score=score.get("home"),
                away_score=score.get("away"),
                source=self.name,
            ))
        return out
