"""試合データプロバイダの共通インターフェース。

プロバイダごとに対応リーグと取得できる項目が違う:

  football-data.org : セリエAのみ（無料プラン）。順位表と結果。スタメンは無し。
  API-Football      : セリエA/B 両方。スタメン・ベンチまで取れる。
  offline           : fixtures/ の JSON を読む。鍵も通信も無い環境での検証用。

build 側はリーグごとに「対応していて設定済みの最初のプロバイダ」を選ぶ。
"""

from __future__ import annotations

import time
from datetime import date, datetime, timezone

import requests

from ..models import Match, StandingRow

SERIE_A = "SA"
SERIE_B = "SB"
LEAGUE_LABELS = {SERIE_A: "セリエA", SERIE_B: "セリエB"}


def current_season(today: date | None = None) -> int:
    """シーズン表記（開始年）を返す。2026-27シーズンなら 2026。

    ヨーロッパのシーズンは夏に始まるので、7月以降はその年、6月以前は前年。
    """
    today = today or datetime.now(timezone.utc).date()
    return today.year if today.month >= 7 else today.year - 1


class ProviderError(RuntimeError):
    pass


class Provider:
    name = "base"
    supported_leagues: tuple[str, ...] = ()

    @property
    def configured(self) -> bool:
        return False

    def supports(self, league: str) -> bool:
        return league in self.supported_leagues

    def standings(self, league: str, season: int) -> list[StandingRow]:
        raise NotImplementedError

    def matches(self, league: str, season: int, days_back: int, days_ahead: int) -> list[Match]:
        raise NotImplementedError

    def attach_lineups(self, matches: list[Match]) -> int:
        """スタメン/ベンチを埋められるだけ埋め、埋めた試合数を返す。"""
        return 0


class HttpProvider(Provider):
    """レート制限と一時障害に耐える HTTP 呼び出しを共通化する。"""

    base_url = ""
    timeout = 25

    def __init__(self, api_key: str = "", request_pause: float = 0.3):
        self.api_key = api_key
        self.request_pause = request_pause
        self.calls = 0

    def headers(self) -> dict[str, str]:
        return {}

    def get(self, path: str, params: dict | None = None, retries: int = 3) -> dict:
        url = f"{self.base_url}{path}"
        last: Exception | None = None
        for attempt in range(retries):
            try:
                resp = requests.get(url, headers=self.headers(), params=params, timeout=self.timeout)
                self.calls += 1
                if resp.status_code == 429:
                    # レート制限。指数バックオフで待つ
                    time.sleep(2 ** attempt * 3)
                    last = ProviderError("429 rate limited")
                    continue
                resp.raise_for_status()
                time.sleep(self.request_pause)
                return resp.json()
            except (requests.RequestException, ValueError) as exc:
                last = exc
                time.sleep(2 ** attempt)
        raise ProviderError(f"{self.name}: GET {path} failed: {last}")
