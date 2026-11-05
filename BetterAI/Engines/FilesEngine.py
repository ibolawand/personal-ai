"""
Find, open and read files — only inside allowed folders.

Allowed folders come from FILE_ROOTS in Engines/.env (colon-separated), default:
~/Desktop/school, ~/Documents, ~/Downloads, ~/Desktop

Reading is text-only and capped so it fits the LLM's context. Moving files
(tidy Downloads) always shows a preview and needs confirmation, and can be undone.
"""

import datetime
import json
import os
import re
import shutil
import sqlite3
import subprocess
import threading
import time
import zipfile
from pathlib import Path

HOME = Path.home()
DEFAULT_ROOTS = ["~/Desktop/school", "~/Documents", "~/Downloads", "~/Desktop"]
SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "__pycache__", ".idea", ".vs", "bin", "obj",
             "dist", "build", ".cache", ".gradle", "target"}
MAX_READ_CHARS = 6000   # ~1.5k tokens; keeps the LLM context from overflowing
MAX_SCAN_FILES = 40000

KINDS = {
    "pdf": {".pdf"},
    "document": {".pdf", ".docx", ".doc", ".odt", ".txt", ".md", ".rtf"},
    "slides": {".pptx", ".ppt", ".odp", ".key"},
    "spreadsheet": {".xlsx", ".xls", ".ods", ".csv"},
    "code": {".py", ".cs", ".java", ".js", ".ts", ".tsx", ".c", ".cpp", ".h", ".sql", ".html", ".css",
             ".ipynb", ".json", ".xml", ".sh", ".kt", ".go", ".rs", ".php"},
    "image": {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".heic"},
    "audio": {".mp3", ".wav", ".flac", ".m4a", ".ogg"},
    "video": {".mp4", ".mkv", ".mov", ".webm", ".avi"},
    "archive": {".zip", ".tar", ".gz", ".7z", ".rar", ".xz"},
}
TEXT_EXTS = {".txt", ".md", ".csv", ".log", ".rtf"} | KINDS["code"]

TIDY_FOLDERS = {
    "Documents": KINDS["document"] | KINDS["slides"] | KINDS["spreadsheet"],
    "Images": KINDS["image"], "Audio": KINDS["audio"], "Video": KINDS["video"],
    "Archives": KINDS["archive"], "Installers": {".deb", ".appimage", ".exe", ".msi", ".rpm", ".run"},
    "Code": KINDS["code"] - {".json", ".xml"},
}
TIDY_LOG = Path(__file__).resolve().parent.parent / "tidy_downloads_log.json"

# Text of Lala's documents, so "the pdf that mentions normalization" can be found by what's inside.
# Kept in Aria's cache folder; rebuilt for changed files every 30 minutes.
INDEX_FILE = Path(os.environ.get("XDG_CACHE_HOME", os.path.expanduser("~/.cache"))) / "aria" / "file_index.db"
INDEX_EXTS = {".pdf", ".docx", ".pptx", ".odt", ".odp", ".txt", ".md", ".ipynb"}
INDEX_MAX_BYTES = 500_000_000   # only the text is kept, so big scanned textbooks are fine
INDEX_MAX_CHARS = 300_000
INDEX_EVERY_S = 30 * 60


def _age(ts: float) -> str:
    days = (time.time() - ts) / 86400
    if days < 1:
        return "today"
    if days < 2:
        return "yesterday"
    if days < 14:
        return f"{int(days)} days ago"
    return datetime.date.fromtimestamp(ts).strftime("%d %b %Y")


def _words(s: str):
    return [w for w in re.split(r"[\W_]+", s.lower()) if w]


class FilesEngine:
    def __init__(self, confirmer, roots=None):
        self.confirm = confirmer
        env = os.environ.get("FILE_ROOTS")
        raw = roots or (env.split(":") if env else DEFAULT_ROOTS)
        self.roots = [Path(os.path.expanduser(r)).resolve() for r in raw]
        self.roots = [r for r in self.roots if r.is_dir()]
        self.last_results = []
        self._index_lock = threading.Lock()
        self.index_ready = False

    # ── Content index ─────────────────────────────────────────────────────────

    def start_indexing(self):
        def loop():
            while True:
                try:
                    n = self.update_index()
                    if n:
                        print(f"[Files] indexed {n} document(s)")
                except Exception as e:
                    print(f"[Files] indexing failed: {e}")
                time.sleep(INDEX_EVERY_S)
        threading.Thread(target=loop, daemon=True).start()

    def _index_db(self):
        INDEX_FILE.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(INDEX_FILE, timeout=10)
        conn.execute("CREATE TABLE IF NOT EXISTS docs (path TEXT PRIMARY KEY, mtime REAL, text TEXT)")
        return conn

    def _documents(self):
        seen = set()
        for root in self.roots:
            for dirpath, dirnames, filenames in os.walk(root):
                dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")]
                for name in filenames:
                    p = Path(dirpath) / name
                    if p.suffix.lower() in INDEX_EXTS and p not in seen:
                        seen.add(p)
                        yield p

    def update_index(self) -> int:
        """(Re)reads new or changed documents; drops deleted ones. Returns how many were read."""
        with self._index_lock:
            conn = self._index_db()
            try:
                known = dict(conn.execute("SELECT path, mtime FROM docs"))
                present, changed = set(), 0
                for p in self._documents():
                    try:
                        st = p.stat()
                    except OSError:
                        continue
                    present.add(str(p))
                    if st.st_size > INDEX_MAX_BYTES or known.get(str(p)) == st.st_mtime:
                        continue
                    try:
                        text = self._extract(p, pdf_pages=300)[:INDEX_MAX_CHARS]
                    except Exception:
                        text = ""
                    conn.execute("INSERT OR REPLACE INTO docs VALUES (?, ?, ?)", (str(p), st.st_mtime, text))
                    changed += 1
                gone = [k for k in known if k not in present]
                conn.executemany("DELETE FROM docs WHERE path = ?", [(k,) for k in gone])
                conn.commit()
            finally:
                conn.close()
            self.index_ready = True
            return changed

    def search_contents(self, query: str):
        """Documents whose text mentions the query words, best first, with a snippet from each."""
        words = [w for w in _words(query) if len(w) > 2 and w not in {"the", "and", "about", "that", "with",
                                                                        "pdf", "file", "document", "mentions"}]
        if not words:
            return "What should the document be about?"
        if not self.index_ready:
            self.update_index()
        conn = self._index_db()
        try:
            rows = conn.execute("SELECT path, mtime, text FROM docs").fetchall()
        finally:
            conn.close()
        hits = []
        for path, mtime, text in rows:
            low = (text or "").lower()
            counts = [low.count(w) for w in words]
            if not all(counts):            # every word must appear somewhere in the document
                continue
            p = Path(path)
            if not p.exists() or not self._allowed(p):
                continue
            score = sum(min(c, 20) for c in counts) + 5 * sum(w in p.stem.lower() for w in words)
            pos = min(low.find(w) for w in words)
            snippet = " ".join(text[max(0, pos - 80):pos + 220].split())
            hits.append((score, p, mtime, snippet))
        hits.sort(key=lambda h: -h[0])
        hits = hits[:5]
        self.last_results = [p for _, p, _, _ in hits]
        if not hits:
            return f"No document mentions {' and '.join(words)}."
        lines = [f"{i}. {p.name} — {self._pretty(p.parent)}, modified {_age(m)}: \"…{snip}…\""
                 for i, (_, p, m, snip) in enumerate(hits, 1)]
        return "Documents that mention it:\n" + "\n".join(lines)

    # ── Safety ────────────────────────────────────────────────────────────────

    def _allowed(self, path: Path) -> bool:
        try:
            p = path.resolve()
        except Exception:
            return False
        return any(p == r or r in p.parents for r in self.roots)

    def _resolve(self, which: str):
        """'1' / 'second' / 'the pdf' / a filename / a path → Path from the last search, or a fresh search."""
        which = (which or "").strip()
        ordinals = {"first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5, "last": -1, "that": 1, "it": 1}
        idx = None
        if which.isdigit():
            idx = int(which)
        else:
            for w, n in ordinals.items():
                if re.search(rf"\b{w}\b", which.lower()):
                    idx = n
                    break
        if idx is not None and self.last_results:
            i = idx - 1 if idx > 0 else idx
            if -len(self.last_results) <= i < len(self.last_results):
                return self.last_results[i]
        p = Path(os.path.expanduser(which))
        if p.is_absolute() and p.exists():
            return p if self._allowed(p) else None
        for r in self.last_results:
            if which.lower() in r.name.lower():
                return r
        hits = self._search(which, limit=1)
        return hits[0][1] if hits else None

    # ── Search ────────────────────────────────────────────────────────────────

    def _search(self, query: str, kind: str = None, days=None, folders=False, limit=8):
        q_words = [w for w in _words(query or "") if w not in {"the", "my", "a", "file", "files", "folder"}]
        exts = KINDS.get((kind or "").lower().rstrip("s")) or KINDS.get((kind or "").lower())
        cutoff = time.time() - float(days) * 86400 if days not in (None, "", 0) else None
        scored, seen = [], 0
        for root in self.roots:
            for dirpath, dirnames, filenames in os.walk(root):
                dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")]
                names = dirnames if folders else filenames
                for name in names:
                    seen += 1
                    if seen > MAX_SCAN_FILES:
                        break
                    path = Path(dirpath) / name
                    if not folders and exts and path.suffix.lower() not in exts:
                        continue
                    try:
                        mtime = path.stat().st_mtime
                    except OSError:
                        continue
                    if cutoff and mtime < cutoff:
                        continue
                    name_words = _words(path.stem)
                    parent_words = _words(str(path.parent.relative_to(root)))
                    score = 0.0
                    for w in q_words:
                        if w in name_words:
                            score += 3
                        elif any(nw.startswith(w) or w in nw for nw in name_words):
                            score += 2
                        elif any(w in pw for pw in parent_words):
                            score += 1
                    if q_words and score == 0:
                        continue
                    # newer files win ties
                    score += max(0.0, 1 - (time.time() - mtime) / (86400 * 90)) * 0.9
                    scored.append((score, path, mtime))
        scored.sort(key=lambda x: (-x[0], -x[2]))
        # de-dup identical paths reached through overlapping roots (~/Desktop and ~/Desktop/school)
        out, seen_paths = [], set()
        for s, p, m in scored:
            if p not in seen_paths:
                seen_paths.add(p)
                out.append((s, p, m))
            if len(out) >= limit:
                break
        return out

    def _pretty(self, p: Path) -> str:
        try:
            return "~/" + str(p.relative_to(HOME))
        except ValueError:
            return str(p)

    def find_files(self, query: str = "", kind: str = None, days=None):
        hits = self._search(query, kind, days)
        self.last_results = [p for _, p, _ in hits]
        if not hits and query and not days and (not kind or KINDS.get(kind.lower().rstrip("s"), INDEX_EXTS) & INDEX_EXTS):
            # no file is *named* like that: look for documents that are *about* it ("the pdf about gear trains")
            inside = self.search_contents(query)
            if inside.startswith("Documents that mention"):
                return "No file names match, but these " + inside[0].lower() + inside[1:]
        if not hits:
            where = ", ".join(self._pretty(r) for r in self.roots)
            return f"No files found for '{query}' in {where}."
        lines = [f"{i}. {p.name} — {self._pretty(p.parent)}, modified {_age(m)}" for i, (_, p, m) in enumerate(hits, 1)]
        return "Found:\n" + "\n".join(lines)

    # ── Open / read ───────────────────────────────────────────────────────────

    def open_file(self, which: str):
        p = self._resolve(which)
        if not p or not p.exists():
            return f"I couldn't find '{which}'. Try find_files first."
        if not self._allowed(p):
            return "That file is outside the folders I'm allowed to touch."
        subprocess.Popen(["xdg-open", str(p)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)
        return f"Opening {p.name}."

    def open_folder(self, name: str):
        hits = self._search(name, folders=True, limit=1)
        target = hits[0][1] if hits else next((r for r in self.roots if name.lower() in r.name.lower()), None)
        if not target:
            return f"No folder like '{name}'."
        subprocess.Popen(["xdg-open", str(target)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         start_new_session=True)
        return f"Opening {self._pretty(target)}."

    def read_file(self, which: str):
        p = self._resolve(which)
        if not p or not p.is_file():
            return f"I couldn't find '{which}'. Try find_files first."
        if not self._allowed(p):
            return "That file is outside the folders I'm allowed to read."
        try:
            text = self._extract(p)
        except Exception as e:
            return f"Couldn't read {p.name}: {e}"
        text = re.sub(r"\n{3,}", "\n\n", text).strip()
        if not text:
            return f"{p.name} has no readable text (it may be scanned images)."
        cut = len(text) > MAX_READ_CHARS
        text = text[:MAX_READ_CHARS]
        note = f"\n…[truncated — showing the first {MAX_READ_CHARS} characters]" if cut else ""
        return f"Contents of {p.name}:\n{text}{note}"

    def _extract(self, p: Path, pdf_pages=40) -> str:
        ext = p.suffix.lower()
        if ext == ".pdf":
            out = subprocess.run(["pdftotext", "-l", str(pdf_pages), "-layout", str(p), "-"],
                                 capture_output=True, text=True, timeout=120)
            return out.stdout
        if ext in (".docx", ".pptx", ".odt", ".odp"):
            with zipfile.ZipFile(p) as z:
                if ext == ".docx":
                    parts = ["word/document.xml"]
                elif ext == ".pptx":
                    parts = sorted((n for n in z.namelist() if re.match(r"ppt/slides/slide\d+\.xml", n)),
                                   key=lambda n: int(re.findall(r"\d+", n)[0]))
                else:
                    parts = ["content.xml"]
                chunks = []
                for i, part in enumerate(parts, 1):
                    xml = z.read(part).decode("utf8", "ignore")
                    xml = re.sub(r"</(w:p|a:p|text:p|text:h)>", "\n", xml)
                    body = re.sub(r"<[^>]+>", "", xml)
                    chunks.append((f"[Slide {i}]\n" if ext == ".pptx" else "") + body)
                import html
                return html.unescape("\n".join(chunks))
        if ext == ".ipynb":
            nb = json.loads(p.read_text("utf8", "ignore"))
            return "\n\n".join("".join(c.get("source", "")) for c in nb.get("cells", []))
        if ext in TEXT_EXTS or p.stat().st_size < 200_000:
            data = p.read_bytes()[:400_000]
            if b"\0" in data[:2000]:
                raise ValueError("it's a binary file")
            return data.decode("utf8", "ignore")
        raise ValueError(f"I can't read {ext} files")

    # ── Tidy Downloads ────────────────────────────────────────────────────────

    def _tidy_plan(self):
        dl = HOME / "Downloads"
        plan = []
        for f in dl.iterdir():
            if not f.is_file() or f.name.startswith(".") or f.suffix in (".part", ".crdownload"):
                continue
            if time.time() - f.stat().st_mtime < 3600:  # leave files that are still fresh / downloading
                continue
            folder = next((name for name, exts in TIDY_FOLDERS.items() if f.suffix.lower() in exts), "Other")
            plan.append((f, dl / folder / f.name))
        return plan

    def tidy_downloads(self):
        plan = self._tidy_plan()
        if not plan:
            return "Downloads is already tidy."
        counts = {}
        for _, dest in plan:
            counts[dest.parent.name] = counts.get(dest.parent.name, 0) + 1
        summary = ", ".join(f"{n} to {k}" for k, n in sorted(counts.items(), key=lambda x: -x[1]))

        def do():
            moved = []
            for src, dest in plan:
                if not src.exists():
                    continue
                dest.parent.mkdir(exist_ok=True)
                final = dest
                i = 1
                while final.exists():
                    final = dest.with_name(f"{dest.stem} ({i}){dest.suffix}")
                    i += 1
                shutil.move(str(src), str(final))
                moved.append([str(src), str(final)])
            TIDY_LOG.write_text(json.dumps({"time": time.time(), "moved": moved}, indent=1))
            return f"Moved {len(moved)} files into folders. Say 'undo the tidy' to put them back."
        return self.confirm.request(f"move {len(plan)} files in Downloads into folders ({summary})", do)

    def undo_tidy_downloads(self):
        if not TIDY_LOG.exists():
            return "There's no tidy to undo."
        moved = json.loads(TIDY_LOG.read_text())["moved"]

        def do():
            n = 0
            for src, final in reversed(moved):
                if Path(final).exists() and not Path(src).exists():
                    shutil.move(final, src)
                    n += 1
            TIDY_LOG.unlink()
            return f"Put {n} files back where they were."
        return self.confirm.request(f"move {len(moved)} files back to the top of Downloads", do)
