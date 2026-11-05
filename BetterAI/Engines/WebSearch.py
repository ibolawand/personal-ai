"""
Web search for Aria, using only official APIs (no scraping of search result pages).

  Brave Search API  — real web results (news, prices, anything recent). Used when BRAVE_API_KEY is set in
                      Engines/.env. Free plan: https://brave.com/search/api/ (about 2000 searches a month).
                      The top result's page is read too, so Aria can answer from it, not just from a snippet.
  Wikipedia API     — always, no key: facts about people, places, history, science, definitions.
  DuckDuckGo        — instant answers (short facts, calculations), no key.

The tool returns the material; the model answers from it and names the source.
"""

import os
import re
from html.parser import HTMLParser
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

UA = {"User-Agent": "Aria-desk-assistant/1.0 (personal local assistant)"}
TIMEOUT = 6
MAX_PAGE_CHARS = 1800      # per page read; keeps the whole result well inside the model's context
MAX_WIKI_CHARS = (1800, 600)   # top article, second article
QUESTION_WORDS = re.compile(r"\b(who|what|when|where|why|how|which|is|are|was|were|does|do|did|can|could|"
                            r"tell me|about|explain|the|a|an|work|works|mean|means|meaning of)\b|[?!.,]", re.I)
RECENT_RE = re.compile(r"\b(today|tonight|yesterday|latest|news|current|now|this (?:week|month|year)|price|cost|"
                       r"score|weather|release|20\d\d)\b", re.I)


def _get_json(url, params):
    """GET with one retry: Wikipedia answers a quick burst of requests with a non-JSON 'slow down' page."""
    for attempt in range(2):
        r = requests.get(url, params=params, headers=UA, timeout=TIMEOUT)
        try:
            return r.json()
        except ValueError:
            if attempt == 0:
                import time
                time.sleep(1.5)
    raise ValueError(f"no JSON from {url} (HTTP {r.status_code})")


class _TextExtractor(HTMLParser):
    """Visible text of a page, without scripts, styles, menus and footers."""
    SKIP = {"script", "style", "noscript", "nav", "footer", "header", "aside", "form", "svg", "button"}

    def __init__(self):
        super().__init__()
        self.parts, self._skip = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self._skip += 1
        elif tag in ("p", "br", "li", "h1", "h2", "h3", "tr"):
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self.SKIP and self._skip:
            self._skip -= 1

    def handle_data(self, data):
        if not self._skip:
            self.parts.append(data)


def page_text(url: str) -> str:
    try:
        r = requests.get(url, headers=UA, timeout=TIMEOUT, stream=True)
        if r.status_code != 200 or "html" not in r.headers.get("content-type", ""):
            return ""
        raw = r.raw.read(1_000_000, decode_content=True).decode(r.encoding or "utf-8", errors="ignore")
    except Exception:
        return ""
    p = _TextExtractor()
    try:
        p.feed(raw)
    except Exception:
        return ""
    lines = [" ".join(l.split()) for l in "".join(p.parts).splitlines()]
    # keep sentence-like lines (drops leftover menu items and buttons)
    text = "\n".join(l for l in lines if len(l) > 60)
    return text[:MAX_PAGE_CHARS]


class WebSearch:
    def __init__(self):
        self.brave_key = os.environ.get("BRAVE_API_KEY", "").strip()

    def search(self, query: str) -> str:
        query = (query or "").strip()
        if not query:
            return "What should I search for?"
        parts = []
        if self.brave_key:
            parts += self._brave(query)
        instant = self._ddg_instant(query)
        if instant:
            parts.append(f"[DuckDuckGo] {instant}")
        if not self.brave_key or len(parts) < 2:
            parts += self._wikipedia(query)
        if not parts:
            return f"I couldn't find anything about '{query}'."
        note = ""
        if not self.brave_key and RECENT_RE.search(query):
            note = ("\n(Only Wikipedia and instant answers were searched, which may not cover recent things. "
                    "If these don't answer it, say so instead of guessing.)")
        return (f"Search results for '{query}'. Answer from these in one or two spoken sentences and mention "
                f"where it's from (e.g. 'according to Wikipedia'):\n" + "\n\n".join(parts) + note)

    # ── sources ──

    def _brave(self, query):
        try:
            r = requests.get("https://api.search.brave.com/res/v1/web/search",
                             params={"q": query, "count": 5},
                             headers={"Accept": "application/json", "X-Subscription-Token": self.brave_key},
                             timeout=TIMEOUT)
            r.raise_for_status()
            results = r.json().get("web", {}).get("results", [])
        except Exception as e:
            print(f"[WebSearch] Brave failed: {e}")
            return []
        out, read = [], False
        for res in results[:5]:
            snippet = re.sub(r"<[^>]+>", "", res.get("description", ""))
            out.append(f"[{res.get('title', '')} — {res.get('url', '')}] {snippet}")
            if not read:       # read the first page that loads, for detail beyond the snippet
                text = page_text(res.get("url", ""))
                if text:
                    out[-1] += f"\nFrom the page:\n{text}"
                    read = True
        return out

    def _ddg_instant(self, query):
        try:
            data = requests.get("https://api.duckduckgo.com/",
                                params={"q": query, "format": "json", "no_html": 1, "skip_disambig": 1},
                                headers=UA, timeout=TIMEOUT).json()
        except Exception:
            return ""
        answer = data.get("Answer") or data.get("AbstractText") or ""
        if isinstance(answer, dict):
            answer = answer.get("result", "")
        return str(answer).strip()

    def _wikipedia(self, query):
        """One request: search + intro text of the top hits (Wikipedia rate-limits bursts of calls)."""
        keywords = " ".join(QUESTION_WORDS.sub(" ", query).split()) or query
        try:
            data = _get_json("https://en.wikipedia.org/w/api.php", {
                "action": "query", "format": "json", "redirects": 1,
                "generator": "search", "gsrsearch": keywords, "gsrlimit": 4,
                "prop": "extracts", "exintro": 1, "explaintext": 1, "exlimit": 4})
        except Exception as e:
            print(f"[WebSearch] Wikipedia failed: {e}")
            return []
        pages = [p for p in data.get("query", {}).get("pages", {}).values()
                 if p.get("extract") and "(disambiguation)" not in p["title"]]
        # search rank, but an article named exactly like the topic ("Photosynthesis") goes first
        pages.sort(key=lambda p: (p["title"].lower() != keywords.lower(), p.get("index", 99)))
        return [f"[Wikipedia: {p['title']}] {p['extract'].strip()[:MAX_WIKI_CHARS[min(i, 1)]]}"
                for i, p in enumerate(pages[:2])]
