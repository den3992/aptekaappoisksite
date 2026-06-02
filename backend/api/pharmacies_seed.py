"""
Static seed for cities, categories and partner pharmacies.
"""

CITIES = [
    {"slug": "msk", "name": "Москва", "lat": 55.7558, "lng": 37.6173},
    {"slug": "spb", "name": "Санкт-Петербург", "lat": 59.9343, "lng": 30.3351},
    {"slug": "krd", "name": "Краснодар", "lat": 45.0355, "lng": 38.9753},
    {"slug": "nn", "name": "Нижний Новгород", "lat": 56.3268, "lng": 44.0065},
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
    # Аптечество — 2-й источник цен для Нижнего Новгорода (Этап 1: только цена
    # по городу, без карты наличия). Намеренно БЕЗ lat/lng — фронт не рисует
    # её маркером (как 36,6/Ригла на Этапе 1).
    {
        "id": "aptechestvo",
        "name": "Аптечество",
        "city": "nn",
        "address": "Сеть аптек по всему Нижнему Новгороду",
        "url": "https://aptechestvo.ru",
        "logo": "aptechestvo",
    },
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
