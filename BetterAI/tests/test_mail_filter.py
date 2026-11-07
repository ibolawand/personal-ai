"""Aria's copy of MyNotion's junk filter must agree with it: both run MyNotion's shared cases."""
import json
import re
from pathlib import Path

import pytest

from Engines.MailFilter import filter_reason

MAIL_DIR = Path(__file__).resolve().parents[3] / "MyNotion" / "note" / "src" / "mail"
CASES = MAIL_DIR / "filter-cases.json"


@pytest.mark.skipif(not CASES.exists(), reason="MyNotion isn't next to personal-ai")
@pytest.mark.parametrize("case", json.loads(CASES.read_text()) if CASES.exists() else [], ids=lambda c: c["name"])
def test_shared_cases(case):
    assert filter_reason(case["headers"], case["from"], set(case.get("alwaysShow", []))) == case["expect"]


@pytest.mark.skipif(not (MAIL_DIR / "schema.ts").exists(), reason="MyNotion isn't next to personal-ai")
def test_same_tables_as_mynotion():
    from Engines.MailEngine import MAIL_SCHEMA
    ts = re.search(r"`(.*)`", (MAIL_DIR / "schema.ts").read_text(), re.S).group(1)
    norm = lambda s: " ".join(s.split())
    assert norm(MAIL_SCHEMA) == norm(ts)
