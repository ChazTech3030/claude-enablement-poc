/* Enablement site behaviour: accessibility toggles. No third-party code. */
(function () {
  "use strict";
  var root = document.documentElement;

  function store(key, value) {
    try { if (value) localStorage.setItem(key, value); else localStorage.removeItem(key); } catch (e) {}
  }

  // ---- accessibility toggles (light/dark is Material's own palette toggle) ----
  var ICONS = {
    contrast: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M12 2a10 10 0 1 0 0 20 10 10 0 0 0 0-20Zm0 18V4a8 8 0 0 1 0 16Z"/></svg>',
    font: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M9.6 14H14.4L12 7.6 9.6 14ZM11 5h2l5.5 14h-2.2l-1.2-3H8.9l-1.2 3H5.5L11 5Z"/></svg>'
  };

  function toggle(attr, key, on, label, icon) {
    var b = document.createElement("button");
    b.type = "button";
    b.className = "md-header__button md-icon dk-toggle";
    b.setAttribute("aria-label", label);
    b.title = label;
    b.innerHTML = icon;
    function sync() { b.setAttribute("aria-pressed", root.getAttribute(attr) === on ? "true" : "false"); }
    b.addEventListener("click", function () {
      var active = root.getAttribute(attr) === on;
      if (active) root.removeAttribute(attr); else root.setAttribute(attr, on);
      store(key, active ? null : on);
      sync();
    });
    sync();
    return b;
  }

  function mountToggles() {
    var header = document.querySelector(".md-header__inner");
    if (!header || header.querySelector(".dk-toggle")) return;
    var anchor = header.querySelector("form.md-header__option") || header.querySelector(".md-search");
    var group = document.createElement("div");
    group.className = "dk-toggles";
    group.appendChild(toggle("data-dk-contrast", "dk-contrast", "high", "High contrast", ICONS.contrast));
    group.appendChild(toggle("data-dk-font", "dk-font", "dyslexic", "Dyslexia-friendly font and spacing", ICONS.font));
    header.insertBefore(group, anchor || null);
  }

  function init() {
    mountToggles();
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
