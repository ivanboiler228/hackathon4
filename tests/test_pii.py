from app.pii import PIILeakError, PIIMasker, UnknownTagError


def test_masks_and_restores_known_pii():
    text = (
        "Позвони Ивану Иванову на +375291112233, email ivan@example.com, "
        "УНП 123456789, ООО «Ромашка»."
    )
    masker = PIIMasker()
    result = masker.mask(text)
    assert "Ивану" not in result.masked
    assert "+375291112233" not in result.masked
    assert "ivan@example.com" not in result.masked
    assert "123456789" not in result.masked
    assert "Ромашка" not in result.masked
    assert "⟦PERSON_1⟧" in result.masked
    assert "⟦PHONE_1⟧" in result.masked
    assert masker.unmask(result.masked) == text


def test_same_value_gets_same_tag():
    masker = PIIMasker()
    result = masker.mask("Анна Ковалёва и снова Анна Ковалёва")
    assert result.masked.count("⟦PERSON_1⟧") == 2
    assert len(result.mapping) == 1


def test_unknown_tag_is_rejected():
    masker = PIIMasker()
    masker.mask("Позвони Ивану Иванову")
    try:
        masker.unmask("Привет, ⟦PERSON_9⟧")
    except UnknownTagError:
        pass
    else:
        raise AssertionError("Неизвестный тег должен отклоняться")


def test_raw_pii_is_blocked():
    masker = PIIMasker()
    try:
        masker.assert_clean("Телефон +375291112233")
    except PIILeakError:
        pass
    else:
        raise AssertionError("Сырой телефон должен блокироваться")


def test_known_employee_name_is_masked_even_lowercase():
    masker = PIIMasker()
    result = masker.mask("игорь подготовит график смен до пятницы")
    assert "игорь" not in result.masked
    assert "⟦PERSON_1⟧" in result.masked
    assert masker.unmask(result.masked) == "игорь подготовит график смен до пятницы"

