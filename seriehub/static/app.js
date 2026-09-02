/* 原文 / 日本語 の表示切替と、移籍ボードの確度フィルタ。
   翻訳はビルド時に済ませて両方を HTML に埋め込んであるので、
   ここでの切替は表示の出し分けだけ。ネットワークは使わない。 */

(function () {
  "use strict";

  var LANG_KEY = "seriehub:lang";
  var FILTER_KEY = "seriehub:confidence";

  function readStore(key, fallback) {
    try {
      var v = window.localStorage.getItem(key);
      return v === null ? fallback : v;
    } catch (e) {
      return fallback;   // プライベートウィンドウ等で localStorage が使えない場合
    }
  }

  function writeStore(key, value) {
    try {
      window.localStorage.setItem(key, value);
    } catch (e) {
      /* 保存できなくても表示は成立する */
    }
  }

  /* ---------- 翻訳トグル ---------- */
  function applyLang(lang) {
    document.body.classList.toggle("lang-ja", lang === "ja");
    var buttons = document.querySelectorAll(".lang-toggle button");
    for (var i = 0; i < buttons.length; i++) {
      buttons[i].setAttribute("aria-pressed", String(buttons[i].dataset.lang === lang));
    }
  }

  function initLang() {
    var toggle = document.querySelector(".lang-toggle");
    if (!toggle) return;
    var lang = readStore(LANG_KEY, toggle.dataset.default || "it");
    applyLang(lang);
    toggle.addEventListener("click", function (ev) {
      var btn = ev.target.closest("button[data-lang]");
      if (!btn) return;
      applyLang(btn.dataset.lang);
      writeStore(LANG_KEY, btn.dataset.lang);
    });
  }

  /* ---------- 確度フィルタ ---------- */
  function applyFilter(value) {
    var items = document.querySelectorAll("[data-confidence]");
    for (var i = 0; i < items.length; i++) {
      var conf = items[i].getAttribute("data-confidence");
      items[i].hidden = !(value === "all" || conf === value);
    }
    var buttons = document.querySelectorAll(".filters button[data-confidence-filter]");
    for (var j = 0; j < buttons.length; j++) {
      var btn = buttons[j];
      btn.setAttribute("aria-pressed", String(btn.dataset.confidenceFilter === value));
    }
    var lists = document.querySelectorAll("[data-filterable-list]");
    for (var k = 0; k < lists.length; k++) {
      var visible = lists[k].querySelectorAll("[data-confidence]:not([hidden])").length;
      var empty = lists[k].parentNode.querySelector("[data-empty-note]");
      if (empty) empty.hidden = visible > 0;
    }
  }

  function initFilter() {
    var bar = document.querySelector(".filters[data-confidence-bar]");
    if (!bar) return;
    applyFilter(readStore(FILTER_KEY, "all"));
    bar.addEventListener("click", function (ev) {
      var btn = ev.target.closest("button[data-confidence-filter]");
      if (!btn) return;
      applyFilter(btn.dataset.confidenceFilter);
      writeStore(FILTER_KEY, btn.dataset.confidenceFilter);
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", function () { initLang(); initFilter(); });
  } else {
    initLang();
    initFilter();
  }
})();
