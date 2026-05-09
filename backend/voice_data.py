"""
Mock data for the voice assistant context.
Mirrors the frontend mock so the bot can reason about meds and pharmacies.
Will be replaced with real DB queries later.
"""

PHARMACIES = [
    {"id": "p1", "city": "Москва", "name": "Аптека «Здоровье»", "address": "ул. Тверская, 12", "metro": "Тверская", "phone": "+7 (495) 123-45-67", "hours": "Пн–Вс: 08:00–22:00"},
    {"id": "p2", "city": "Москва", "name": "Аптека «36,6»", "address": "Ленинградский пр-т, 39", "metro": "Динамо", "phone": "+7 (495) 234-56-78", "hours": "Круглосуточно"},
    {"id": "p3", "city": "Москва", "name": "Ригла", "address": "ул. Арбат, 28", "metro": "Арбатская", "phone": "+7 (495) 345-67-89", "hours": "Пн–Вс: 09:00–23:00"},
    {"id": "p4", "city": "Москва", "name": "Горздрав", "address": "Кутузовский пр-т, 22", "metro": "Кутузовская", "phone": "+7 (495) 456-78-90", "hours": "Пн–Вс: 07:00–23:00"},
    {"id": "p5", "city": "Москва", "name": "Столички", "address": "Профсоюзная, 56", "metro": "Новые Черёмушки", "phone": "+7 (495) 567-89-01", "hours": "Круглосуточно"},
    {"id": "p6", "city": "Москва", "name": "Аптека «Будь Здоров»", "address": "ул. Мясницкая, 8", "metro": "Лубянка", "phone": "+7 (495) 678-90-12", "hours": "Пн–Вс: 08:00–22:00"},
    {"id": "p7", "city": "Москва", "name": "Самсон-Фарма", "address": "Комсомольский пр-т, 14", "metro": "Парк культуры", "phone": "+7 (495) 789-01-23", "hours": "Пн–Вс: 09:00–22:00"},
    {"id": "p8", "city": "Москва", "name": "Аптеки А5", "address": "Большая Дмитровка, 32", "metro": "Чеховская", "phone": "+7 (495) 890-12-34", "hours": "Пн–Вс: 08:00–23:00"},
    {"id": "p13", "city": "СПб", "name": "Первая помощь", "address": "Невский пр-т, 88", "metro": "Маяковская", "phone": "+7 (812) 111-11-11", "hours": "Пн–Вс: 08:00–23:00"},
    {"id": "p14", "city": "СПб", "name": "Озерки", "address": "Лиговский пр-т, 50", "metro": "Лиговский пр-т", "phone": "+7 (812) 222-22-22", "hours": "Круглосуточно"},
    {"id": "p15", "city": "СПб", "name": "Аптека «Радуга»", "address": "Большой пр-т П.С., 72", "metro": "Петроградская", "phone": "+7 (812) 333-33-33", "hours": "Пн–Вс: 09:00–22:00"},
]

# Subset of meds the bot can advise on (top searches) with pricing samples
MEDICATIONS = [
    {"name": "Парацетамол", "form": "Таблетки 500 мг", "price_from": 40, "price_to": 70, "rx": False, "category": "Обезболивающие"},
    {"name": "Ибупрофен", "form": "Таблетки 200 мг", "price_from": 70, "price_to": 110, "rx": False, "category": "Обезболивающие"},
    {"name": "Аспирин Кардио", "form": "Таблетки 100 мг", "price_from": 245, "price_to": 365, "rx": False, "category": "Сердце и сосуды"},
    {"name": "Нурофен", "form": "Таблетки 200 мг", "price_from": 195, "price_to": 295, "rx": False, "category": "Обезболивающие"},
    {"name": "Цитрамон П", "form": "Таблетки", "price_from": 30, "price_to": 50, "rx": False, "category": "Обезболивающие"},
    {"name": "Кагоцел", "form": "Таблетки 12 мг", "price_from": 280, "price_to": 415, "rx": False, "category": "От простуды"},
    {"name": "Арбидол", "form": "Капсулы 100 мг", "price_from": 415, "price_to": 625, "rx": False, "category": "От простуды"},
    {"name": "ТераФлю", "form": "Порошок", "price_from": 365, "price_to": 545, "rx": False, "category": "От простуды"},
    {"name": "Витамин D3 2000 МЕ", "form": "Капсулы", "price_from": 740, "price_to": 1100, "rx": False, "category": "Витамины и БАДы"},
    {"name": "Магний B6", "form": "Таблетки", "price_from": 600, "price_to": 895, "rx": False, "category": "Нервная система"},
    {"name": "Омега-3", "form": "Капсулы 1000 мг", "price_from": 625, "price_to": 935, "rx": False, "category": "Витамины и БАДы"},
    {"name": "Смекта", "form": "Порошок", "price_from": 165, "price_to": 245, "rx": False, "category": "ЖКТ"},
    {"name": "Энтеросгель", "form": "Паста", "price_from": 415, "price_to": 625, "rx": False, "category": "ЖКТ"},
    {"name": "Омепразол", "form": "Капсулы 20 мг", "price_from": 80, "price_to": 125, "rx": False, "category": "ЖКТ"},
    {"name": "Кардиомагнил", "form": "Таблетки 75 мг", "price_from": 330, "price_to": 495, "rx": False, "category": "Сердце и сосуды"},
    {"name": "Зодак", "form": "Таблетки 10 мг", "price_from": 245, "price_to": 365, "rx": False, "category": "Аллергия"},
    {"name": "Супрастин", "form": "Таблетки 25 мг", "price_from": 125, "price_to": 190, "rx": False, "category": "Аллергия"},
    {"name": "Аква Марис", "form": "Спрей назальный", "price_from": 245, "price_to": 365, "rx": False, "category": "Мать и дитя"},
    {"name": "Глицин", "form": "Таблетки 100 мг", "price_from": 75, "price_to": 110, "rx": False, "category": "Нервная система"},
    {"name": "Мукалтин", "form": "Таблетки", "price_from": 30, "price_to": 50, "rx": False, "category": "От простуды"},
]

def build_context_text() -> str:
    """Compact context for the system prompt."""
    meds_lines = []
    for m in MEDICATIONS:
        rx = " (по рецепту)" if m["rx"] else ""
        meds_lines.append(f"- {m['name']} ({m['form']}) — от {m['price_from']} ₽ до {m['price_to']} ₽{rx}")
    pharm_lines = []
    for p in PHARMACIES:
        pharm_lines.append(f"- {p['name']} ({p['city']}, {p['address']}, м. {p['metro']}, {p['hours']})")
    return (
        "ДОСТУПНЫЕ ПРЕПАРАТЫ В НАШЕЙ БАЗЕ:\n" + "\n".join(meds_lines)
        + "\n\nАПТЕКИ-ПАРТНЁРЫ (Москва, СПб):\n" + "\n".join(pharm_lines)
    )
