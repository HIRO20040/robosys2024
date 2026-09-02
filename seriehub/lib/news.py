"""RSS の収集・正規化・重複排除。

方針:
  * 記事本文は保存しない。見出しと短い要約、原文URLだけを持つ（著作権配慮）。
  * どれか1つのフィードが落ちてもビルドは続行し、死活を SourceHealth に残す。
  * 同じニュースが複数媒体から来た場合、より一次に近い媒体の版を残す。
"""

from __future__ import annotations

import hashlib
import html
import re
from datetime import datetime, timezone, timedelta

import feedparser
import requests

from .matching import ClubMatcher, normalize
from .models import Article, SourceHealth
from .transfer import classify

USER_AGENT = (
    "SerieHub/1.0 (+https://github.com/HIRO20040/robosys2024; "
    "RSS aggregator for personal/educational use)"
)

_TIER_RANK = {"official": 0, "primary": 1, "aggregator": 2, "translated": 3}
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def _clean(text: str, limit: int = 300) -> str:
    """RSS の description から HTML を落として要約に使える形にする。"""
    if not text:
        return ""
    text = _TAG_RE.sub(" ", text)
    text = html.unescape(text)
    text = _WS_RE.sub(" ", text).strip()
    if len(text) > limit:
        text = text[:limit].rsplit(" ", 1)[0] + "…"
    return text


def _entry_time(entry) -> datetime | None:
    for key in ("published_parsed", "updated_parsed"):
        parsed = entry.get(key)
        if parsed:
            try:
                return datetime(*parsed[:6], tzinfo=timezone.utc)
            except (TypeError, ValueError):
                continue
    return None


def fetch_source(source: dict, timeout: int = 20) -> tuple[list, SourceHealth]:
    """1つのフィードを取得してエントリ列と死活を返す。例外は投げない。"""
    health = SourceHealth(
        source_id=source["id"], name=source.get("name", source["id"]),
        tier=source["tier"], url=source["url"], ok=False,
    )
    try:
        resp = requests.get(
            source["url"],
            headers={"User-Agent": USER_AGENT, "Accept": "application/rss+xml, application/xml, text/xml, */*"},
            timeout=timeout,
        )
        resp.raise_for_status()
    except requests.RequestException as exc:
        health.error = f"{type(exc).__name__}: {exc}"[:200]
        return [], health

    parsed = feedparser.parse(resp.content)
    if parsed.bozo and not parsed.entries:
        health.error = f"parse error: {parsed.bozo_exception}"[:200]
        return [], health

    health.ok = True
    health.entries = len(parsed.entries)
    return parsed.entries, health


def entries_to_articles(entries, source: dict, matcher: ClubMatcher,
                        max_age_days: int = 30) -> list[Article]:
    """フィードのエントリを Article に変換し、クラブと移籍種別を付与する。"""
    cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
    articles: list[Article] = []

    for entry in entries:
        title = _clean(entry.get("title", ""), limit=200)
        link = entry.get("link", "")
        if not title or not link:
            continue

        published = _entry_time(entry)
        if published and published < cutoff:
            continue

        summary = _clean(entry.get("summary", "") or entry.get("description", ""))
        clubs = matcher.find(title, summary)
        if not clubs:
            continue    # セリエA/Bのクラブに触れていない記事は載せない

        verdict = classify(title, summary, source["tier"])
        leagues = sorted({matcher.clubs[c].league for c in clubs if matcher.clubs[c].league})

        articles.append(Article(
            id=hashlib.sha1(link.encode("utf-8")).hexdigest()[:16],
            title=title,
            url=link,
            source_id=source["id"],
            source_name=source.get("name", source["id"]),
            tier=source["tier"],
            lang=source.get("lang", "it"),
            published=published,
            summary=summary,
            clubs=clubs,
            leagues=leagues or list(source.get("leagues", [])),
            transfer_kind=verdict["kind"],
            transfer_confidence=verdict["confidence"],
            transfer_score=verdict["score"],
        ))
    return articles


def _dedupe_key(title: str) -> str:
    """媒体をまたいだ同一ニュースを寄せるためのキー。"""
    norm = normalize(title)
    norm = re.sub(r"[^\w\s]", " ", norm)
    words = [w for w in norm.split() if len(w) > 3]
    return " ".join(sorted(words)[:6])


def dedupe(articles: list[Article]) -> list[Article]:
    """同一ニュースは、より一次に近い媒体の版だけを残す。"""
    best: dict[str, Article] = {}
    for art in articles:
        key = _dedupe_key(art.title)
        if not key:
            key = art.url
        current = best.get(key)
        if current is None:
            best[key] = art
            continue
        # 一次性 → 新しさ の順で優劣を決める
        cand_rank = (_TIER_RANK.get(art.tier, 9), -(art.published or datetime.min.replace(tzinfo=timezone.utc)).timestamp())
        cur_rank = (_TIER_RANK.get(current.tier, 9), -(current.published or datetime.min.replace(tzinfo=timezone.utc)).timestamp())
        if cand_rank < cur_rank:
            best[key] = art
    return list(best.values())


def sort_articles(articles: list[Article]) -> list[Article]:
    """新しい順。日時不明の記事は末尾に送る。"""
    epoch = datetime.min.replace(tzinfo=timezone.utc)
    return sorted(articles, key=lambda a: (a.published or epoch), reverse=True)
