"""Extract interactive elements from a Playwright page as Facts.

The browser script only collects raw data. All filtering happens in Python
(see salience.py) so that every dropped element gets a reason code.
"""

from __future__ import annotations

from .facts import Fact, clean_label, fact_id

SELECTOR = "a,button,input,select,textarea,[role=button],[role=link],[onclick],h1,h2,h3,h4"

_SCRIPT = """
(sel) => {
  const vh = window.innerHeight;
  const cssPath = (el) => {
    const parts = [];
    for (let e = el; e && e.nodeType === 1 && e !== document.documentElement; e = e.parentElement) {
      let i = 1;
      for (let s = e.previousElementSibling; s; s = s.previousElementSibling) if (s.tagName === e.tagName) i++;
      parts.unshift(e.tagName.toLowerCase() + ':nth-of-type(' + i + ')');
    }
    return 'html>' + parts.join('>');
  };
  const labelOf = (el) => {
    const aria = el.getAttribute('aria-label');
    if (aria) return aria;
    const by = el.getAttribute('aria-labelledby');
    if (by) { const t = by.split(/\\s+/).map(id => document.getElementById(id)?.innerText || '').join(' ').trim(); if (t) return t; }
    if (el.labels && el.labels.length) return el.labels[0].innerText;
    const tag = el.tagName.toLowerCase();
    if (tag === 'input' && ['submit', 'button', 'reset'].includes(el.type)) return el.value;
    if (tag === 'select') return el.name || el.id || '';
    const text = el.innerText;
    if (text && text.trim()) return text;
    const img = el.querySelector('img[alt]');
    if (img) return img.alt;
    return el.getAttribute('placeholder') || el.getAttribute('title') || el.getAttribute('alt') || '';
  };
  return Array.from(document.querySelectorAll(sel)).map((el) => {
    const r = el.getBoundingClientRect();
    const cs = getComputedStyle(el);
    const visible = r.width > 0 && r.height > 0 && cs.display !== 'none' &&
      cs.visibility !== 'hidden' && !el.closest('[aria-hidden="true"],[hidden]');
    let href = null;
    if (el.tagName === 'A' && el.getAttribute('href')) {
      try { href = new URL(el.href).pathname; } catch (e) {}
    }
    return {
      tag: el.tagName.toLowerCase(),
      role: el.getAttribute('role'),
      type: el.getAttribute('type'),
      name: el.getAttribute('name'),
      href_path: href,
      onclick: el.hasAttribute('onclick'),
      label: labelOf(el),
      visible,
      enabled: !el.disabled && el.getAttribute('aria-disabled') !== 'true',
      in_viewport: visible && r.bottom > 0 && r.top < vh,
      y: Math.round(r.top + window.scrollY),
      path: cssPath(el),
    };
  });
}
"""


def _kind(raw: dict) -> str:
    tag, role, typ = raw["tag"], raw["role"], (raw["type"] or "").lower()
    if role == "link" or tag == "a":
        return "link"
    if role == "button" or tag == "button" or (tag == "input" and typ in ("submit", "button", "reset", "image")):
        return "button"
    if tag in ("input", "textarea"):
        return "input"
    if tag == "select":
        return "select"
    if tag in ("h1", "h2", "h3", "h4"):
        return "text"
    return "button"  # [onclick] on a generic element


def to_fact(raw: dict) -> Fact:
    label = clean_label(raw["label"])
    attrs = {k: raw[k] for k in ("type", "href_path", "name") if raw.get(k)}
    return Fact(
        id=fact_id(raw["tag"], label, raw["path"]),
        kind=_kind(raw),
        label=label,
        attrs=attrs,
        visible=raw["visible"],
        enabled=raw["enabled"],
        in_viewport=raw["in_viewport"],
        y=raw["y"],
        selector=raw["path"],
    )


async def extract(page) -> list[Fact]:
    """Return every candidate element on the page as a Fact, in document order."""
    raws = await page.evaluate(_SCRIPT, SELECTOR)
    return [to_fact(r) for r in raws]
