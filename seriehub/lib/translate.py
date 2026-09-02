"""ビルド時の翻訳。原文は必ず保持し、訳文を横に足すだけ。

エンジンの優先順位:
  1. DeepL      … DEEPL_API_KEY があれば使用。伊→日の品質が最も高い。
  2. MyMemory   … キー不要。無料枠が小さいので予備。
  3. NullEngine … キーも通信も無い環境。原文をそのまま通す。

翻訳結果は data/translation_cache.json に貯め、同じ見出しを二度課金しない。
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import requests

DEEPL_FREE = "https://api-free.deepl.com/v2/translate"
DEEPL_PRO = "https://api.deepl.com/v2/translate"
MYMEMORY = "https://api.mymemory.translated.net/get"

# MyMemory は 1 リクエスト 500 バイト程度が上限
_MYMEMORY_MAX = 480


class TranslationCache:
    def __init__(self, path: Path):
        self.path = path
        self._data: dict[str, str] = {}
        if path.exists():
            try:
                self._data = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                self._data = {}
        self.hits = 0
        self.misses = 0

    @staticmethod
    def key(text: str, src: str, dest: str) -> str:
        return f"{src}>{dest}:{text}"

    def get(self, text: str, src: str, dest: str) -> str | None:
        v = self._data.get(self.key(text, src, dest))
        if v is not None:
            self.hits += 1
        return v

    def put(self, text: str, src: str, dest: str, value: str) -> None:
        self._data[self.key(text, src, dest)] = value
        self.misses += 1

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(self._data, ensure_ascii=False, indent=0, sort_keys=True),
            encoding="utf-8",
        )


class NullEngine:
    name = "none"
    available = False

    def translate(self, texts: list[str], src: str, dest: str) -> list[str]:
        return ["" for _ in texts]


class DeepLEngine:
    name = "deepl"

    def __init__(self, api_key: str, timeout: int = 20):
        self.api_key = api_key
        self.timeout = timeout
        # 無料キーは ":fx" で終わる
        self.endpoint = DEEPL_FREE if api_key.endswith(":fx") else DEEPL_PRO

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    def translate(self, texts: list[str], src: str, dest: str) -> list[str]:
        if not texts:
            return []
        resp = requests.post(
            self.endpoint,
            headers={"Authorization": f"DeepL-Auth-Key {self.api_key}"},
            data=[("text", t) for t in texts]
            + [("source_lang", src.upper()), ("target_lang", dest.upper())],
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return [t.get("text", "") for t in resp.json().get("translations", [])]


class MyMemoryEngine:
    """キー不要の無料翻訳。1件ずつしか投げられないので低速・小容量向け。"""

    name = "mymemory"
    available = True

    def __init__(self, email: str = "", timeout: int = 20):
        self.email = email
        self.timeout = timeout

    def translate(self, texts: list[str], src: str, dest: str) -> list[str]:
        out: list[str] = []
        for text in texts:
            snippet = text[:_MYMEMORY_MAX]
            params = {"q": snippet, "langpair": f"{src}|{dest}"}
            if self.email:
                params["de"] = self.email
            try:
                resp = requests.get(MYMEMORY, params=params, timeout=self.timeout)
                resp.raise_for_status()
                data = resp.json()
                translated = (data.get("responseData") or {}).get("translatedText", "")
                # 制限超過時は本文にエラー文字列が返るので弾く
                if translated and "MYMEMORY WARNING" not in translated.upper():
                    out.append(translated)
                else:
                    out.append("")
            except (requests.RequestException, ValueError):
                out.append("")
            time.sleep(0.4)  # 無料枠のレート制限に配慮
        return out


def build_engine(prefer: str = "auto") -> object:
    """環境変数を見て翻訳エンジンを決める。"""
    deepl_key = os.environ.get("DEEPL_API_KEY", "").strip()
    email = os.environ.get("MYMEMORY_EMAIL", "").strip()

    if prefer == "none":
        return NullEngine()
    if prefer in ("deepl", "auto") and deepl_key:
        return DeepLEngine(deepl_key)
    if prefer == "deepl" and not deepl_key:
        return NullEngine()
    if prefer in ("mymemory", "auto"):
        return MyMemoryEngine(email)
    return NullEngine()


class Translator:
    """キャッシュ付きの翻訳窓口。失敗しても例外を外に出さない。"""

    def __init__(self, engine, cache: TranslationCache, dest: str = "ja",
                 batch_size: int = 25, limit: int = 0):
        self.engine = engine
        self.cache = cache
        self.dest = dest
        self.batch_size = batch_size
        self.limit = limit          # 1ビルドあたりの新規翻訳上限（0で無制限）
        self.translated = 0
        self.errors = 0

    @property
    def engine_name(self) -> str:
        return getattr(self.engine, "name", "none")

    def translate_many(self, texts: list[str], src: str) -> list[str]:
        """原文リストを訳文リストに変換する。訳せなかった要素は空文字。"""
        results: list[str] = [""] * len(texts)
        pending: list[tuple[int, str]] = []

        for i, text in enumerate(texts):
            if not text or not text.strip():
                continue
            if src == self.dest:
                results[i] = text
                continue
            cached = self.cache.get(text, src, self.dest)
            if cached is not None:
                results[i] = cached
                continue
            pending.append((i, text))

        if not getattr(self.engine, "available", False):
            return results

        if self.limit:
            room = max(0, self.limit - self.translated)
            pending = pending[:room]

        for start in range(0, len(pending), self.batch_size):
            chunk = pending[start:start + self.batch_size]
            try:
                out = self.engine.translate([t for _, t in chunk], src, self.dest)
            except Exception:                # 翻訳の失敗でビルド全体を止めない
                self.errors += 1
                continue
            for (idx, original), translated in zip(chunk, out):
                if translated:
                    results[idx] = translated
                    self.cache.put(original, src, self.dest, translated)
                    self.translated += 1
        return results
