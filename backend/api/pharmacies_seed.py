"""
Static seed for cities, categories and partner pharmacies.
"""

CITIES = [
    {"slug": "msk", "name": "Москва", "lat": 55.7558, "lng": 37.6173},
    {"slug": "spb", "name": "Санкт-Петербург", "lat": 59.9343, "lng": 30.3351},
    {"slug": "krd", "name": "Краснодар", "lat": 45.0355, "lng": 38.9753},
    {"slug": "nn", "name": "Нижний Новгород", "lat": 56.3268, "lng": 44.0065},
    {"slug": "ekb", "name": "Екатеринбург", "lat": 56.8389, "lng": 60.6057},
    {"slug": "kzn", "name": "Казань", "lat": 55.7963, "lng": 49.1088},
    {"slug": "nsk", "name": "Новосибирск", "lat": 55.0084, "lng": 82.9357},
    {"slug": "sam", "name": "Самара", "lat": 53.2415, "lng": 50.2212},
    {"slug": "chel", "name": "Челябинск", "lat": 55.1644, "lng": 61.4368},
    {"slug": "ufa", "name": "Уфа", "lat": 54.7388, "lng": 55.9721},
    {"slug": "rnd", "name": "Ростов-на-Дону", "lat": 47.2225, "lng": 39.7188},
    {"slug": "vrn", "name": "Воронеж", "lat": 51.6608, "lng": 39.2003},
]

CATEGORIES = [
    {"slug": "ot-prostudy", "title": "От простуды и гриппа", "icon": "Thermometer", "color": "#FEE2E2", "accent": "#DC2626"},
    {"slug": "obezbolivayuschie", "title": "Обезболивающие", "icon": "Pill", "color": "#FEF3C7", "accent": "#D97706"},
    {"slug": "vitaminy-bady", "title": "Витамины и БАДы", "icon": "Leaf", "color": "#DCFCE7", "accent": "#16A34A"},
    {"slug": "zhkt", "title": "ЖКТ и пищеварение", "icon": "Apple", "color": "#FFE4E6", "accent": "#E11D48"},
    {"slug": "serdce", "title": "Сердце и сосуды", "icon": "HeartPulse", "color": "#E0E7FF", "accent": "#4F46E5"},
    {"slug": "allergiya", "title": "Аллергия", "icon": "Wind", "color": "#CFFAFE", "accent": "#0891B2"},
    {"slug": "antibiotiki", "title": "Антибиотики", "icon": "Shield", "color": "#F3E8FF", "accent": "#7E22CE"},
    {"slug": "kozha", "title": "Дерматология", "icon": "Sparkles", "color": "#FEF9C3", "accent": "#CA8A04"},
    {"slug": "glaza", "title": "Глаза", "icon": "Eye", "color": "#DBEAFE", "accent": "#1D4ED8"},
    {"slug": "nervnaya", "title": "Нервная система", "icon": "Brain", "color": "#EDE9FE", "accent": "#6D28D9"},
    {"slug": "other", "title": "Прочие препараты", "icon": "Pill", "color": "#F1F5F9", "accent": "#475569"},
]

PHARMACIES: list[dict] = [
    {
        "id": "gorzdrav",
        "name": "Горздрав",
        "city": "msk",
        "address": "Сеть аптек по всей Москве",
        "url": "https://gorzdrav.org",
        "logo": "gorzdrav",
    },
    {
        "id": "gorzdrav",
        "name": "Горздрав",
        "city": "spb",
        "address": "Сеть аптек по всему Санкт-Петербургу",
        "url": "https://gorzdrav.org",
        "logo": "gorzdrav",
    },
    # Аптека 36,6 — 2-й источник цен (Этап 1: только цена по городу, без
    # карты наличия). Намеренно БЕЗ lat/lng — фронт не рисует её маркером.
    {
        "id": "apteka366",
        "name": "Аптека 36,6",
        "city": "msk",
        "address": "Сеть аптек по всей Москве",
        "url": "https://366.ru",
        "logo": "apteka366",
    },
    {
        "id": "apteka366",
        "name": "Аптека 36,6",
        "city": "spb",
        "address": "Сеть аптек по всему Санкт-Петербургу",
        "url": "https://366.ru",
        "logo": "apteka366",
    },
    # Ригла — 3-й источник цен (Этап 1: только цена по Москве, без карты
    # наличия). Только msk: каталог отдаётся для региона домена www.rigla.ru.
    # Намеренно БЕЗ lat/lng — фронт не рисует её маркером.
    {
        "id": "rigla",
        "name": "Ригла",
        "city": "msk",
        "address": "Сеть аптек по всей Москве",
        "url": "https://www.rigla.ru",
        "logo": "rigla",
    },
    # Аптечество (группа Протек/Ригла) — источник цен для НН, Москвы и СПб
    # (регион = поддомен: aptechestvo.ru / moscow. / spb.). Краснодар не
    # обслуживает. Этап 1: только цена по городу, без карты наличия. Намеренно
    # БЕЗ lat/lng — фронт не рисует её маркером (как 36,6/Ригла на Этапе 1).
    {
        "id": "aptechestvo",
        "name": "Аптечество",
        "city": "nn",
        "address": "Сеть аптек по всему Нижнему Новгороду",
        "url": "https://aptechestvo.ru",
        "logo": "aptechestvo",
    },
    {
        "id": "aptechestvo",
        "name": "Аптечество",
        "city": "msk",
        "address": "Сеть аптек по всей Москве",
        "url": "https://moscow.aptechestvo.ru",
        "logo": "aptechestvo",
    },
    {
        "id": "aptechestvo",
        "name": "Аптечество",
        "city": "spb",
        "address": "Сеть аптек по всему Санкт-Петербургу",
        "url": "https://spb.aptechestvo.ru",
        "logo": "aptechestvo",
    },
    # Здоровье (s-zdorovie.ru) — 2-й источник цен для Краснодара (1-й — Максавит).
    # Краснодарская сеть (город по умолчанию = Краснодар, цена единая). Этап 1:
    # только цена, без карты наличия. Намеренно БЕЗ lat/lng — фронт не рисует
    # её маркером (как 36,6/Ригла/Аптечество на Этапе 1).
    {
        "id": "zdorovie",
        "name": "Здоровье",
        "city": "krd",
        "address": "Сеть аптек по всему Краснодару",
        "url": "https://s-zdorovie.ru",
        "logo": "zdorovie",
    },
    # Фармакопейка (farmakopeika.ru) — 2-й источник цен для Новосибирска (1-й —
    # Магнит). Сибирская сеть, регион = поддомен novosibirsk.farmakopeika.ru.
    # Этап 1: только цена, без карты наличия — намеренно БЕЗ lat/lng.
    {
        "id": "farmakopeika",
        "name": "Фармакопейка",
        "city": "nsk",
        "address": "Сеть аптек по всему Новосибирску",
        "url": "https://novosibirsk.farmakopeika.ru",
        "logo": "farmakopeika",
    },
    # Магнит Аптека (apteka.magnit.ru) — федеральная сеть, мультигород через FIAS.
    # Фаза 1: наши 4 города. Цена И остаток по городу (webgate). Этап 1: без карты
    # по аптекам — БЕЗ lat/lng (маркеров нет, как у 36,6/Ригла/Аптечество Этап 1).
    *[
        {
            "id": "magnit",
            "name": "Магнит Аптека",
            "city": _c,
            "address": "Сеть аптек Магнит",
            "url": "https://apteka.magnit.ru",
            "logo": "magnit",
        }
        for _c in ("msk", "spb", "krd", "nn", "ekb", "kzn", "nsk", "sam", "chel", "ufa", "rnd", "vrn")
    ],
]


def pharmacies_by_city(city: str):
    return [p for p in PHARMACIES if p["city"] == city]


def find_pharmacy_by_id(pid: str):
    for p in PHARMACIES:
        if p["id"] == pid:
            return p
    return None


def find_pharmacy(pid: str, city: str | None = None):
    """City-aware lookup: prefer the entry matching both id and city,
    fall back to id-only (так старые ссылки без города не ломаются)."""
    if city:
        for p in PHARMACIES:
            if p["id"] == pid and p["city"] == city:
                return p
    return find_pharmacy_by_id(pid)
