"""
Static seed for cities, categories and partner pharmacies.

Mirrors what the frontend used to import from `mock.js` so that the
catalog API is self‑contained on the backend. Pharmacies are still
demo data and will be replaced once aptechnaja ingestion lands.
"""

CITIES = [
    {"slug": "msk", "name": "Москва", "lat": 55.7558, "lng": 37.6173},
    {"slug": "spb", "name": "Санкт-Петербург", "lat": 59.9343, "lng": 30.3351},
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

PHARMACIES = [
    # Москва
    {"id": "p1", "city": "msk", "name": "Аптека «Здоровье»", "chain": "Здоровье", "address": "Москва, ул. Тверская, 12", "metro": "Тверская", "phone": "+7 (495) 123-45-67", "hours": "Пн–Вс: 08:00–22:00", "lat": 55.7615, "lng": 37.6063, "rating": 4.7},
    {"id": "p2", "city": "msk", "name": "Аптека «36,6»", "chain": "36,6", "address": "Москва, Ленинградский пр-т, 39", "metro": "Динамо", "phone": "+7 (495) 234-56-78", "hours": "Круглосуточно", "lat": 55.7903, "lng": 37.5546, "rating": 4.5},
    {"id": "p3", "city": "msk", "name": "Ригла", "chain": "Ригла", "address": "Москва, ул. Арбат, 28", "metro": "Арбатская", "phone": "+7 (495) 345-67-89", "hours": "Пн–Вс: 09:00–23:00", "lat": 55.7494, "lng": 37.5934, "rating": 4.6},
    {"id": "p4", "city": "msk", "name": "Горздрав", "chain": "Горздрав", "address": "Москва, Кутузовский пр-т, 22", "metro": "Кутузовская", "phone": "+7 (495) 456-78-90", "hours": "Пн–Вс: 07:00–23:00", "lat": 55.7400, "lng": 37.5505, "rating": 4.4},
    {"id": "p5", "city": "msk", "name": "Столички", "chain": "Столички", "address": "Москва, Профсоюзная, 56", "metro": "Новые Черёмушки", "phone": "+7 (495) 567-89-01", "hours": "Круглосуточно", "lat": 55.6790, "lng": 37.5500, "rating": 4.3},
    {"id": "p6", "city": "msk", "name": "Аптека «Будь Здоров»", "chain": "Будь Здоров", "address": "Москва, ул. Мясницкая, 8", "metro": "Лубянка", "phone": "+7 (495) 678-90-12", "hours": "Пн–Вс: 08:00–22:00", "lat": 55.7616, "lng": 37.6299, "rating": 4.5},
    {"id": "p7", "city": "msk", "name": "Самсон-Фарма", "chain": "Самсон-Фарма", "address": "Москва, Комсомольский пр-т, 14", "metro": "Парк культуры", "phone": "+7 (495) 789-01-23", "hours": "Пн–Вс: 09:00–22:00", "lat": 55.7274, "lng": 37.5863, "rating": 4.6},
    {"id": "p8", "city": "msk", "name": "Аптеки А5", "chain": "А5", "address": "Москва, Большая Дмитровка, 32", "metro": "Чеховская", "phone": "+7 (495) 890-12-34", "hours": "Пн–Вс: 08:00–23:00", "lat": 55.7691, "lng": 37.6149, "rating": 4.4},
    {"id": "p9", "city": "msk", "name": "Аптечная сеть «Ноль Боли»", "chain": "Ноль Боли", "address": "Москва, ул. Пятницкая, 25", "metro": "Третьяковская", "phone": "+7 (495) 901-23-45", "hours": "Пн–Вс: 09:00–21:00", "lat": 55.7398, "lng": 37.6259, "rating": 4.2},
    {"id": "p10", "city": "msk", "name": "Доктор Столетов", "chain": "Доктор Столетов", "address": "Москва, Мичуринский пр-т, 31", "metro": "Раменки", "phone": "+7 (495) 012-34-56", "hours": "Пн–Вс: 08:00–22:00", "lat": 55.6951, "lng": 37.5031, "rating": 4.5},
    {"id": "p11", "city": "msk", "name": "Аптека Wer.ru", "chain": "Wer.ru", "address": "Москва, ул. Новый Арбат, 15", "metro": "Арбатская", "phone": "+7 (495) 111-22-33", "hours": "Круглосуточно", "lat": 55.7522, "lng": 37.5944, "rating": 4.7},
    {"id": "p12", "city": "msk", "name": "Планета Здоровья", "chain": "Планета Здоровья", "address": "Москва, Дмитровское ш., 71", "metro": "Селигерская", "phone": "+7 (495) 222-33-44", "hours": "Пн–Вс: 08:00–22:00", "lat": 55.8728, "lng": 37.5468, "rating": 4.4},
    # Санкт-Петербург
    {"id": "p13", "city": "spb", "name": "Аптека «Первая помощь»", "chain": "Первая помощь", "address": "СПб, Невский пр-т, 88", "metro": "Маяковская", "phone": "+7 (812) 111-11-11", "hours": "Пн–Вс: 08:00–23:00", "lat": 59.9343, "lng": 30.3573, "rating": 4.6},
    {"id": "p14", "city": "spb", "name": "Озерки", "chain": "Озерки", "address": "СПб, Лиговский пр-т, 50", "metro": "Лиговский пр-т", "phone": "+7 (812) 222-22-22", "hours": "Круглосуточно", "lat": 59.9265, "lng": 30.3593, "rating": 4.5},
    {"id": "p15", "city": "spb", "name": "Аптека «Радуга»", "chain": "Радуга", "address": "СПб, Большой пр-т П.С., 72", "metro": "Петроградская", "phone": "+7 (812) 333-33-33", "hours": "Пн–Вс: 09:00–22:00", "lat": 59.9659, "lng": 30.3033, "rating": 4.4},
    {"id": "p16", "city": "spb", "name": "Аптека «Невис»", "chain": "Невис", "address": "СПб, Московский пр-т, 165", "metro": "Электросила", "phone": "+7 (812) 444-44-44", "hours": "Пн–Вс: 08:00–22:00", "lat": 59.8769, "lng": 30.3196, "rating": 4.5},
    {"id": "p17", "city": "spb", "name": "Доктор Столетов", "chain": "Доктор Столетов", "address": "СПб, Каменноостровский пр-т, 36", "metro": "Петроградская", "phone": "+7 (812) 555-55-55", "hours": "Пн–Вс: 09:00–21:00", "lat": 59.9712, "lng": 30.3110, "rating": 4.6},
    {"id": "p18", "city": "spb", "name": "ГосАптека", "chain": "ГосАптека", "address": "СПб, ул. Восстания, 15", "metro": "Площадь Восстания", "phone": "+7 (812) 666-66-66", "hours": "Пн–Сб: 08:00–22:00", "lat": 59.9347, "lng": 30.3608, "rating": 4.3},
    {"id": "p19", "city": "spb", "name": "Аптека «Лекарь»", "chain": "Лекарь", "address": "СПб, Гражданский пр-т, 41", "metro": "Академическая", "phone": "+7 (812) 777-77-77", "hours": "Круглосуточно", "lat": 60.0145, "lng": 30.3956, "rating": 4.4},
    {"id": "p20", "city": "spb", "name": "Будь Здоров СПб", "chain": "Будь Здоров", "address": "СПб, пр-т Просвещения, 80", "metro": "Проспект Просвещения", "phone": "+7 (812) 888-88-88", "hours": "Пн–Вс: 08:00–22:00", "lat": 60.0518, "lng": 30.3325, "rating": 4.5},
]


def pharmacies_by_city(city: str):
    return [p for p in PHARMACIES if p["city"] == city]


def find_pharmacy_by_id(pid: str):
    for p in PHARMACIES:
        if p["id"] == pid:
            return p
    return None
