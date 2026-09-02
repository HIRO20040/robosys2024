#!/usr/bin/env python3
"""SerieHub — セリエA/B 情報サイトのビルド。

  python3 build.py                     # 通常ビルド（RSS + API、鍵は環境変数）
  python3 build.py --offline           # サンプルデータでビルド（通信・鍵なし）
  python3 build.py --check-feeds       # 全RSSの死活だけ確認して終了
  python3 build.py --out docs          # 出力先を変更

環境変数:
  DEEPL_API_KEY        DeepL の APIキー（伊→日の翻訳。無くても動く）
  API_FOOTBALL_KEY     API-Football のキー（セリエA/B の結果とスタメン）
  FOOTBALL_DATA_TOKEN  football-data.org のトークン（セリエAのみ）
  MYMEMORY_EMAIL       MyMemory 利用時の連絡先（任意、無料枠が少し増える）

どの外部サービスも必須ではない。取れなかったものは黙って欠落させず、
サイト上の「情報源」ページに理由を出す。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from lib.matching import ClubMatcher                                  # noqa: E402
from lib.models import Article, Club, Match, StandingRow              # noqa: E402
from lib.news import dedupe, entries_to_articles, fetch_source, sort_articles  # noqa: E402
from lib.providers.api_football import ApiFootballProvider            # noqa: E402
from lib.providers.base import LEAGUE_LABELS, SERIE_A, SERIE_B, ProviderError, current_season  # noqa: E402
from lib.providers.football_data import FootballDataProvider          # noqa: E402
from lib.providers.offline import OfflineProvider                     # noqa: E402
from lib.render import SiteRenderer                                   # noqa: E402
from lib.transfer import classify                                     # noqa: E402
from lib.translate import Translator, TranslationCache, build_engine   # noqa: E402

LEAGUES = (SERIE_A, SERIE_B)
SITE_NAME = "SerieHub"


# --------------------------------------------------------------------------
# 設定の読み込み
# --------------------------------------------------------------------------

def load_clubs() -> list[Club]:
    raw = yaml.safe_load((ROOT / "config/clubs.yaml").read_text(encoding="utf-8"))
    return [Club(**entry) for entry in raw["clubs"]]


def load_sources() -> list[dict]:
    raw = yaml.safe_load((ROOT / "config/sources.yaml").read_text(encoding="utf-8"))
    return [s for s in raw["sources"] if s.get("enabled", True)]


def load_league_fallback() -> dict:
    return yaml.safe_load((ROOT / "config/leagues.yaml").read_text(encoding="utf-8"))


# --------------------------------------------------------------------------
# 収集
# --------------------------------------------------------------------------

def collect_news(sources: list[dict], matcher: ClubMatcher, max_age_days: int,
                 verbose: bool = True) -> tuple[list[Article], list]:
    """全フィードを回して記事と死活を集める。1つ落ちても止まらない。"""
    articles: list[Article] = []
    health = []
    for source in sources:
        entries, status = fetch_source(source)
        health.append(status)
        if status.ok:
            got = entries_to_articles(entries, source, matcher, max_age_days)
            articles.extend(got)
            if verbose:
                print(f"  [ok]   {source['id']:<20} {status.entries:>3} entries -> {len(got):>3} 関連記事")
        elif verbose:
            print(f"  [FAIL] {source['id']:<20} {status.error}")
    return articles, health


def collect_offline_news(matcher: ClubMatcher, sources: list[dict]) -> tuple[list[Article], list]:
    """fixtures のサンプル見出しを Article に変換する。"""
    from lib.models import SourceHealth

    path = ROOT / "fixtures/sample_feed.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    by_id = {s["id"]: s for s in sources}
    articles: list[Article] = []
    for i, entry in enumerate(data["entries"]):
        source = by_id.get(entry["source_id"], {
            "id": entry["source_id"], "name": entry["source_id"],
            "tier": entry["tier"], "lang": entry["lang"], "leagues": list(LEAGUES),
        })
        clubs = matcher.find(entry["title"], entry["summary"])
        if not clubs:
            continue
        verdict = classify(entry["title"], entry["summary"], source["tier"])
        leagues = sorted({matcher.clubs[c].league for c in clubs if matcher.clubs[c].league})
        articles.append(Article(
            id=f"sample-{i}", title=entry["title"], url=entry["link"],
            source_id=source["id"], source_name=source.get("name", source["id"]),
            tier=source["tier"], lang=entry["lang"],
            published=datetime.fromisoformat(entry["published"]),
            summary=entry["summary"], clubs=clubs, leagues=leagues,
            transfer_kind=verdict["kind"], transfer_confidence=verdict["confidence"],
            transfer_score=verdict["score"],
        ))
    health = [SourceHealth(source_id="offline", name="サンプルデータ", tier="official",
                           url="fixtures/sample_feed.json", ok=True, entries=len(articles))]
    return articles, health


def build_providers(args, matcher: ClubMatcher) -> list:
    if args.offline:
        return [OfflineProvider(ROOT / "fixtures")]
    providers = []
    af_key = os.environ.get("API_FOOTBALL_KEY", "").strip()
    fd_key = os.environ.get("FOOTBALL_DATA_TOKEN", "").strip()
    # セリエBとスタメンを扱えるのは API-Football だけなので優先する
    if af_key:
        providers.append(ApiFootballProvider(af_key, matcher, lineup_budget=args.lineup_budget))
    if fd_key:
        providers.append(FootballDataProvider(fd_key, matcher))
    return providers


def collect_matches(providers: list, season: int, args) -> tuple[
        dict[str, list[StandingRow]], dict[str, list[Match]], dict[str, str], list[dict]]:
    """リーグごとに、対応する最初のプロバイダからデータを取る。"""
    standings: dict[str, list[StandingRow]] = {}
    matches: dict[str, list[Match]] = {}
    sources_used: dict[str, str] = {}
    status: list[dict] = []

    for provider in providers:
        handled = []
        errors = []
        for league in LEAGUES:
            if not provider.supports(league):
                continue
            # 順位表と日程は別々に埋める。片方だけ埋まっている状態で
            # リーグごと飛ばしてしまうと、もう片方が永久に取れなくなる。
            need_standings = league not in standings
            need_matches = league not in matches
            if not (need_standings or need_matches):
                continue
            try:
                if need_standings:
                    rows = provider.standings(league, season)
                    if rows:
                        standings[league] = rows
                        sources_used[league] = provider.name
                if need_matches:
                    fixtures = provider.matches(league, season, args.days_back, args.days_ahead)
                    if fixtures:
                        matches[league] = fixtures
                        handled.append(LEAGUE_LABELS[league])
            except ProviderError as exc:
                errors.append(f"{LEAGUE_LABELS[league]}: {exc}")
                continue

        filled = 0
        if matches:
            try:
                filled = provider.attach_lineups([m for ms in matches.values() for m in ms])
            except ProviderError as exc:
                errors.append(f"スタメン取得: {exc}")

        detail = f"{'、'.join(handled)} を取得" if handled else "データなし"
        if filled:
            detail += f" / スタメン{filled}試合"
        if errors:
            detail += " / " + "; ".join(errors)[:160]
        status.append({
            "name": provider.name,
            "leagues": "・".join(LEAGUE_LABELS[l] for l in provider.supported_leagues),
            "ok": bool(handled),
            "detail": detail,
        })

    if not providers:
        status.append({
            "name": "（未設定）", "leagues": "セリエA・セリエB", "ok": False,
            "detail": "APIキーが設定されていないため、試合データを取得していません。"
                      "API_FOOTBALL_KEY もしくは FOOTBALL_DATA_TOKEN を設定してください。",
        })
    return standings, matches, sources_used, status


# --------------------------------------------------------------------------
# 加工
# --------------------------------------------------------------------------

def assign_leagues(clubs: list[Club], standings: dict[str, list[StandingRow]],
                   fallback: dict) -> tuple[dict[str, list[Club]], bool]:
    """所属リーグを決める。順位表があればそれが正、無ければ設定のフォールバック。"""
    by_slug = {c.slug: c for c in clubs}
    used_fallback = False
    league_clubs: dict[str, list[Club]] = {}

    for league in LEAGUES:
        rows = standings.get(league) or []
        slugs = [r.club_slug for r in rows if r.club_slug in by_slug]
        if not slugs:
            slugs = [s for s in fallback.get(league, []) if s in by_slug]
            used_fallback = used_fallback or bool(slugs)
        for slug in slugs:
            by_slug[slug].league = league
        league_clubs[league] = [by_slug[s] for s in slugs]
    return league_clubs, used_fallback


def translate_articles(articles: list[Article], translator: Translator) -> None:
    """見出しと要約を言語ごとにまとめて翻訳する（バッチでAPI呼び出しを減らす）。"""
    by_lang: dict[str, list[Article]] = defaultdict(list)
    for article in articles:
        by_lang[article.lang].append(article)

    for lang, group in by_lang.items():
        if lang == "ja":
            continue
        titles = translator.translate_many([a.title for a in group], lang)
        for article, translated in zip(group, titles):
            article.title_ja = translated
        summaries = translator.translate_many([a.summary for a in group], lang)
        for article, translated in zip(group, summaries):
            article.summary_ja = translated


def attach_reasons(articles: list[Article]) -> None:
    """バッジの tooltip に出す判定根拠を組み立てる。"""
    for article in articles:
        verdict = classify(article.title, article.summary, article.tier)
        article.reason_text = "、".join(verdict["reasons"]) or "自動判定"


# --------------------------------------------------------------------------
# 出力
# --------------------------------------------------------------------------

def write_site(args, clubs, league_clubs, articles, standings, matches,
               standings_source, provider_status, health, translator,
               season, used_fallback) -> SiteRenderer:
    by_slug = {c.slug: c for c in clubs}
    transfers = [a for a in articles if a.is_transfer]
    general = [a for a in articles if not a.is_transfer]

    all_matches = [m for ms in matches.values() for m in ms]
    finished = sorted([m for m in all_matches if m.status in ("FINISHED", "LIVE")],
                      key=lambda m: m.kickoff or datetime.min.replace(tzinfo=timezone.utc),
                      reverse=True)
    upcoming = sorted([m for m in all_matches if m.status in ("SCHEDULED", "POSTPONED")],
                      key=lambda m: m.kickoff or datetime.max.replace(tzinfo=timezone.utc))

    context = {
        "site_name": SITE_NAME,
        "built_at": datetime.now(timezone.utc),
        "season": season,
        "demo_mode": args.offline,
        "translation_engine": translator.engine_name,
        "clubs": by_slug,
        "league_clubs": league_clubs,
        "standings": standings,
        "standings_source": standings_source,
        "used_fallback": used_fallback,
        "page": "",
    }

    renderer = SiteRenderer(ROOT / "templates", ROOT / "static", Path(args.out), context)
    renderer.copy_static()

    renderer.render("index.html", "index.html", page="home",
                    transfers=transfers, general_news=general,
                    recent_matches=finished or upcoming)

    for league, filename in ((SERIE_A, "serie-a.html"), (SERIE_B, "serie-b.html")):
        renderer.render(
            "league.html", filename, page=filename.replace(".html", ""), league=league,
            matches=[m for m in finished + upcoming if m.league == league],
            articles=[a for a in articles if league in a.leagues],
        )

    renderer.render("transfers.html", "transfers.html", page="transfers",
                    transfers_by_league={
                        league: [a for a in transfers if league in a.leagues]
                        for league in LEAGUES
                    })

    renderer.render("matches.html", "matches.html", page="matches",
                    any_matches=bool(all_matches),
                    finished_by_league={l: [m for m in finished if m.league == l] for l in LEAGUES},
                    upcoming_by_league={l: [m for m in upcoming if m.league == l] for l in LEAGUES})

    health_by_tier: dict[str, list] = defaultdict(list)
    for row in health:
        health_by_tier[row.tier].append(row)
    renderer.render("sources.html", "sources.html", page="sources",
                    health_by_tier=dict(health_by_tier), provider_status=provider_status)

    standing_by_slug = {r.club_slug: r for rows in standings.values() for r in rows}
    for league in LEAGUES:
        for club in league_clubs.get(league, []):
            club_articles = [a for a in articles if club.slug in a.clubs]
            renderer.render(
                "team.html", f"team/{club.slug}.html", page="team", club=club,
                standing=standing_by_slug.get(club.slug),
                transfers=[a for a in club_articles if a.is_transfer][:20],
                news=[a for a in club_articles if not a.is_transfer][:20],
                matches=[m for m in finished + upcoming
                         if club.slug in (m.home_slug, m.away_slug)][:8],
            )
    return renderer


def dump_data(out_dir: Path, articles, standings, matches, health) -> None:
    """生成に使ったデータを JSON でも残す（差分確認と再利用のため）。"""
    data_dir = out_dir / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "articles": [a.to_dict() for a in articles],
        "standings": {k: [r.to_dict() for r in v] for k, v in standings.items()},
        "matches": {k: [m.to_dict() for m in v] for k, v in matches.items()},
        "sources": [h.to_dict() for h in health],
    }
    (data_dir / "site.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")


# --------------------------------------------------------------------------

def check_feeds(sources: list[dict]) -> int:
    print("RSS フィードの死活確認\n")
    bad = 0
    for source in sources:
        _, status = fetch_source(source)
        mark = "ok  " if status.ok else "FAIL"
        print(f"[{mark}] {source['id']:<22} {status.entries:>4} entries  {source['url']}")
        if not status.ok:
            print(f"         └ {status.error}")
            bad += 1
    print(f"\n{len(sources) - bad}/{len(sources)} 本が応答しました。")
    return 1 if bad else 0


def parse_args(argv=None):
    p = argparse.ArgumentParser(description="セリエA/B 情報サイトをビルドする")
    p.add_argument("--out", default=str(ROOT / "site"), help="出力ディレクトリ")
    p.add_argument("--offline", action="store_true",
                   help="通信もAPIキーも使わず、fixtures のサンプルデータでビルドする")
    p.add_argument("--check-feeds", action="store_true", help="RSSの死活だけ確認して終了")
    p.add_argument("--no-news", action="store_true", help="RSS収集を飛ばす")
    p.add_argument("--translate", default="auto", choices=["auto", "deepl", "mymemory", "none"],
                   help="翻訳エンジン（既定: auto = DeepLキーがあればDeepL、無ければMyMemory）")
    p.add_argument("--translate-limit", type=int, default=400,
                   help="1回のビルドで新規に翻訳する最大件数（0で無制限）")
    p.add_argument("--season", type=int, default=None, help="シーズン開始年（既定は自動判定）")
    p.add_argument("--days-back", type=int, default=14, help="何日前までの試合を取るか")
    p.add_argument("--days-ahead", type=int, default=14, help="何日先までの日程を取るか")
    p.add_argument("--max-age-days", type=int, default=21, help="記事の鮮度上限")
    p.add_argument("--max-articles", type=int, default=600, help="保持する記事数の上限")
    p.add_argument("--lineup-budget", type=int, default=20,
                   help="スタメンを取りに行く試合数の上限（APIの回数制限対策）")
    return p.parse_args(argv)


def main(argv=None) -> int:
    args = parse_args(argv)
    # オフラインは通信しない前提なので、明示指定が無ければ翻訳も行わない
    if args.offline and args.translate == "auto":
        args.translate = "none"
    sources = load_sources()

    if args.check_feeds:
        return check_feeds(sources)

    clubs = load_clubs()
    matcher = ClubMatcher(clubs)
    season = args.season or current_season()
    fallback = load_league_fallback()

    print(f"■ シーズン {season}-{(season + 1) % 100}"
          f"{'（サンプルデータ）' if args.offline else ''}")

    # 1. 試合データ（順位表 → 所属リーグの決定に使う）
    print("■ 試合データ")
    providers = build_providers(args, matcher)
    standings, matches, standings_source, provider_status = collect_matches(providers, season, args)
    for row in provider_status:
        print(f"  [{'ok' if row['ok'] else '--'}] {row['name']}: {row['detail']}")

    league_clubs, used_fallback = assign_leagues(clubs, standings, fallback)
    if used_fallback:
        print(f"  ! 順位表が無いため config/leagues.yaml の構成"
              f"（{fallback.get('fallback_season')}-{(fallback.get('fallback_season', 0) + 1) % 100}）を使用")
    print(f"  クラブ: セリエA {len(league_clubs.get(SERIE_A, []))} / "
          f"セリエB {len(league_clubs.get(SERIE_B, []))}")

    # 2. ニュース
    articles: list[Article] = []
    health = []
    if args.no_news:
        print("■ ニュース: 収集を飛ばしました")
    elif args.offline:
        print("■ ニュース（サンプル）")
        articles, health = collect_offline_news(matcher, sources)
        print(f"  {len(articles)} 件")
    else:
        print(f"■ ニュース（{len(sources)} フィード）")
        articles, health = collect_news(sources, matcher, args.max_age_days)

    before = len(articles)
    articles = sort_articles(dedupe(articles))[: args.max_articles]
    print(f"  重複排除: {before} → {len(articles)} 件")

    # 3. 翻訳
    cache = TranslationCache(ROOT / "data/translation_cache.json")
    translator = Translator(build_engine(args.translate), cache,
                            limit=args.translate_limit)
    print(f"■ 翻訳エンジン: {translator.engine_name}")
    if articles:
        translate_articles(articles, translator)
        cache.save()
        print(f"  新規 {translator.translated} 件 / キャッシュ命中 {cache.hits} 件"
              f"{f' / 失敗 {translator.errors} 回' if translator.errors else ''}")
    attach_reasons(articles)

    # 4. 出力
    renderer = write_site(args, clubs, league_clubs, articles, standings, matches,
                          standings_source, provider_status, health, translator,
                          season, used_fallback)
    dump_data(Path(args.out), articles, standings, matches, health)

    transfers = sum(1 for a in articles if a.is_transfer)
    confirmed = sum(1 for a in articles if a.transfer_confidence == "confirmed")
    print(f"■ 出力: {len(renderer.written)} ページ -> {args.out}")
    print(f"  記事 {len(articles)} 件（うち移籍 {transfers} 件 / 確定 {confirmed} 件）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
