import asyncio

import pytest

from app import llm
from app.llm import LLMError, validate_and_restore
from app.pii import PIIMasker


def test_llm_tags_are_restored():
    masker = PIIMasker()
    masker.mask("Позвони Ивану Иванову на +375291112233")
    restored = validate_and_restore("Напомнить ⟦PERSON_1⟧ на ⟦PHONE_1⟧", masker)
    assert restored == "Напомнить Ивану Иванову на +375291112233"


def test_llm_unknown_tag_is_rejected():
    masker = PIIMasker()
    masker.mask("Позвони Ивану Иванову")
    with pytest.raises(LLMError):
        validate_and_restore("Напомнить ⟦PERSON_7⟧", masker)


def test_deepseek_receives_only_masked_text(monkeypatch):
    captured = {}

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": "Позвонить ⟦PERSON_1⟧ по доставке."}}]}

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, url, json, headers):
            captured["url"] = url
            captured["json"] = json
            captured["headers"] = headers
            return FakeResponse()

    monkeypatch.setattr(llm.settings, "deepseek_api_key", "test-key")
    monkeypatch.setattr(llm.httpx, "AsyncClient", FakeClient)

    masker = PIIMasker()
    question = masker.mask("Позвонить Ивану Иванову на +375291112233?")
    docs = [{"id": "D-01", "title": "Политика", "date": "2026-01-01", "text": "Текст без ПДн."}]
    answer = asyncio.run(llm.call_deepseek(question.masked, docs))

    payload = captured["json"]
    user_text = payload["messages"][-1]["content"]
    assert "⟦PERSON_1⟧" in user_text
    assert "⟦PHONE_1⟧" in user_text
    assert "Ивану" not in user_text
    assert "+375291112233" not in user_text
    assert answer == "Позвонить ⟦PERSON_1⟧ по доставке."

