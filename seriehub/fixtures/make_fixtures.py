"""検証用サンプルデータの生成スクリプト（決定論的）。

生成物はすべて架空。実在の試合結果・選手ではない。
    python3 fixtures/make_fixtures.py
"""

from __future__ import annotations

import json
import random
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import yaml  # noqa: E402

SERIE_A = ["atalanta", "bologna", "cagliari", "como", "cremonese", "fiorentina", "genoa",
           "hellas-verona", "inter", "juventus", "lazio", "lecce", "milan", "napoli",
           "parma", "pisa", "roma", "sassuolo", "torino", "udinese"]
SERIE_B = ["avellino", "bari", "carrarese", "catanzaro", "cesena", "empoli", "entella",
           "frosinone", "juve-stabia", "mantova", "modena", "monza", "padova", "palermo",
           "pescara", "reggiana", "sampdoria", "spezia", "sudtirol", "venezia"]

# 架空の選手名（実在選手ではない）
SURNAMES = ["Rossi", "Bianchi", "Ferrari", "Esposito", "Romano", "Colombo", "Ricci",
            "Marino", "Greco", "Bruno", "Gallo", "Conti", "De Luca", "Costa", "Giordano",
            "Mancini", "Rizzo", "Lombardi", "Moretti", "Barbieri", "Fontana", "Santoro",
            "Mariani", "Rinaldi", "Caruso", "Ferrara", "Galli", "Martini", "Leone"]
POSITIONS = ["G", "D", "D", "D", "D", "M", "M", "M", "F", "F", "F"]


def squad(rng: random.Random, seed_name: str) -> tuple[list[dict], list[dict]]:
    names = rng.sample(SURNAMES, 18)
    start = [{"name": names[i], "number": i + 1, "position": POSITIONS[i], "grid": ""}
             for i in range(11)]
    bench = [{"name": names[i], "number": i + 1, "position": rng.choice("GDMF"), "grid": ""}
             for i in range(11, 18)]
    return start, bench


def main() -> None:
    rng = random.Random(20260902)
    raw = (ROOT / "config/clubs.yaml").read_text(encoding="utf-8")
    clubs = {c["slug"]: c for c in yaml.safe_load(raw)["clubs"]}
    now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)

    standings: dict[str, list[dict]] = {}
    matches: dict[str, list[dict]] = {}

    for league, slugs in (("SA", SERIE_A), ("SB", SERIE_B)):
        order = list(slugs)
        rng.shuffle(order)
        records = []
        for slug in order:
            played = 4
            won = rng.randint(0, played)
            lost = rng.randint(0, played - won)
            drawn = played - won - lost
            records.append({
                "club_slug": slug, "club_name": clubs[slug]["short_it"],
                "played": played, "won": won, "drawn": drawn, "lost": lost,
                "goals_for": won * 2 + drawn, "goals_against": lost * 2 + drawn,
                "points": won * 3 + drawn,
            })
        # 勝点 → 得失点差 → 得点 の順に並べて順位を振る（本物と同じ整列）
        records.sort(key=lambda r: (-r["points"],
                                    -(r["goals_for"] - r["goals_against"]),
                                    -r["goals_for"]))
        for pos, rec in enumerate(records, start=1):
            rec["position"] = pos
        standings[league] = records

        fixtures = []
        pairs = list(zip(order[0::2], order[1::2]))
        for idx, (home, away) in enumerate(pairs):
            finished = idx < len(pairs) - 2      # 最後の2試合は未消化にする
            kickoff = now - timedelta(days=3) + timedelta(hours=idx * 3) if finished \
                else now + timedelta(days=4, hours=idx * 3)
            m = {
                "id": f"sample-{league}-{idx}",
                "league": league,
                "matchday": 4 if finished else 5,
                "kickoff": kickoff.isoformat(),
                "status": "FINISHED" if finished else "SCHEDULED",
                "home_slug": home, "away_slug": away,
                "home_name": clubs[home]["short_it"], "away_name": clubs[away]["short_it"],
                "home_score": rng.randint(0, 3) if finished else None,
                "away_score": rng.randint(0, 2) if finished else None,
                "venue": clubs[home].get("stadium", ""),
                "source": "サンプルデータ（架空）",
                "home_lineup": None, "away_lineup": None,
            }
            if finished:
                for side, slug in (("home", home), ("away", away)):
                    start, bench = squad(rng, slug)
                    m[f"{side}_lineup"] = {
                        "club_slug": slug, "club_name": clubs[slug]["short_it"],
                        "formation": rng.choice(["4-3-3", "3-5-2", "4-2-3-1", "3-4-2-1"]),
                        "coach": rng.choice(SURNAMES),
                        "start": start, "bench": bench,
                    }
            fixtures.append(m)
        matches[league] = fixtures

    out = Path(__file__).resolve().parent
    (out / "sample_standings.json").write_text(
        json.dumps(standings, ensure_ascii=False, indent=1), encoding="utf-8")
    (out / "sample_matches.json").write_text(
        json.dumps(matches, ensure_ascii=False, indent=1), encoding="utf-8")

    # 架空のニュース（RSS エントリ相当）
    headlines = [
        ("UFFICIALE: il centrocampista firma con l'Inter fino al 2030", "official", "legaseriea", "it"),
        ("Milan, visite mediche fissate per il difensore", "primary", "gazzetta", "it"),
        ("Napoli, accordo vicino per il rinnovo del portiere", "primary", "corrieredellosport", "it"),
        ("Juventus, sondaggio per l'attaccante del Bologna", "aggregator", "tuttomercatoweb", "it"),
        ("Roma-Lazio, le formazioni ufficiali del derby", "primary", "gazzetta", "it"),
        ("Palermo, colpo chiuso in difesa: comunicato ufficiale del club", "aggregator", "tuttob", "it"),
        ("Sampdoria, secondo quanto riportato sarebbe vicino l'accordo col tecnico", "primary", "tuttosport", "it"),
        ("Venezia, addio all'esterno: risoluzione consensuale", "aggregator", "calciomercato", "it"),
        ("インテルとナポリの上位対決、注目の一戦", "translated", "soccerking", "ja"),
        ("Atalanta target Serie B striker, say reports", "aggregator", "football-italia", "en"),
        ("Frosinone, trattativa avanzata per il centrocampista del Modena", "aggregator", "tuttob", "it"),
        ("Cremonese, il club annuncia il rinnovo del capitano", "official", "legaseriea", "it"),
    ]
    entries = []
    for i, (title, tier, source_id, lang) in enumerate(headlines):
        entries.append({
            "title": title,
            "link": f"https://example.invalid/sample/{i}",
            "summary": "これは動作確認用の架空の記事です。実在の報道ではありません。",
            "published": (now - timedelta(hours=i * 5)).isoformat(),
            "source_id": source_id, "tier": tier, "lang": lang,
        })
    (out / "sample_feed.json").write_text(
        json.dumps({"entries": entries}, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"standings: SA={len(standings['SA'])} SB={len(standings['SB'])}")
    print(f"matches:   SA={len(matches['SA'])} SB={len(matches['SB'])}")
    print(f"feed:      {len(entries)} entries")


if __name__ == "__main__":
    main()
