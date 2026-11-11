import json
from pathlib import Path

from app.retrieval import can_access, search_json

DOCS = json.loads((Path(__file__).resolve().parent.parent / "data" / "docs.json").read_text(encoding="utf-8"))
BOSS = ["all", "fin", "hr", "prod", "mkt", "support", "legal"]
PROD = ["all", "prod"]


def test_boss_sees_finance_doc():
    found = search_json("финплан 2027", DOCS, BOSS)
    assert any(d["id"] == "D-12" for d in found)


def test_employee_does_not_see_finance_doc():
    found = search_json("финплан 2027", DOCS, PROD)
    assert not any(d["id"] == "D-12" for d in found)


def test_employee_sees_production_doc():
    found = search_json("загрузка мощностей неделя 48", DOCS, PROD)
    assert any(d["id"] == "D-15" for d in found)


def test_legal_doc_is_not_visible_to_production():
    doc = next(d for d in DOCS if d["id"] == "D-05")
    assert can_access(doc, BOSS)
    assert not can_access(doc, PROD)
