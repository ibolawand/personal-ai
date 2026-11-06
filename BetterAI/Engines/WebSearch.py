"""
Web search for Aria, with no accounts and no API keys.

  SearXNG       — real web results (news, prices, anything recent) from a search engine running on this
                  computer in Docker (see searxng/README.md, one command to start). Used when it answers at
                  SEARXNG_URL (default http://127.0.0.1:8888). The top result's page is read too, so Aria can
                  answer from it, not just from a snippet.
  Wikipedia API — always: facts about people, places, history, science, definitions.
  DuckDuckGo    — instant answers (short facts), from its official API.

The tool returns the material; the model answers from it and names the source.
"""

import os
import re
import time
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


SEARXNG_URL = os.environ.get("SEARXNG_URL", "http://127.0.0.1:8888").rstrip("/")
RETRY_SEARXNG_S = 60       # after SearXNG didn't answer, don't wait for it again for a minute


class WebSearch:
    def __init__(self, searxng_url=None):
        self.searxng_url = (searxng_url or SEARXNG_URL).rstrip("/")
        self._searxng_down_at = 0.0

    def searxng_running(self) -> bool:
        try:
            return requests.get(self.searxng_url + "/healthz", headers=UA, timeout=2).status_code == 200
        except requests.RequestException:
            return False

    def search(self, query: str) -> str:
        query = (query or "").strip()
        if not query:
            return "What should I search for?"
        web = self._searxng(query)
        parts = list(web)
        instant = self._ddg_instant(query)
        if instant:
            parts.append(f"[DuckDuckGo] {instant}")
        if len(parts) < 3:
            parts += self._wikipedia(query)
        if not parts:
            return f"I couldn't find anything about '{query}'."
        note = ""
        if not web and RECENT_RE.search(query):
            note = ("\n(Only Wikipedia and instant answers were searched, which may not cover recent things. "
                    "If these don't answer it, say so instead of guessing.)")
        return (f"Search results for '{query}'. Answer from these in one or two spoken sentences and mention "
                f"where it's from (e.g. 'according to Wikipedia'):\n" + "\n\n".join(parts) + note)

    # ── sources ──

    def _searxng(self, query):
        if time.time() - self._searxng_down_at < RETRY_SEARXNG_S:
            return []
        try:
            r = requests.get(self.searxng_url + "/search", params={"q": query, "format": "json"},
                             headers=UA, timeout=(2, 8))
            r.raise_for_status()
            results = r.json().get("results", [])
        except Exception as e:
            self._searxng_down_at = time.time()
            if not isinstance(e, requests.ConnectionError):
                print(f"[WebSearch] SearXNG failed: {e}")
            return []
        out, read = [], False
        for res in results[:5]:
            snippet = re.sub(r"<[^>]+>", "", res.get("content") or "")
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
