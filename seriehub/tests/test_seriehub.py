"""SerieHub のテスト。外部通信を一切行わない。

    cd seriehub && python3 -m unittest discover -s tests -v
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import yaml  # noqa: E402

from lib.matching import ClubMatcher, normalize  # noqa: E402
from lib.models import Article, Club, Match, PlayerSlot, StandingRow, TeamLineup  # noqa: E402
from lib.news import _clean, _dedupe_key, dedupe, entries_to_articles, sort_articles  # noqa: E402
from lib.providers.api_football import _matchday  # noqa: E402
from lib.providers.base import current_season  # noqa: E402
from lib.render import zone_class  # noqa: E402
from lib.transfer import classify  # noqa: E402
from lib.translate import DeepLEngine, NullEngine, TranslationCache, Translator  # noqa: E402


def load_clubs() -> list[Club]:
    raw = yaml.safe_load((ROOT / "config/clubs.yaml").read_text(encoding="utf-8"))
    return [Club(**c) for c in raw["clubs"]]


class TestConfig(unittest.TestCase):
    def test_clubs_yaml_is_well_formed(self):
        clubs = load_clubs()
        self.assertGreaterEqual(len(clubs), 40)
        slugs = [c.slug for c in clubs]
        self.assertEqual(len(slugs), len(set(slugs)), "slug が重複している")
        for club in clubs:
            self.assertTrue(club.name_ja, f"{club.slug} に日本語名が無い")
            self.assertTrue(club.colors[0].startswith("#"), f"{club.slug} の色が不正")

    def test_sources_have_valid_tiers(self):
        raw = yaml.safe_load((ROOT / "config/sources.yaml").read_text(encoding="utf-8"))
        valid = {"official", "primary", "aggregator", "translated"}
        ids = set()
        for source in raw["sources"]:
            self.assertIn(source["tier"], valid, source["id"])
            self.assertTrue(source["url"].startswith("http"), source["id"])
            self.assertNotIn(source["id"], ids, "source id が重複している")
            ids.add(source["id"])

    def test_league_fallback_matches_club_dictionary(self):
        fallback = yaml.safe_load((ROOT / "config/leagues.yaml").read_text(encoding="utf-8"))
        known = {c.slug for c in load_clubs()}
        for league in ("SA", "SB"):
            slugs = fallback[league]
            self.assertEqual(len(slugs), 20, f"{league} は20クラブであるべき")
            self.assertEqual(len(slugs), len(set(slugs)))
            missing = set(slugs) - known
            self.assertFalse(missing, f"clubs.yaml に無いクラブ: {missing}")
        overlap = set(fallback["SA"]) & set(fallback["SB"])
        self.assertFalse(overlap, f"AとBに重複所属: {overlap}")


class TestMatching(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.matcher = ClubMatcher(load_clubs())

    def test_normalize_strips_accents(self):
        self.assertEqual(normalize("Südtirol"), "sudtirol")

    def test_finds_club_in_headline(self):
        self.assertEqual(self.matcher.find("Inter, accordo per il rinnovo", "mercato"), ["inter"])

    def test_handles_italian_elision(self):
        # "l'Inter" / "dell'Inter" はイタリア語の記事で最も普通の書かれ方
        self.assertIn("inter", self.matcher.find("Il derby dell'Inter", "calcio"))
        self.assertIn("inter", self.matcher.find("Nuovo attaccante per l'Inter", ""))

    def test_does_not_match_inside_words(self):
        # "interesse" が Inter に、"Milano" が Milan に誤爆しないこと
        self.assertEqual(self.matcher.find("Grande interesse per il centrocampista", ""), [])
        self.assertEqual(self.matcher.find("Milano si sveglia sotto la pioggia", "meteo"), [])

    def test_ambiguous_city_names_need_football_context(self):
        self.assertEqual(self.matcher.find("Torino, traffico in centro", "cronaca"), [])
        self.assertIn("torino", self.matcher.find("Torino, il mister cambia modulo", "calcio"))

    def test_longer_alias_wins(self):
        self.assertEqual(self.matcher.find("Juve Stabia, colpo in attacco", "Le Vespe"), ["juve-stabia"])

    def test_matches_japanese_names(self):
        self.assertEqual(sorted(self.matcher.find("インテルがナポリに勝利", "セリエA")),
                         ["inter", "napoli"])

    def test_resolves_api_team_names(self):
        for api_name, expected in [
            ("Hellas Verona FC", "hellas-verona"),
            ("FC Internazionale Milano", "inter"),
            ("US Sassuolo Calcio", "sassuolo"),
            ("Virtus Entella", "entella"),
            ("FC Südtirol", "sudtirol"),
        ]:
            self.assertEqual(self.matcher.resolve(api_name), expected, api_name)

    def test_resolve_returns_none_for_unknown(self):
        self.assertIsNone(self.matcher.resolve("Real Madrid CF"))


class TestTransferClassification(unittest.TestCase):
    def test_official_announcement_is_confirmed(self):
        r = classify("UFFICIALE: il difensore e un nuovo giocatore", "", "official")
        self.assertEqual((r["kind"], r["confidence"]), ("signing", "confirmed"))

    def test_primary_medical_is_strong(self):
        r = classify("Milan, visite mediche per l'attaccante", "", "primary")
        self.assertEqual((r["kind"], r["confidence"]), ("medical", "strong"))

    def test_aggregator_interest_is_rumour(self):
        r = classify("Napoli, piace il centrocampista", "Solo un sondaggio", "aggregator")
        self.assertEqual(r["confidence"], "rumour")

    def test_hedged_language_downgrades(self):
        r = classify("Juventus, sarebbe vicino l'accordo", "", "primary")
        self.assertEqual(r["confidence"], "rumour")
        self.assertTrue(any("引き下げ" in reason for reason in r["reasons"]))

    def test_official_marker_promotes_aggregator(self):
        r = classify("Lecce, firma fino al 2029", "comunicato ufficiale del club", "aggregator")
        self.assertEqual(r["confidence"], "confirmed")

    def test_match_report_is_not_a_transfer(self):
        self.assertEqual(classify("Serie A, l'Inter vince 2-0", "cronaca", "primary")["kind"], "")

    def test_generic_japanese_words_do_not_trigger(self):
        # 「報道」だけで噂扱いにしない（日本語記事のほぼ全てに出る語）
        self.assertEqual(classify("インテル対ナポリ、注目の一戦", "各社の報道より", "translated")["kind"], "")

    def test_reasons_are_always_present(self):
        r = classify("Roma, accordo per il rinnovo", "", "primary")
        self.assertTrue(r["reasons"])


class TestNews(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        clubs = load_clubs()
        for club in clubs:
            club.league = "SA" if club.slug in ("inter", "milan", "napoli") else "SB"
        cls.clubs = clubs
        cls.matcher = ClubMatcher(clubs)
        cls.source = {"id": "gz", "name": "Gazzetta", "tier": "primary",
                      "lang": "it", "leagues": ["SA"]}

    def test_clean_strips_html_and_entities(self):
        self.assertEqual(_clean("<p>Ciao &amp; buonasera</p>"), "Ciao & buonasera")

    def test_clean_truncates_long_text(self):
        self.assertLessEqual(len(_clean("parola " * 200, limit=50)), 52)

    def test_only_keeps_articles_mentioning_clubs(self):
        now = datetime.now(timezone.utc)
        entries = [
            {"title": "UFFICIALE: nuovo attaccante per l'Inter", "link": "https://x/1",
             "summary": "annuncio", "published_parsed": now.timetuple()[:9]},
            {"title": "Elezioni comunali", "link": "https://x/2",
             "summary": "politica", "published_parsed": now.timetuple()[:9]},
        ]
        got = entries_to_articles(entries, self.source, self.matcher)
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0].leagues, ["SA"])

    def test_drops_stale_articles(self):
        old = datetime.now(timezone.utc) - timedelta(days=60)
        entries = [{"title": "Il Napoli vince", "link": "https://x/3", "summary": "calcio",
                    "published_parsed": old.timetuple()[:9]}]
        self.assertEqual(entries_to_articles(entries, self.source, self.matcher, max_age_days=30), [])

    def test_entry_without_link_is_skipped(self):
        entries = [{"title": "Inter, mercato", "link": "", "summary": ""}]
        self.assertEqual(entries_to_articles(entries, self.source, self.matcher), [])

    def test_dedupe_prefers_more_primary_source(self):
        now = datetime.now(timezone.utc)
        a = Article(id="1", title="Inter, accordo per il rinnovo di Barella", url="u1",
                    source_id="tmw", source_name="TMW", tier="aggregator", lang="it", published=now)
        b = Article(id="2", title="Inter: accordo per il rinnovo di Barella!", url="u2",
                    source_id="lega", source_name="Lega", tier="official", lang="it", published=now)
        out = dedupe([a, b])
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0].tier, "official")

    def test_dedupe_keeps_distinct_news(self):
        now = datetime.now(timezone.utc)
        a = Article(id="1", title="Inter, ufficiale il rinnovo del capitano", url="u1",
                    source_id="s", source_name="S", tier="primary", lang="it", published=now)
        b = Article(id="2", title="Milan, visite mediche per il portiere brasiliano", url="u2",
                    source_id="s", source_name="S", tier="primary", lang="it", published=now)
        self.assertEqual(len(dedupe([a, b])), 2)

    def test_sort_puts_newest_first_and_undated_last(self):
        now = datetime.now(timezone.utc)
        mk = lambda i, dt: Article(id=str(i), title=f"t{i}", url=f"u{i}", source_id="s",
                                   source_name="S", tier="primary", lang="it", published=dt)
        out = sort_articles([mk(1, now - timedelta(days=1)), mk(2, None), mk(3, now)])
        self.assertEqual([a.id for a in out], ["3", "1", "2"])


class TestModels(unittest.TestCase):
    def test_article_roundtrip(self):
        a = Article(id="1", title="t", url="u", source_id="s", source_name="S",
                    tier="primary", lang="it", published=datetime(2026, 9, 1, tzinfo=timezone.utc))
        self.assertEqual(Article.from_dict(json.loads(json.dumps(a.to_dict()))).published, a.published)

    def test_match_roundtrip_with_lineups(self):
        m = Match(id="m", league="SA", matchday=1, kickoff=datetime.now(timezone.utc),
                  status="FINISHED", home_slug="inter", away_slug="milan",
                  home_name="Inter", away_name="Milan", home_score=2, away_score=1,
                  home_lineup=TeamLineup("inter", "Inter", formation="3-5-2",
                                         start=[PlayerSlot("Rossi", 1, "G")]))
        back = Match.from_dict(json.loads(json.dumps(m.to_dict())))
        self.assertEqual(back.score_text, "2 - 1")
        self.assertTrue(back.has_lineups)
        self.assertEqual(back.home_lineup.start[0].name, "Rossi")

    def test_score_text_for_unplayed_match(self):
        m = Match(id="m", league="SB", matchday=None, kickoff=None, status="SCHEDULED",
                  home_slug="bari", away_slug="modena", home_name="Bari", away_name="Modena")
        self.assertEqual(m.score_text, "-")

    def test_goal_difference(self):
        self.assertEqual(StandingRow(1, "inter", "Inter", goals_for=10, goals_against=3).goal_diff, 7)


class TestTranslation(unittest.TestCase):
    def setUp(self):
        self.cache_path = Path(tempfile.mkdtemp()) / "cache.json"

    def test_no_engine_leaves_translation_empty(self):
        t = Translator(NullEngine(), TranslationCache(self.cache_path))
        self.assertEqual(t.translate_many(["Inter, accordo fatto"], "it"), [""])

    def test_cache_prevents_repeat_calls(self):
        calls = []

        class Fake:
            name, available = "fake", True

            def translate(self, texts, src, dest):
                calls.append(len(texts))
                return [f"[{x}]" for x in texts]

        cache = TranslationCache(self.cache_path)
        self.assertEqual(Translator(Fake(), cache).translate_many(["a", "b"], "it"), ["[a]", "[b]"])
        cache.save()
        reloaded = TranslationCache(self.cache_path)
        self.assertEqual(Translator(Fake(), reloaded).translate_many(["a", "b"], "it"), ["[a]", "[b]"])
        self.assertEqual(len(calls), 1, "キャッシュが効かず再度APIを呼んでいる")

    def test_same_language_passes_through(self):
        t = Translator(NullEngine(), TranslationCache(self.cache_path), dest="ja")
        self.assertEqual(t.translate_many(["日本語の見出し"], "ja"), ["日本語の見出し"])

    def test_engine_failure_does_not_raise(self):
        class Boom:
            name, available = "boom", True

            def translate(self, *args):
                raise RuntimeError("429 Too Many Requests")

        t = Translator(Boom(), TranslationCache(self.cache_path))
        self.assertEqual(t.translate_many(["x"], "it"), [""])
        self.assertEqual(t.errors, 1)

    def test_limit_caps_new_translations(self):
        class Fake:
            name, available = "fake", True

            def translate(self, texts, src, dest):
                return [f"[{x}]" for x in texts]

        t = Translator(Fake(), TranslationCache(self.cache_path), limit=2)
        out = t.translate_many(["a", "b", "c", "d"], "it")
        self.assertEqual(t.translated, 2)
        self.assertEqual(out[2:], ["", ""])

    def test_deepl_endpoint_selection(self):
        self.assertIn("api-free", DeepLEngine("key:fx").endpoint)
        self.assertNotIn("api-free", DeepLEngine("key").endpoint)


class TestProviderHelpers(unittest.TestCase):
    def test_season_starts_in_july(self):
        from datetime import date
        self.assertEqual(current_season(date(2026, 9, 2)), 2026)
        self.assertEqual(current_season(date(2026, 5, 2)), 2025)
        self.assertEqual(current_season(date(2026, 7, 1)), 2026)

    def test_matchday_parsing(self):
        self.assertEqual(_matchday("Regular Season - 3"), 3)
        self.assertIsNone(_matchday("Final"))
        self.assertIsNone(_matchday(""))

    def test_zone_classes(self):
        self.assertEqual(zone_class("SA", 1, 20), "zone-ucl")
        self.assertEqual(zone_class("SA", 19, 20), "zone-releg")
        self.assertEqual(zone_class("SA", 10, 20), "")
        self.assertEqual(zone_class("SB", 2, 20), "zone-promo")
        self.assertEqual(zone_class("SB", 5, 20), "zone-playoff")


class TestOfflineBuild(unittest.TestCase):
    """--offline ビルドが最後まで通り、期待するページを出すこと。"""

    @classmethod
    def setUpClass(cls):
        import build
        cls.out = Path(tempfile.mkdtemp()) / "site"
        cls.rc = build.main(["--offline", "--out", str(cls.out)])

    def test_build_succeeds(self):
        self.assertEqual(self.rc, 0)

    def test_core_pages_exist(self):
        for name in ("index.html", "serie-a.html", "serie-b.html",
                     "transfers.html", "matches.html", "sources.html"):
            self.assertTrue((self.out / name).exists(), name)

    def test_a_team_page_per_club(self):
        self.assertEqual(len(list((self.out / "team").glob("*.html"))), 40)

    def test_static_assets_copied(self):
        self.assertTrue((self.out / "static/style.css").exists())
        self.assertTrue((self.out / "static/app.js").exists())
        self.assertTrue((self.out / ".nojekyll").exists())

    def test_demo_banner_present_in_offline_mode(self):
        self.assertIn("サンプルデータ表示中", (self.out / "index.html").read_text(encoding="utf-8"))

    def test_every_headline_links_to_its_source(self):
        html = (self.out / "transfers.html").read_text(encoding="utf-8")
        self.assertIn('rel="noopener nofollow"', html)

    def test_relative_paths_are_correct_at_depth(self):
        html = (self.out / "team/inter.html").read_text(encoding="utf-8")
        self.assertIn('href="../static/style.css"', html)

    def test_data_dump_is_valid_json(self):
        payload = json.loads((self.out / "data/site.json").read_text(encoding="utf-8"))
        self.assertIn("articles", payload)
        self.assertIn("SA", payload["standings"])

    def test_no_unrendered_template_syntax(self):
        for page in self.out.rglob("*.html"):
            text = page.read_text(encoding="utf-8")
            self.assertNotIn("{{", text, f"{page.name} にテンプレート構文が残っている")
            self.assertNotIn("{%", text, f"{page.name} にテンプレート構文が残っている")


if __name__ == "__main__":
    unittest.main()
