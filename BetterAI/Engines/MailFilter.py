"""Hides what slipped into Gmail's Primary tab but looks like a newsletter or an ad. A port of MyNotion's
note/src/mail/filter.ts: both run filter-cases.json (tests/test_mail_filter.py), so keep them in step."""
import re

NO_REPLY = re.compile(r"^(no-?reply|do-?not-?reply|newsletter|marketing|promo(tions?)?|news|deals|offers)@", re.I)


def filter_reason(headers: dict, sender: str, always_show: set) -> str | None:
    """headers: lower-case names. None = show it; otherwise why it's hidden."""
    sender = (sender or "").strip().lower()
    if sender in {a.lower() for a in always_show}:
        return None
    if headers.get("list-unsubscribe") or headers.get("list-id"):
        return "newsletter"
    if re.fullmatch(r"(bulk|list|junk)", (headers.get("precedence") or "").strip(), re.I):
        return "bulk"
    if NO_REPLY.search(sender):
        return "no-reply sender"
    return None
