"""Jinja2 でサイトを書き出す。

`rel` は各ページからサイトルートへの相対パス。team/xxx.html は 1 階層深いので
"../" になる。これを間違えると CSS とリンクが全部壊れるので、ページ生成の
入口で必ず注入する。
"""

from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from jinja2 import Environment, FileSystemLoader, StrictUndefined, select_autoescape

from .providers.base import LEAGUE_LABELS
from .transfer import CONFIDENCE_LABELS, KIND_LABELS, TIER_LABELS

JST = ZoneInfo("Asia/Tokyo")


def _jst(dt: datetime | None) -> str:
    if not dt:
        return ""
    return dt.astimezone(JST).strftime("%m/%d %H:%M")


def _jst_time(dt: datetime | None) -> str:
    if not dt:
        return ""
    return dt.astimezone(JST).strftime("%H:%M")


def _jst_full(dt: datetime | None) -> str:
    if not dt:
        return ""
    return dt.astimezone(JST).strftime("%Y/%m/%d %H:%M")


def zone_class(league: str, position: int, total: int) -> str:
    """順位表の色帯。おおよその区分で、細目はシーズンごとに変わる。"""
    if league == "SA":
        if position <= 4:
            return "zone-ucl"
        if position <= 6:
            return "zone-uel"
        if position > total - 3:
            return "zone-releg"
    elif league == "SB":
        if position <= 2:
            return "zone-promo"
        if position <= 8:
            return "zone-playoff"
        if position > total - 3:
            return "zone-releg"
    return ""


class SiteRenderer:
    def __init__(self, templates_dir: Path, static_dir: Path, out_dir: Path, context: dict):
        self.out_dir = Path(out_dir)
        self.static_dir = Path(static_dir)
        self.base_context = context
        self.env = Environment(
            loader=FileSystemLoader(str(templates_dir)),
            autoescape=select_autoescape(["html"]),
            undefined=StrictUndefined,
            trim_blocks=True,
            lstrip_blocks=True,
        )
        self.env.filters["jst"] = _jst
        self.env.filters["jst_time"] = _jst_time
        self.env.filters["jst_full"] = _jst_full
        self.env.globals.update({
            "league_labels": LEAGUE_LABELS,
            "kind_labels": KIND_LABELS,
            "confidence_labels": CONFIDENCE_LABELS,
            "tier_labels": TIER_LABELS,
            "zone_class": zone_class,
        })
        self.written: list[Path] = []

    def render(self, template: str, out_path: str, **context) -> Path:
        depth = out_path.count("/")
        merged = dict(self.base_context)
        merged.update(context)
        merged["rel"] = "../" * depth
        html = self.env.get_template(template).render(**merged)
        target = self.out_dir / out_path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(html, encoding="utf-8")
        self.written.append(target)
        return target

    def copy_static(self) -> None:
        dest = self.out_dir / "static"
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(self.static_dir, dest)
        # GitHub Pages の Jekyll 処理を止める（_ で始まるパスを消されないように）
        (self.out_dir / ".nojekyll").write_text("", encoding="utf-8")
