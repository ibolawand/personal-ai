"""
Aria writes and reworks MyNotion notes: "write a study sheet on the French Revolution", "organise this note",
"add a section about mitosis", "put a summary at the top", "fix the spelling", "translate it into English".

The model works in Markdown, which it writes well; this file turns MyNotion's HTML into Markdown and back:
  headings, lists, to-dos (- [ ]), tables, formulas ($…$ / $$…$$), callouts (::: tip … :::) and toggles
  (::: toggle Question … :::) become MyNotion's own blocks. Anything else (pictures, coloured text, matrices, …)
  is shown to the model as a marker {{3}} that it has to keep, and is put back exactly as it was.

Nothing gets lost: before a reworked note is saved, the code checks that every word, formula and marker of the
original is still there ("organise"), or that only small changes were made ("fix the spelling"). If not, the model
gets one more try with what it left out; after that the part stays as it was. "Undo that" brings back the old
version, and while Aria works MyNotion locks the note ("Aria is editing…"), so your typing can't get lost either.
"""

import difflib
import html
import re
from collections import Counter
from html.parser import HTMLParser

from markdown_it import MarkdownIt

CHUNK_CHARS = 4500          # Markdown per model call: the original, its new version and a retry fit in 8,192 tokens
CONTEXT_CHARS = 3000        # how much of the note the model sees when it only writes a new part
CALLOUTS = ("note", "tip", "important", "warning")
BLOCK_TAGS = {"div", "details", "table", "img", "figure", "pre", "ul", "ol", "blockquote", "hr", "h1", "h2", "h3",
              "h4", "h5", "h6"}
VOID = {"br", "img", "hr", "input", "col", "wbr"}


# ── HTML -> a small tree ──────────────────────────────────────────────────────

class _Tree(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = {"tag": "root", "attrs": {}, "children": []}
        self.stack = [self.root]

    def handle_starttag(self, tag, attrs):
        node = {"tag": tag, "attrs": {k: (v if v is not None else "") for k, v in attrs}, "children": []}
        self.stack[-1]["children"].append(node)
        if tag not in VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.stack[-1]["children"].append(
            {"tag": tag, "attrs": {k: (v if v is not None else "") for k, v in attrs}, "children": []})

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i]["tag"] == tag:
                del self.stack[i:]
                return

    def handle_data(self, data):
        self.stack[-1]["children"].append(data)


def _parse(content: str) -> dict:
    t = _Tree()
    t.feed(content or "")
    t.close()
    return t.root


def _outer(node) -> str:
    """The node as HTML again (for the parts kept as they are)."""
    if isinstance(node, str):
        return html.escape(node, quote=False)
    attrs = "".join(f' {k}="{html.escape(v, quote=True)}"' for k, v in node["attrs"].items())
    if node["tag"] in VOID:
        return f"<{node['tag']}{attrs}>"
    return f"<{node['tag']}{attrs}>{''.join(_outer(c) for c in node['children'])}</{node['tag']}>"


def _text(node) -> str:
    if isinstance(node, str):
        return node
    return "".join(_text(c) for c in node["children"])


def _kids(node, *tags):
    return [c for c in node["children"] if isinstance(c, dict) and (not tags or c["tag"] in tags)]


# ── HTML -> Markdown ──────────────────────────────────────────────────────────

class _ToMarkdown:
    def __init__(self):
        self.keep = []          # HTML of the parts the model sees as {{n}}

    def marker(self, node) -> str:
        self.keep.append(_outer(node))
        return "{{" + str(len(self.keep) - 1) + "}}"

    # inline

    def inline(self, nodes, top=True) -> str:
        out = []
        for n in nodes:
            if isinstance(n, str):
                out.append(re.sub(r"([*`\\$])", r"\\\1", n.replace("\n", " ")))
                continue
            tag, a = n["tag"], n["attrs"]
            inner = lambda: self.inline(n["children"], top=False)
            if tag == "span" and a.get("data-type") == "inline-math":
                out.append(f"${a.get('data-latex', '').strip()}$")
            elif tag in ("strong", "b"):
                out.append(f"**{inner()}**")
            elif tag in ("em", "i"):
                out.append(f"*{inner()}*")
            elif tag in ("s", "del", "strike"):
                out.append(f"~~{inner()}~~")
            elif tag == "code":
                out.append("`" + _text(n).replace("`", "'") + "`")
            elif tag == "a" and a.get("href"):
                out.append(f"[{inner()}]({a['href'].replace(' ', '%20').replace(')', '%29')})")
            elif tag == "br":
                out.append("\\\n")
            elif tag in ("span", "label") and not a:
                out.append(inner())
            elif tag == "input":
                continue
            elif tag not in VOID and n["children"]:
                # coloured text, highlights, x²: the words stay readable between {{n}} and {{/n}}
                self.keep.append(_outer(n)[:_outer(n).find(">") + 1])
                i = len(self.keep) - 1
                out.append("{{" + str(i) + "}}" + inner() + "{{/" + str(i) + "}}")
            else:                                   # a picture in a line…
                out.append(self.marker(n))
        s = "".join(out)
        if not top:                                 # "wenn " inside a highlight keeps its space
            return s
        return re.sub(r"(?:\\\n\s*)+$", "", s).strip()   # a line break at the very end shows nothing

    @staticmethod
    def _line_start(text: str) -> str:
        """Text that would read as a heading/list/quote at the start of a line is escaped."""
        text = re.sub(r"^(\d+)([.)])(?=\s|$)", r"\1\\\2", text)          # "2)" -> "2\)": not a numbered list
        return re.sub(r"^(#|[-+*>](?=\s|$)|:::|=+\s*$)", r"\\\1", text)

    # blocks

    def blocks(self, nodes) -> list:
        out = []
        loose = []                                  # text and inline tags directly at block level

        def flush():
            if loose:
                t = self.inline(loose)
                if t:
                    out.append(self._line_start(t))
                loose.clear()

        for n in nodes:
            if isinstance(n, str) or n["tag"] not in BLOCK_TAGS | {"p"}:
                if isinstance(n, str) and not n.strip():
                    continue
                loose.append(n)
                continue
            flush()
            md = self.block(n)
            if md is not None and md.strip():
                out.append(md)
        flush()
        return out

    def block(self, n) -> str | None:
        tag, a = n["tag"], n["attrs"]
        if tag == "p":
            return self._line_start(self.inline(n["children"]))
        if re.fullmatch(r"h[1-6]", tag):
            return "#" * int(tag[1]) + " " + self.inline(n["children"])
        if tag in ("ul", "ol"):
            return self.list(n)
        if tag == "blockquote":
            inner = "\n\n".join(self.blocks(n["children"]))
            return "\n".join("> " + l if l else ">" for l in inner.split("\n"))
        if tag == "pre":
            code = _kids(n, "code")
            lang = re.sub(r"^language-", "", (code[0]["attrs"].get("class", "") if code else "")).split(" ")[0]
            body = _text(n).rstrip("\n")
            if "```" in body:
                return self.marker(n)
            return f"```{lang}\n{body}\n```"
        if tag == "hr":
            return "---"
        if tag == "div" and a.get("data-type") == "block-math":
            return f"$${a.get('data-latex', '').strip()}$$"
        if tag == "div" and a.get("data-type") == "callout":
            kind = a.get("data-kind", "note") if a.get("data-kind") in CALLOUTS else "note"
            return f"::: {kind}\n" + "\n\n".join(self.blocks(n["children"])) + "\n:::"
        if tag == "details":
            summary = _kids(n, "summary")
            content = [c for c in _kids(n) if c["tag"] != "summary"]
            title = self.inline(summary[0]["children"]) if summary else ""
            inner = []
            for c in content:
                inner += self.blocks(c["children"]) if c["tag"] == "div" else self.blocks([c])
            return f"::: toggle {title}".rstrip() + "\n" + "\n\n".join(inner) + "\n:::"
        if tag == "table":
            return self.table(n)
        return self.marker(n)

    def list(self, n) -> str:
        ordered = n["tag"] == "ol"
        tasks = n["attrs"].get("data-type") == "taskList"
        lines = []
        for i, li in enumerate(_kids(n, "li"), start=int(n["attrs"].get("start") or 1)):
            if tasks or li["attrs"].get("data-type") == "taskItem":
                mark = "- [x] " if li["attrs"].get("data-checked") == "true" else "- [ ] "
            else:
                mark = f"{i}. " if ordered else "- "
            body = [c for c in li["children"] if not (isinstance(c, dict) and c["tag"] == "label")]
            flat = []
            for c in body:                          # a task item keeps its text in a <div>
                if isinstance(c, dict) and c["tag"] == "div" and not c["attrs"]:
                    flat += c["children"]
                else:
                    flat.append(c)
            parts = self.blocks(flat) or [""]
            pad = " " * len(mark)
            lines.append(mark + parts[0].replace("\n", "\n" + pad))
            for p in parts[1:]:
                lines.append(pad + p.replace("\n", "\n" + pad))
        return "\n".join(lines)

    def table(self, n) -> str:
        rows = []
        for tr in _find_all(n, "tr"):
            cells = []
            for td in _kids(tr, "td", "th"):
                if len(_kids(td, "p")) > 1 or any(c["tag"] not in ("p",) for c in _kids(td)) \
                        or td["attrs"].get("colspan", "1") != "1" or td["attrs"].get("rowspan", "1") != "1":
                    return self.marker(n)           # cells with lists, several lines or merged cells: keep as is
                cells.append(self.inline(_kids(td, "p")[0]["children"] if _kids(td, "p") else td["children"])
                             .replace("|", "\\|"))
            rows.append(cells)
        if not rows or len({len(r) for r in rows}) != 1:
            return self.marker(n)
        line = lambda r: "| " + " | ".join(r) + " |"
        return "\n".join([line(rows[0]), line(["---"] * len(rows[0]))] + [line(r) for r in rows[1:]])


def _find_all(node, tag):
    out = []
    for c in _kids(node):
        if c["tag"] == tag:
            out.append(c)
        else:
            out += _find_all(c, tag)
    return out


def html_to_md(content: str) -> tuple[str, list]:
    """(Markdown, the HTML behind each {{n}} marker)."""
    conv = _ToMarkdown()
    md = "\n\n".join(conv.blocks(_parse(content)["children"]))
    return md.strip(), conv.keep


# ── Markdown -> HTML ──────────────────────────────────────────────────────────

# breaks: a single line break is one (the model writes line after line); html: raw HTML stays text
_MD = MarkdownIt("commonmark", {"html": False, "breaks": True}).enable(["table", "strikethrough"])
_CONTAINER = re.compile(r"^:{3,}\s*(note|tip|important|warning|toggle)\b[ \t]*(.*)$", re.I)
_CLOSE = re.compile(r"^:{3,}$")
_ALERT = re.compile(r"^>\s*\[!(note|tip|important|warning|caution)\][ \t]*(.*)$", re.I)


def _alerts_to_containers(lines: list) -> list:
    """GitHub's "> [!TIP]" boxes (small models like writing them) as ::: tip … :::"""
    out, i = [], 0
    while i < len(lines):
        m = _ALERT.match(lines[i])
        if not m:
            out.append(lines[i])
            i += 1
            continue
        kind = m.group(1).lower().replace("caution", "warning")
        out.append(f"::: {kind}")
        if m.group(2).strip():
            out.append(m.group(2).strip())
        i += 1
        while i < len(lines) and lines[i].startswith(">"):
            out.append(re.sub(r"^>\s?", "", lines[i]))
            i += 1
        out.append(":::")
    return out


def md_to_html(md: str, keep=()) -> str:
    """The editor's HTML for this Markdown; {{n}} markers become keep[n] again."""
    store = {"blocks": [], "formulas": []}
    body = _render((md or "").replace("\r\n", "\n").replace("\r", "\n"), store)
    return _restore(body, store, list(keep)) or "<p></p>"


def _render(md: str, store) -> str:
    lines = _alerts_to_containers(md.split("\n"))
    out, i, fence = [], 0, False
    while i < len(lines):
        line = lines[i]
        if line.lstrip().startswith("```"):
            fence = not fence
        m = None if fence else _CONTAINER.match(line.strip())
        if not m:
            out.append(line)
            i += 1
            continue
        depth, j, inner = 1, i + 1, []
        closed = any(_CLOSE.match(l.strip()) for l in lines[i + 1:])
        while j < len(lines):
            if not closed and not lines[j].strip():
                break                       # never closed: the box is just the lines right under it
            s = lines[j].strip()
            if _CONTAINER.match(s):
                depth += 1
            elif _CLOSE.match(s):
                depth -= 1
                if depth == 0:
                    break
            inner.append(lines[j])
            j += 1
        kind, title = m.group(1).lower(), m.group(2).strip()
        content = _render("\n".join(inner), store)
        if kind == "toggle":                # "1. Question?" followed by a toggle with the same question
            prev = next((k for k in range(len(out) - 1, -1, -1) if out[k].strip()), None)
            item = re.match(r"^\s*(?:\d+[.)]|[-*+])\s+(.*)$", out[prev]) if prev is not None else None
            if item and _same_words(item.group(1), title):
                del out[prev]
        if kind == "toggle":
            summary = _MD.renderInline(title) if title else ""
            block = (f'<details class="toggle"><summary>{summary}</summary>'
                     f'<div data-type="detailsContent">{content or "<p></p>"}</div></details>')
        else:
            if title:
                content = f"<p>{_MD.renderInline(title)}</p>" + content
            block = f'<div data-type="callout" data-kind="{kind}">{content or "<p></p>"}</div>'
        store["blocks"].append(block)
        out += ["", f"MNBLOCK{len(store['blocks']) - 1}X", ""]
        i = j + 1
    return _md_part("\n".join(out), store)


def _mathy(s: str) -> bool:
    """Is "$ … $" with spaces inside still a formula? ($ A $, $ \\pi r^2 $ yes; "$5 and $" no)"""
    return bool(re.search(r"[\\^_=]", s) or re.fullmatch(r"\d*[A-Za-z]{1,2}\d*'?", s))


_INLINE = re.compile(r"(^|[^\\$])\$([^$\n]+?)\$(?![\d$])")


def _inline_formulas(text: str, keep):
    """Replaces each $…$ in text by keep(latex): no space just inside the $ signs (so money isn't one), unless
    what's between them clearly is maths."""
    def one(m):
        inner = m.group(2)
        if inner != inner.strip() and not _mathy(inner.strip()):
            return m.group(0)
        if not inner.strip():
            return m.group(0)
        return m.group(1) + keep(inner.strip())
    return _INLINE.sub(one, text)


def _same_words(a, b) -> bool:
    w = lambda t: re.findall(r"[^\W_]+", t.lower())
    return w(a) == w(b)


def _md_part(md: str, store) -> str:
    def keep(latex, block):
        store["formulas"].append((latex.strip(), block))
        mark = f"MNFORMULA{len(store['formulas']) - 1}X"
        return f"\n\n{mark}\n\n" if block else mark

    # formulas first, so Markdown doesn't touch their _ * \ (code stays as it is)
    parts = re.split(r"(```[\s\S]*?```|`[^`\n]*`)", md)
    prepared = "".join(p if i % 2 else (
        _inline_formulas(
               re.sub(r"\\\(([^\n]+?)\\\)", lambda m: keep(m.group(1), False),
                      re.sub(r"\\\[([\s\S]+?)\\\]", lambda m: keep(m.group(1), True),
                             re.sub(r"\$\$([\s\S]+?)\$\$", lambda m: keep(m.group(1), True), p))),
               lambda latex: keep(latex, False)))
        for i, p in enumerate(parts))
    tokens = _MD.parse(prepared)
    _task_lists(tokens)
    return _MD.renderer.render(tokens, _MD.options, {})


def _task_lists(tokens):
    """"- [ ] x" lists: MyNotion's to-do lists."""
    box = re.compile(r"^\[([ xX])\]\s+")
    for k, t in enumerate(tokens):
        if t.type != "bullet_list_open":
            continue
        items, depth = [], 0
        for j in range(k + 1, len(tokens)):
            u = tokens[j]
            if u.type == "bullet_list_close" and u.level == t.level:
                break
            if u.type == "list_item_open" and u.level == t.level + 1:
                inline = next((tokens[x] for x in range(j + 1, len(tokens)) if tokens[x].type == "inline"), None)
                items.append((u, inline))
        if not items or not all(inl is not None and box.match(inl.content) for _, inl in items):
            continue
        t.attrSet("data-type", "taskList")
        for li, inline in items:
            checked = box.match(inline.content).group(1).lower() == "x"
            li.attrSet("data-type", "taskItem")
            li.attrSet("data-checked", "true" if checked else "false")
            inline.content = box.sub("", inline.content, count=1)
            if inline.children and inline.children[0].type == "text":
                inline.children[0].content = box.sub("", inline.children[0].content, count=1)


def _restore(body: str, store, keep: list) -> str:
    def formula(i, alone):
        latex, block = store["formulas"][i]
        q = html.escape(latex, quote=True)
        if block and alone:
            return f'<div data-type="block-math" data-latex="{q}"></div>'
        span = f'<span data-type="inline-math" data-latex="{q}"></span>'
        return f"<p>{span}</p>" if alone else span

    def kept(i, alone):
        if i >= len(keep):
            return "{{" + str(i) + "}}"
        piece = keep[i]
        tag = re.match(r"<(\w+)", piece)
        if alone and not (tag and tag.group(1) in BLOCK_TAGS):
            return f"<p>{piece}</p>"            # coloured text etc. on its own line: still a paragraph
        return piece

    def closing(i):
        tag = re.match(r"<(\w+)", keep[i]) if i < len(keep) else None
        return f"</{tag.group(1)}>" if tag else ""

    for _ in range(4):          # containers hold formulas and markers, and can be nested
        body = re.sub(r"<p>MNBLOCK(\d+)X</p>\n?", lambda m: store["blocks"][int(m.group(1))], body)
        body = re.sub(r"MNBLOCK(\d+)X", lambda m: store["blocks"][int(m.group(1))], body)
    body = re.sub(r"<p>MNFORMULA(\d+)X</p>\n?", lambda m: formula(int(m.group(1)), True), body)
    body = re.sub(r"MNFORMULA(\d+)X", lambda m: formula(int(m.group(1)), False), body)
    body = re.sub(r"<p>\{\{(\d+)\}\}</p>\n?", lambda m: kept(int(m.group(1)), True), body)
    body = re.sub(r"\{\{(\d+)\}\}", lambda m: kept(int(m.group(1)), False), body)
    body = re.sub(r"\{\{/(\d+)\}\}", lambda m: closing(int(m.group(1))), body)
    body = re.sub(r"<br\s*/?>\n?", "<br>", body)
    return re.sub(r">\n+(?=<)", ">", body).strip()


# ── was anything lost? ────────────────────────────────────────────────────────

_MARK = re.compile(r"\{\{(/?\d+)\}\}")


def _split_formulas(md: str):
    """(text without its formulas, [latex…])."""
    found = []

    def keep(latex):
        found.append(latex)
        return " "
    rest = re.sub(r"\$\$([\s\S]+?)\$\$", lambda m: keep(m.group(1)), md or "")
    rest = _inline_formulas(rest, keep)
    return rest, found


def _words(text):
    """Words; numbers like 5.2 / 31,9 / 4.8a stay whole (so exercise "5.2)" can't be made up by other 5s and 2s)."""
    return [w.lower() for w in re.findall(r"\d+(?:[.,]\d+)*[^\W_]*|[^\W_]+", text)]


def facts(md: str, keep=None) -> dict:
    """What a note is made of: its words (in order), formulas, markers, boxes. With `keep` (the HTML behind the
    markers) a marker counts as what it stands for, so two versions with different numbering can be compared."""
    rest, found = _split_formulas(md)
    formulas = Counter(re.sub(r"\s+", "", f) for f in found)
    name = (lambda n: n) if keep is None else (lambda n: ("/" if n.startswith("/") else "") +
                                              (keep[int(n.lstrip("/"))] if int(n.lstrip("/")) < len(keep) else n))
    marks = Counter(name(n) for n in _MARK.findall(rest))
    # a highlight has to stay on the same words; boxes and toggles have to stay (a toggle with its question)
    wrapped = Counter("{{" + name(n) + "}}" + " ".join(_words(_MARK.sub(" ", inner)))
                      for n, inner in re.findall(r"\{\{(\d+)\}\}(.*?)\{\{/\1\}\}", md or "", flags=re.S))
    boxes = Counter(re.sub(r"\s+", " ", m.group(1).lower() + " " + " ".join(_words(m.group(2)))).strip()
                    for m in (_CONTAINER.match(l.strip()) for l in (md or "").split("\n")) if m)
    boxes["line"] = len(re.findall(r"(?m)^---\s*$", md or ""))        # a dividing line
    boxes = +boxes
    rest = _MARK.sub(" ", rest)
    rest = re.sub(r"\]\([^)]*\)", "] ", rest)                                   # link addresses aren't words
    rest = re.sub(r"(?m)^\s*:{3,}\s*(?:note|tip|important|warning|toggle)?", " ", rest)   # box syntax
    rest = re.sub(r"(?m)^(\s*(?:[-*+]|\d+[.)]))\s+\[[ xX]\]", r"\1", rest)            # to-do boxes
    seq = _words(rest)
    # the words a formula spells out: "6CO2" may have become $6CO_2$
    in_formulas = set(_words(re.sub(r"\\[A-Za-z]+|[_^{}]", "", " ".join(found))))
    return {"words": Counter(seq), "seq": seq, "formulas": formulas, "marks": marks + wrapped, "boxes": boxes,
            "in_formulas": in_formulas}


def missing(old_md: str, new_md: str, old_keep=None, new_keep=None) -> dict:
    """What the new version left out: {"words": [...], "formulas": [...], "marks": [...]} (empty lists if nothing).
    Not counted as lost: two words written as one ("licht energie" -> "Lichtenergie"), and text that became a
    formula ("6CO2" -> $6CO_2$)."""
    a, b = facts(old_md, old_keep), facts(new_md, new_keep)
    lost_words = a["words"] - b["words"]
    if lost_words:
        extra = b["words"] - a["words"]
        seq = a["seq"]
        for x, y in zip(seq, seq[1:]):
            if lost_words[x] and lost_words[y] and extra[x + y]:
                lost_words[x] -= 1
                lost_words[y] -= 1
                extra[x + y] -= 1
        for w in list(lost_words):
            if w in b["in_formulas"]:
                del lost_words[w]
    lost = lambda k: sorted((a[k] - b[k]).elements())
    return {"words": sorted((+lost_words).elements()), "formulas": lost("formulas"), "marks": lost("marks"),
            "boxes": lost("boxes")}


def nothing_missing(gap: dict) -> bool:
    return not any(gap.values())


def describe(gap: dict, n=12) -> str:
    bits = []
    if gap["words"]:
        bits.append("these words: " + ", ".join(dict.fromkeys(gap["words"]))[:400])
    if gap["formulas"]:
        bits.append("these formulas: " + ", ".join(f"${f}$" for f in gap["formulas"][:n]))
    if gap["marks"]:
        bits.append("these markers, each around the same words as before: "
                    + ", ".join(m if m.startswith("{") else "{{" + m + "}}" for m in gap["marks"][:n]))
    if gap["boxes"]:
        bits.append("these ::: boxes/toggles: " + ", ".join(gap["boxes"][:n]))
    return "; ".join(bits)


def _markers(md):
    """Just which {{n}} / {{/n}} markers there are (for changes that may change the words inside them)."""
    return Counter(_MARK.findall(md or ""))


def small_changes(old_md: str, new_md: str) -> tuple[bool, int]:
    """(only small corrections?, how many words changed) — for "fix the spelling"."""
    a, b = re.findall(r"\S+", old_md), re.findall(r"\S+", new_md)
    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
    changed = sum(max(i2 - i1, j2 - j1) for op, i1, i2, j1, j2 in sm.get_opcodes() if op != "equal")
    fa, fb = facts(old_md), facts(new_md)
    same_parts = fa["formulas"] == fb["formulas"] and _markers(old_md) == _markers(new_md)
    return same_parts and sm.ratio() >= 0.8, changed


# ── splitting long notes ──────────────────────────────────────────────────────

_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")


def blocks_of(md: str) -> list:
    """The note's top-level blocks (paragraphs, lists, tables, ::: boxes, code), in order."""
    out, cur, depth, fence = [], [], 0, False
    for line in md.split("\n"):
        s = line.strip()
        if s.startswith("```"):
            fence = not fence
        elif not fence:
            if _CONTAINER.match(s):
                depth += 1
            elif _CLOSE.match(s) and depth:
                depth -= 1
        if not s and not depth and not fence:
            if cur:
                out.append("\n".join(cur))
                cur = []
            continue
        cur.append(line)
    if cur:
        out.append("\n".join(cur))
    return out


def chunks(md: str, size=CHUNK_CHARS) -> list:
    """Parts of at most `size` characters, cut before headings where possible (a block bigger than that is one
    part on its own)."""
    out, cur = [], []
    for b in blocks_of(md):
        length = sum(len(x) + 2 for x in cur)
        new_section = bool(_HEADING.match(b.split("\n")[0])) and length > size * 0.5
        if cur and (length + len(b) > size or new_section):
            out.append("\n\n".join(cur))
            cur = []
        cur.append(b)
    if cur:
        out.append("\n\n".join(cur))
    return out


def sections(md: str) -> list:
    """[(heading text or "", level, list of blocks)]: the part before the first heading, then each heading's part
    (up to the next heading of the same or a higher level)."""
    out = [["", 0, []]]
    for b in blocks_of(md):
        m = _HEADING.match(b.split("\n")[0])
        if m:
            out.append([m.group(2).strip(), len(m.group(1)), [b]])
        else:
            out[-1][2].append(b)
    return [tuple(s) for s in out if s[2] or s[0]]


def strip_fence(text: str) -> str:
    """The model's reply without a ```markdown … ``` wrapper, an empty <think></think>, the <<< >>> it was given the
    note in, or spaces at line ends."""
    t = re.sub(r"<think>[\s\S]*?</think>", "", text or "").strip()
    m = re.fullmatch(r"```(?:markdown|md)?\s*\n([\s\S]*?)\n?```", t)
    t = (m.group(1) if m else t).strip()
    t = re.sub(r"^<<<[ \t]*\n|\n?[ \t]*>>>$", "", t).strip()
    return "\n".join(l.rstrip() for l in t.split("\n"))


# ── the model's jobs ──────────────────────────────────────────────────────────

FORMAT_HELP = """Format (Markdown):
- "## " headings for sections, short paragraphs, "- " bullet lists, "1. " numbered steps
- tables (| a | b |) for comparisons or data in rows
- formulas in LaTeX: $x^2$ inside a line (no spaces just inside the $ signs), $$…$$ on a line of their own
- "- [ ] " for things to do
- a box for a key point (tip, note, important or warning):
::: tip
The key point.
:::
- a question with a hidden answer, good for self-testing:
::: toggle What is the area of a circle with r = 5 cm?
$A = 25\\pi \\approx 78.5$ cm²
:::
Boxes and toggles start at the beginning of a line, never inside a list."""

KEEP_RULES = """- Keep every formula ($…$, $$…$$) exactly as it is, character for character.
- Keep every marker like {{3}} or {{/3}} exactly, around the same words (they are pictures and highlights)."""


class NoteWriter:
    """write_note / organize_note / edit_note. `ask(prompt) -> text` is the chat model (replaced in tests)."""

    def __init__(self, notion, model=None, ask=None):
        self.notion = notion
        self.model = model
        self.ask = ask or self._ollama

    def _ollama(self, prompt, history=(), temperature=0.3):
        import ollama
        from llm_engine import KEEP_ALIVE, LLM_MODEL_DEFAULT, chat_options
        messages = list(history) + [{"role": "user", "content": prompt}]
        resp = ollama.chat(model=self.model or LLM_MODEL_DEFAULT, messages=messages, think=False,
                           options=chat_options(temperature=temperature), keep_alive=KEEP_ALIVE)
        return resp["message"]["content"]

    def _md(self, prompt, history=(), temperature=0.3) -> str:
        return strip_fence(self.ask(prompt, history=history, temperature=temperature))

    # ── which note ──

    def _note(self, title):
        n = self.notion.resolve_note(title)
        if n:
            return n, ""
        if self.notion.is_this(title):
            return None, "Which note? I can't see one open in MyNotion — say its name."
        return None, f"I couldn't find a note called '{title}'. " + self.notion._titles_hint()

    def _save(self, note, old_html, new_md, keep, done: str) -> str:
        new_html = md_to_html(new_md, keep)
        if not self.notion.replace_content(note["id"], old_html, new_html):
            return (f"'{note['title']}' was changed in MyNotion while I was working, so I didn't overwrite it. "
                    "Ask me again and I'll start from the new version.")
        return done

    # ── write a new note ──

    def write_note(self, title: str, about: str, language: str = "", from_last_answer: bool = False):
        title = (title or "").strip()
        about = (about or "").strip()
        source = (self.notion.last_reply() or "").strip() if from_last_answer else ""
        if not about and not source:
            return "What should the note be about?"
        lang = f"Write it in {language}." if language else \
            "Write it in the language of the request (English unless it is clearly in another language)."
        if source:
            task = (f"Turn this answer into a well organised note titled \"{title}\""
                    + (f" ({about})" if about else "") + f". Keep all its facts.\n\nAnswer:\n<<<\n{source}\n>>>")
        else:
            task = f"Write a note titled \"{title}\" about: {about}"
        prompt = f"""{task}

It's for a student, so make it clear and easy to learn from. {lang}
{FORMAT_HELP}
Use the parts that fit; don't force every kind in. Facts must be correct — leave out what you're not sure about.
Don't repeat the title as a heading at the top. Usually 150–400 words, unless the request asks for more or less.
Reply with the Markdown only."""
        md = self._md(prompt, temperature=0.5)
        md = re.sub(rf"^#+\s*{re.escape(title)}\s*\n+", "", md, flags=re.I) if title else md
        if not md.strip():
            return "I couldn't write that note just now — try again in a moment."
        words = len(re.findall(r"[^\W_]+", md))
        existing = self.notion.resolve_note(title) if title else None
        if existing and (self.notion.is_this(title) or self.notion.title_score(title, existing["title"]) >= 80):
            with self.notion.editing(existing["id"]):
                fresh = self.notion._note_by_id(existing["id"])
                old_md, keep = html_to_md(fresh["content"] or "")
                return self._save(fresh, fresh["content"], (old_md + "\n\n" + md).strip(), keep,
                                  f"Added about {words} words to '{fresh['title']}'.")
        name = title or (about[:40].strip().capitalize() if about else "Note from Aria")
        self.notion._create_note(name, md_to_html(md))
        return f"Wrote the note '{name}' in MyNotion (about {words} words). Say 'open it' to see it."

    # ── organise ──

    def organize_note(self, title: str = "this"):
        note, err = self._note(title)
        if err:
            return err
        with self.notion.editing(note["id"]):
            note = self.notion._note_by_id(note["id"])
            md, keep = html_to_md(note["content"] or "")
            if len(facts(md)["words"]) < 8:
                return f"'{note['title']}' is too short to organise."
            parts, kept_as_is = [], []
            for i, part in enumerate(chunks(md)):
                new = self._organize_part(note["title"], part, keep)
                if new is None:
                    parts.append(part)
                    kept_as_is.append(_part_name(part, i))
                else:
                    parts.append(new)
            if len(kept_as_is) == len(parts):
                return (f"I couldn't reorganise '{note['title']}' without leaving something out, so I left it "
                        "as it was.")
            new_md = "\n\n".join(parts)
            saved_md, saved_keep = html_to_md(md_to_html(new_md, keep))     # exactly what MyNotion will get
            if not nothing_missing(missing(md, saved_md, keep, saved_keep)):  # never save one with something missing
                return f"Something went wrong while organising '{note['title']}', so I left it as it was."
            done = f"Organised '{note['title']}'."
            if kept_as_is:
                done += f" I left {', '.join(kept_as_is)} as it was, because I couldn't do it without losing something."
            return self._save(note, note["content"], new_md, keep, done + " Say 'undo that' to get the old version back.")

    def _organize_part(self, title, part, keep=None):
        prompt = f"""Tidy up this part of a student's note titled "{title}" so it's easier to learn from:
- put lines that belong together next to each other, in a sensible order
- add a few short "## " headings (1 to 4 words, a topic name) above groups of lines
- turn loose lines into bullet lists, steps into numbered lists, things to do into "- [ ] " to-dos, data in rows into a table
- you may put a line that is already there and important into a "::: important" box
Rules (very important):
- Keep EVERY word of the original. Don't shorten, reword, translate, explain or add sentences. Only move, group and format.
- Leave each line's words as they are: don't fix spelling or capitals, don't turn written-out formulas into LaTeX.
- Never turn a sentence of the note into a heading; headings are new, short topic names.
{KEEP_RULES}
- Headings you add are in the same language as the note.
Reply with the reorganised Markdown only.

{FORMAT_HELP}

The note:
<<<
{part}
>>>"""
        new = self._md(prompt)
        problems = _organize_problems(part, new, keep)
        if not problems:
            return new
        retry = f"{problems} Fix that, keep everything else, and reply with the whole Markdown again."
        new = self._md(retry, history=[{"role": "user", "content": prompt}, {"role": "assistant", "content": new}],
                       temperature=0.2)
        return None if _organize_problems(part, new, keep) else new

    # ── change part of a note ──

    def edit_note(self, title: str = "this", change: str = "add", instruction: str = "", section: str = "",
                  language: str = ""):
        note, err = self._note(title)
        if err:
            return err
        change = (change or "add").lower().replace(" ", "_")
        jobs = {"add": self._add, "summary": self._summary, "fix_spelling": self._fix_spelling,
                "translate": self._translate, "rewrite": self._rewrite}
        job = jobs.get(change)
        if not job:
            return f"I can add, summary, fix_spelling, translate or rewrite — not '{change}'."
        with self.notion.editing(note["id"]):
            note = self.notion._note_by_id(note["id"])
            md, keep = html_to_md(note["content"] or "")
            return job(note, md, keep, instruction=(instruction or "").strip(), section=(section or "").strip(),
                       language=(language or "").strip())

    def _context(self, md):
        return md if len(md) <= CONTEXT_CHARS else md[:CONTEXT_CHARS] + "\n…"

    def _add(self, note, md, keep, instruction, section, language):
        if not instruction:
            return "What should I add?"
        prompt = f"""A student's note titled "{note['title']}" is below. Write ONLY the new part they asked for:
"{instruction}"
Match the note's language and style. Don't repeat what's already in the note. Facts must be correct.
{FORMAT_HELP}
Reply with the new Markdown only.

The note so far:
<<<
{self._context(md)}
>>>"""
        new = self._md(prompt, temperature=0.5)
        if not new.strip():
            return "I couldn't write that part just now — try again in a moment."
        secs = sections(md)
        where = _find_section(secs, section)
        at_top = re.search(r"\b(top|start|beginning|anfang|oben)\b", instruction, re.I)
        if where is not None:
            blocks = [b for s in secs[:where + 1] for b in s[2]] + [new] + [b for s in secs[where + 1:] for b in s[2]]
            new_md = "\n\n".join(blocks)
            spot = f"after the '{secs[where][0]}' part"
        elif at_top:
            new_md, spot = new + "\n\n" + md, "at the top"
        else:
            new_md, spot = (md + "\n\n" + new).strip(), "at the end"
        return self._save(note, note["content"], new_md, keep, f"Added it to '{note['title']}', {spot}.")

    def _summary(self, note, md, keep, instruction, section, language):
        body = _drop_summary(md)
        if len(facts(body)["words"]) < 30:
            return f"'{note['title']}' is too short for a summary."
        prompt = f"""Summarise this student's note titled "{note['title']}" in 3 to 6 short bullet points: the main ideas
someone should remember. {f'Also: {instruction}.' if instruction else ''}
Write in the note's language. Use $…$ for formulas. Only what's in the note.
Start with one line that is just the word "Summary" in the note's language, in bold (e.g. **Summary** or **Zusammenfassung**).
Reply with the Markdown only.

The note:
<<<
{body if len(body) <= CHUNK_CHARS else body[:CHUNK_CHARS] + "…"}
>>>"""
        summary = self._md(prompt)
        if not summary.strip():
            return "I couldn't write a summary just now — try again in a moment."
        if not summary.lstrip().startswith("**"):
            summary = "**Summary**\n\n" + summary
        new_md = f"::: note\n{summary.strip()}\n:::\n\n{body}"
        replaced = body != md
        return self._save(note, note["content"], new_md, keep,
                          f"{'Updated the' if replaced else 'Put a'} summary at the top of '{note['title']}'.")

    def _fix_spelling(self, note, md, keep, instruction, section, language):
        parts, changed, skipped = [], 0, 0
        for part in chunks(md):
            prompt = f"""Correct the spelling, grammar and punctuation mistakes in this part of a student's note.
Only fix real mistakes. Don't reword, reorder, translate or add anything; keep the formatting.
{KEEP_RULES}
If there are no mistakes, reply with it unchanged. Reply with the Markdown only.

<<<
{part}
>>>"""
            new = self._md(prompt, temperature=0.1)
            ok, n = small_changes(part, new)
            if ok:
                parts.append(new)
                changed += n
            else:
                parts.append(part)
                skipped += 1
        if not changed:
            return (f"I found no mistakes in '{note['title']}'." if not skipped else
                    f"I couldn't correct '{note['title']}' without changing too much, so I left it as it was.")
        msg = f"Fixed {changed} word{'s' if changed != 1 else ''} in '{note['title']}'."
        if skipped:
            msg += " I left a part as it was, because the corrections changed too much."
        return self._save(note, note["content"], "\n\n".join(parts), keep, msg + " Say 'undo that' to see the old version.")

    def _translate(self, note, md, keep, instruction, section, language):
        if not language:
            return "Into which language?"
        parts = []
        for i, part in enumerate(chunks(md)):
            prompt = f"""Translate this part of a student's note into {language}. Translate everything, keep the formatting.
{KEEP_RULES}
Reply with the translated Markdown only.

<<<
{part}
>>>"""
            new = self._md(prompt, temperature=0.2)
            a, b = facts(part), facts(new)
            if a["formulas"] != b["formulas"] or _markers(part) != _markers(new) \
                    or sum(b["words"].values()) < 0.5 * sum(a["words"].values()):
                return (f"The translation of '{note['title']}' lost some parts, so I didn't change the note. "
                        "Try again, or tell me a shorter part to translate.")
            parts.append(new)
        return self._save(note, note["content"], "\n\n".join(parts), keep,
                          f"Translated '{note['title']}' into {language}. Say 'undo that' to get the original back.")

    def _rewrite(self, note, md, keep, instruction, section, language):
        if not instruction:
            return "How should I change it?"
        secs = sections(md)
        where = _find_section(secs, section)
        if section and where is None:
            heads = [s[0] for s in secs if s[0]]
            return f"I couldn't find a part called '{section}' in '{note['title']}'." + \
                (f" Its parts: {', '.join(heads[:10])}." if heads else "")
        part = "\n\n".join(secs[where][2]) if where is not None else md
        if len(part) > CHUNK_CHARS:
            return f"That's too long to rewrite in one go — name one part of '{note['title']}' (a heading)."
        prompt = f"""Change this part of a student's note titled "{note['title']}" like this: "{instruction}".
Change only what that asks for. Keep the language. Keep anything the request doesn't touch.
Your reply REPLACES this part completely, so never keep the old lines next to their new version.
{KEEP_RULES}
{FORMAT_HELP}
Reply with the new Markdown for this part only.

<<<
{part}
>>>"""
        new = self._md(prompt, temperature=0.3)
        twice = _duplicated(part, new)
        if twice:
            new = self._md(f"Your version has these lines twice (the old and the new way): {'; '.join(twice[:3])}. "
                           "Keep only the new way and reply with the whole part again.",
                           history=[{"role": "user", "content": prompt}, {"role": "assistant", "content": new}],
                           temperature=0.2)
            if _duplicated(part, new):
                return "My version repeated parts of the note, so I left it as it was. Try saying it differently."
        if not new.strip():
            return "I couldn't change it just now — try again in a moment."
        lost = _markers(part) - _markers(new)
        if lost:
            return "That would have removed a picture or highlight, so I left it as it was."
        if where is None:
            new_md = new
        else:
            new_md = "\n\n".join([b for s in secs[:where] for b in s[2]] + [new] + [b for s in secs[where + 1:] for b in s[2]])
        what = f"the '{secs[where][0] or 'first'}' part of " if where is not None else ""
        return self._save(note, note["content"], new_md, keep,
                          f"Changed {what}'{note['title']}'. Say 'undo that' to get the old version back.")


    # ── a selection from MyNotion ("Select text, ask Aria") ──

    REWORKS = {
        "rewrite": "Improve the wording of this part: clearer and smoother, with the same meaning, the same facts "
                   "and about the same length.",
        "shorter": "Make this part clearly shorter: keep the meaning and the key facts, drop repetition and filler.",
        "spelling": "Correct the spelling, grammar and punctuation mistakes in this part. Only fix real mistakes. "
                    "Don't reword, reorder, translate or add anything; keep the formatting. If there are no "
                    "mistakes, reply with it unchanged.",
        "table": "Turn this part into a Markdown table (| a | b |) with short column headings. Keep every word "
                 "and number of it.",
    }

    def rework(self, html: str, action: str, instruction: str = "", title: str = "", context: str = "",
               previous: str = ""):
        """A new version of the text selected in MyNotion: (its HTML, "") or (None, why not). Nothing is saved:
        MyNotion shows the version and puts it into the note only if it is accepted. The same checks as for whole
        notes apply (pictures, highlights and formulas stay), with one more try if the first version fails them."""
        instruction = (instruction or "").strip()
        if action not in self.REWORKS and action != "custom":
            return None, "I don't know that kind of change."
        if action == "custom" and not instruction:
            return None, "How should I change it?"
        md, keep = html_to_md(html or "")
        if not md.strip():
            return None, "There's no text in what you selected."
        if len(md) > CHUNK_CHARS:
            return None, "That's too much at once. Select a smaller part."
        task = self.REWORKS.get(action) or (f'Change this part like this: "{instruction}". Change only what that '
                                           "asks for and keep anything it doesn't touch.")
        if action != "custom" and instruction:
            task += f' Also: "{instruction}".'
        prompt = f"""{task}
This is a part of a student's note{f' titled "{title.strip()}"' if (title or "").strip() else ""}. Keep its language.
Your reply REPLACES this part completely, so never keep the old lines next to their new version.
{KEEP_RULES}
{FORMAT_HELP if action in ("custom", "table") else "Keep the formatting (Markdown)."}
Reply with the new Markdown for this part only, nothing before or after it."""
        if (context or "").strip():
            prompt += ("\n\nFor context only, the text around this part (don't repeat it in your reply):\n"
                       f"<<<\n{context.strip()[:2000]}\n>>>")
        again = html_to_md(previous)[0].strip() if previous else ""
        if again:
            prompt += f"\n\nAn earlier version was this. Write a clearly different one:\n<<<\n{again}\n>>>"
        prompt += f"\n\nThe part:\n<<<\n{md}\n>>>"
        temperature = 0.6 if again else 0.1 if action == "spelling" else 0.3

        check = lambda version: _rework_problem(action, md, version, keep, instruction, again)
        new = self._md(prompt, temperature=temperature)
        problem = check(new)
        if problem and problem[1]:
            new = self._md(f"That doesn't work: {problem[1]} Reply with the whole part again.",
                           history=[{"role": "user", "content": prompt}, {"role": "assistant", "content": new}],
                           temperature=max(temperature, 0.2))
            problem = check(new)
        if problem:
            return None, problem[0]
        return md_to_html(new, keep), ""


def _rework_problem(action, old, new, keep, instruction="", previous=""):
    """Why this version of a selection can't be offered: (what to tell the user, what to tell the model for one
    more try — empty if another try is pointless), or None if it is fine."""
    count = lambda md: sum(facts(md)["words"].values())
    same = " ".join(new.split()) == " ".join(old.split())
    if not new.strip():
        return "I couldn't come up with a version just now. Try again.", "Your reply was empty."
    if action == "spelling":
        ok, changed = small_changes(old, new)
        if same or (ok and not changed):
            return "I found no mistakes in that part.", ""
        if not ok:
            return ("I couldn't correct that without changing too much, so I left it.",
                    "You changed too much. Fix only spelling, grammar and punctuation mistakes; keep every formula "
                    "and {{n}} marker.")
        return None
    if same:
        return "I couldn't find a different way to write that.", "That is the same text as before."
    flat = lambda t: " ".join(_words(t))
    if previous and flat(new) == flat(previous):
        return ("I couldn't find a different version this time.",
                "That is the same as the earlier version. Write a clearly different one.")
    if instruction and len(flat(instruction).split()) >= 2 and flat(instruction) in flat(new) \
            and flat(instruction) not in flat(old):
        # "second item stays / translate into German": the request written into the text instead of carried out
        return ("My version repeated your instruction instead of following it, so I left it.",
                f'You wrote the instruction ("{instruction}") into the text. Carry it out instead: reply only '
                "with the changed part.")
    if _markers(old) - _markers(new):
        return ("That would have removed a picture or highlight, so I left it.",
                "A {{n}} marker is missing. Keep every marker around the same words.")
    if action != "custom" and (facts(old)["formulas"] - facts(new)["formulas"]):
        return ("That would have dropped a formula, so I left it.",
                "A formula is missing. Keep every $…$ formula exactly as it was.")
    if action == "table":
        if "<table" not in md_to_html(new, keep):
            return "I couldn't turn that into a table.", "That is not a Markdown table (| a | b | with a |---| line)."
        gap = missing(old, new, keep, keep)
        if not nothing_missing(gap):
            return (f"The table would have left out {describe(gap)}, so I left it.",
                    f"The table leaves out {describe(gap)}. Keep everything.")
        return None
    if _duplicated(old, new):
        return ("My version repeated parts of the text, so I left it.",
                "You kept old lines next to their new version. Keep only the new way.")
    if action == "shorter" and count(new) >= count(old):
        return "I couldn't make that shorter.", "That is not shorter than before. Make it clearly shorter."
    if action == "rewrite" and count(new) > 1.5 * count(old) + 5:
        return ("My version got much longer instead of clearer, so I left it.",
                "That is much longer than before (did you keep the old text next to the new?). Keep about the "
                "same length.")
    return None


def _headings(md):
    return [m.group(2).strip() for m in (_HEADING.match(l) for l in md.split("\n")) if m]


def _organize_problems(old, new, keep=None) -> str:
    """What's wrong with an organised version ("" if nothing): something left out, or sentences made headings."""
    gap = missing(old, new)
    if not nothing_missing(gap):
        return f"Your version left out {describe(gap)}. Put them back where they belong."
    opens = sum(1 for l in new.split("\n") if _CONTAINER.match(l.strip()))
    closes = sum(1 for l in new.split("\n") if _CLOSE.match(l.strip()))
    if opens != closes:
        return ("Every ::: box or toggle must end with its own line \":::\" — yours has "
                f"{opens} starting and {closes} ending lines. Close each box right after its text.")
    before = {h.lower() for h in _headings(old)}
    long_ = [h for h in _headings(new) if h.lower() not in before and len(_words(h)) > 5]
    if long_:
        return (f"You turned sentences into headings ({'; '.join(long_[:3])}). Headings must be short topic names "
                "(1 to 4 words); the sentences go back to being normal lines under them.")
    new_heads = [h for h in _headings(new) if h.lower() not in before]
    lines = len([b for b in blocks_of(old)])
    if len(new_heads) > max(3, lines // 2):
        return "You added too many headings. Use only a few, each above a group of related lines."
    if keep is not None:            # as it will be saved: boxes that swallow lines, markers moved…
        a_md, a_keep = html_to_md(md_to_html(old, keep))
        b_md, b_keep = html_to_md(md_to_html(new, keep))
        gap = missing(a_md, b_md, a_keep, b_keep)
        if not nothing_missing(gap):
            return f"Your version breaks the note's layout: it loses {describe(gap)}."
    return ""


def _lines(md):
    """The note's lines and list items as plain words (for comparing), only the ones with a few words."""
    out = []
    for l in md.split("\n"):
        w = " ".join(_words(re.sub(r"^\s*(?:#+|[-*+]|\d+[.)]|>)\s*(?:\[[ xX]\]\s*)?", "", l)))
        if len(w.split()) >= 4:
            out.append(w)
    return out


def _duplicated(old, new) -> list:
    """Lines that appear more often in the new version than in the old one (the old and the new way, both kept)."""
    before, after = Counter(_lines(old)), Counter(_lines(new))
    return [l for l, n in after.items() if n > max(1, before[l])]


def _part_name(part, i):
    m = _HEADING.match(part.split("\n")[0])
    return f"the '{m.group(2).strip()}' part" if m else f"part {i + 1}"


def _find_section(secs, name):
    """The index of the section whose heading matches `name` best (None if no name or no match)."""
    if not name:
        return None
    from Engines.NotionEngine import _match_score
    scored = [(_match_score(name, s[0]), i) for i, s in enumerate(secs) if s[0]]
    best = max(scored, default=(0, None))
    return best[1] if best[0] >= 40 else None


def _drop_summary(md):
    """The note without the summary box Aria put at its top earlier (so a new one replaces it)."""
    blocks = blocks_of(md)
    if blocks and re.match(r"^:::\s*note\s*\n\*\*(summary|zusammenfassung|résumé|resumen|riassunto|samenvatting|"
                           r"özet|podsumowanie)\*\*", blocks[0], re.I):
        return "\n\n".join(blocks[1:])
    return md
