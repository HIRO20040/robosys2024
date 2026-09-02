"""API-Football (api-sports.io v3) プロバイダ。

セリエA (league=135) と セリエB (league=136) の両方に対応し、
スタメン・ベンチ・フォーメーション・監督まで取得できる唯一のプロバイダ。
APIキー: 環境変数 API_FOOTBALL_KEY

注意: 無料プランは 1日100リクエスト、かつプランによって取得可能シーズンに
      制限がある。スタメンは試合1件につき1リクエスト消費するので、
      lineup_budget で取得件数に上限をかけている。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from ..models import Match, PlayerSlot, StandingRow, TeamLineup
from .base import SERIE_A, SERIE_B, HttpProvider, ProviderError

_LEAGUE_IDS = {SERIE_A: 135, SERIE_B: 136}

_STATUS_MAP = {
    "FT": "FINISHED", "AET": "FINISHED", "PEN": "FINISHED",
    "1H": "LIVE", "2H": "LIVE", "HT": "LIVE", "ET": "LIVE", "LIVE": "LIVE",
    "NS": "SCHEDULED", "TBD": "SCHEDULED",
    "PST": "POSTPONED", "CANC": "POSTPONED", "ABD": "POSTPONED", "SUSP": "POSTPONED",
}


class ApiFootballProvider(HttpProvider):
    name = "API-Football"
    supported_leagues = (SERIE_A, SERIE_B)
    base_url = "https://v3.football.api-sports.io"

    def __init__(self, api_key: str = "", matcher=None, lineup_budget: int = 20):
        super().__init__(api_key, request_pause=0.5)
        self.matcher = matcher
        self.lineup_budget = lineup_budget

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def headers(self) -> dict[str, str]:
        return {"x-apisports-key": self.api_key}

    def get(self, path: str, params: dict | None = None, retries: int = 3) -> dict:
        data = super().get(path, params, retries)
        # API-Football は HTTP 200 のままエラーを本文に載せてくる
        errors = data.get("errors")
        if errors and (isinstance(errors, dict) and errors or isinstance(errors, list) and errors):
            raise ProviderError(f"{self.name}: {errors}")
        return data

    def _slug(self, name: str) -> str:
        if self.matcher:
            return self.matcher.resolve(name) or ""
        return ""

    def standings(self, league: str, season: int) -> list[StandingRow]:
        data = self.get("/standings", {"league": _LEAGUE_IDS[league], "season": season})
        rows: list[StandingRow] = []
        for entry in data.get("response", []):
            for table in (entry.get("league") or {}).get("standings", []) or []:
                for r in table:
                    team = r.get("team", {})
                    all_ = r.get("all", {})
                    goals = all_.get("goals", {})
                    rows.append(StandingRow(
                        position=r.get("rank", 0),
                        club_slug=self._slug(team.get("name", "")),
                        club_name=team.get("name", ""),
                        played=all_.get("played", 0),
                        won=all_.get("win", 0),
                        drawn=all_.get("draw", 0),
                        lost=all_.get("lose", 0),
                        goals_for=goals.get("for", 0) or 0,
                        goals_against=goals.get("against", 0) or 0,
                        points=r.get("points", 0),
                    ))
                break
        return rows

    def matches(self, league: str, season: int, days_back: int = 14, days_ahead: int = 14) -> list[Match]:
        today = datetime.now(timezone.utc).date()
        data = self.get("/fixtures", {
            "league": _LEAGUE_IDS[league],
            "season": season,
            "from": (today - timedelta(days=days_back)).isoformat(),
            "to": (today + timedelta(days=days_ahead)).isoformat(),
            "timezone": "UTC",
        })
        out: list[Match] = []
        for item in data.get("response", []):
            fx = item.get("fixture", {})
            teams = item.get("teams", {})
            goals = item.get("goals", {})
            home, away = teams.get("home", {}), teams.get("away", {})
            kickoff = fx.get("date")
            round_name = (item.get("league") or {}).get("round", "")
            out.append(Match(
                id=f"af-{fx.get('id')}",
                league=league,
                matchday=_matchday(round_name),
                kickoff=datetime.fromisoformat(kickoff) if kickoff else None,
                status=_STATUS_MAP.get(((fx.get("status") or {}).get("short") or ""), "SCHEDULED"),
                home_slug=self._slug(home.get("name", "")),
                away_slug=self._slug(away.get("name", "")),
                home_name=home.get("name", ""),
                away_name=away.get("name", ""),
                home_score=goals.get("home"),
                away_score=goals.get("away"),
                venue=((fx.get("venue") or {}).get("name") or ""),
                source=self.name,
            ))
        return out

    def attach_lineups(self, matches: list[Match]) -> int:
        """終了済み/進行中の試合に、新しい順でスタメンを付ける。

        1試合1リクエストなので lineup_budget 件までに抑える。
        """
        targets = [m for m in matches if m.status in ("FINISHED", "LIVE") and m.id.startswith("af-")]
        targets.sort(key=lambda m: m.kickoff or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
        filled = 0
        for match in targets[: self.lineup_budget]:
            fixture_id = match.id.split("-", 1)[1]
            try:
                data = self.get("/fixtures/lineups", {"fixture": fixture_id})
            except ProviderError:
                continue
            for block in data.get("response", []):
                team = block.get("team", {})
                slug = self._slug(team.get("name", ""))
                lineup = TeamLineup(
                    club_slug=slug,
                    club_name=team.get("name", ""),
                    formation=block.get("formation", "") or "",
                    coach=((block.get("coach") or {}).get("name") or ""),
                    start=[_slot(p) for p in block.get("startXI", []) or []],
                    bench=[_slot(p) for p in block.get("substitutes", []) or []],
                )
                if slug and slug == match.home_slug:
                    match.home_lineup = lineup
                elif slug and slug == match.away_slug:
                    match.away_lineup = lineup
                elif match.home_lineup is None:
                    match.home_lineup = lineup
                else:
                    match.away_lineup = lineup
            if match.home_lineup or match.away_lineup:
                filled += 1
        return filled


def _slot(entry: dict) -> PlayerSlot:
    p = entry.get("player", {})
    return PlayerSlot(
        name=p.get("name", "") or "",
        number=p.get("number"),
        position=p.get("pos", "") or "",
        grid=p.get("grid", "") or "",
    )


def _matchday(round_name: str) -> int | None:
    """"Regular Season - 3" から節番号を取り出す。"""
    if not round_name:
        return None
    tail = round_name.rsplit("-", 1)[-1].strip()
    return int(tail) if tail.isdigit() else None
