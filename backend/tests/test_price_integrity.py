from scripts.parse_gorzdrav import curated_identity_verified, curated_pack_matches, dosage_matches
from scripts.parse_zdorovie import _parse_price


def test_price_parser_decodes_html_non_breaking_spaces():
    assert _parse_price("Цена 8&nbsp;220 ₽") == 8220
    assert _parse_price("Цена 1&#160;219 ₽") == 1219


def test_dosage_match_uses_numeric_boundaries():
    assert dosage_matches("100 мг", "Изониазид таблетки 100 мг 100 шт")
    assert not dosage_matches("100 мг", "Изониазид таблетки 300 мг 100 шт")


def test_dosage_match_checks_every_combination_component():
    dose = "0.1 мг+10 мг+10 мг"
    assert dosage_matches(dose, "Адельфан Плюс таблетки 0.1 мг + 10 мг + 10 мг 10 шт")
    assert not dosage_matches(dose, "Адельфан Плюс таблетки 0.1 мг + 5 мг 10 шт")
    assert not dosage_matches(dose, "Адельфан Плюс таблетки 0.1 мг + 10 мг 10 шт")


def test_curated_pack_match_checks_container_count_and_inner_volume():
    injectable = {"variants": [{"pack_size": "1 флакон × 25 мл (50 мг)"}]}
    assert curated_pack_matches(injectable, "Доксорубицин 2 мг/мл 25 мл 1 шт", "1 шт")
    assert not curated_pack_matches(injectable, "Доксорубицин 2 мг/мл 10 мл 1 шт", "1 шт")

    ointment = {"variants": [{"pack_size": "1 туба × 30 г"}]}
    assert curated_pack_matches(ointment, "Пиолизин мазь 30 г", "30 г")
    assert not curated_pack_matches(ointment, "Пиолизин мазь 50 г", "50 г")


def test_curated_identity_requires_the_approved_manufacturer():
    med = {
        "curated_source": "priority_medications_2026-09",
        "name": "Виагра",
        "mnn": "Силденафил",
        "dosage": "100 мг",
        "form": "таблетки",
        "manufacturer": "Viatris",
        "variants": [{"pack_size": "4 шт"}],
    }
    valid = {
        "name": "Виагра таблетки 100 мг 4 шт",
        "attributes": [{"code": "manufacturer", "value": "Viatris"}],
    }
    wrong = {
        "name": "Виагра таблетки 100 мг 4 шт",
        "attributes": [{"code": "manufacturer", "value": "Другая компания"}],
    }
    assert curated_identity_verified(med, valid, "4 шт", "matched")
    assert not curated_identity_verified(med, wrong, "4 шт", "matched")
    assert not curated_identity_verified(med, {"name": valid["name"], "attributes": []}, "4 шт", "matched")
