# DNS-настройки в REG.RU для деплоя АптекаА

## Текущая ситуация
- `aptekaa.ru` → DigitalOcean (старый сайт-заглушка 2013 года)
- `аптекаа.рф` (xn--80aerl0afi.xn--p1ai) → REG.RU парковка
- Почта на Mail.ru
- Записи валидации Я.360 (`yandex-verification`) — оставить, не удалять

## Что меняем после деплоя на VPS

**IP вашего сервера: `89.169.137.36`**

### Для домена aptekaa.ru

#### Шаг 1 — Удалить старые A-записи на DigitalOcean
В REG.RU → Мои домены → aptekaa.ru → DNS-серверы и управление зоной:

Найдите и **УДАЛИТЕ** все A-записи, указывающие на DigitalOcean (обычно IP вида `159.x.x.x` или `46.x.x.x`).

#### Шаг 2 — Добавить новые A-записи

| Тип | Subdomain | Значение | TTL |
|---|---|---|---|
| A | @ | `89.169.137.36` | 3600 |
| A | www | `89.169.137.36` | 3600 |

#### Шаг 3 — Удалить старые MX-записи Mail.ru

**УДАЛИТЕ** все MX-записи вида:
- `emx.mail.ru`
- `mxs.mail.ru`

И все `_dmarc`, `mailru._domainkey` если они были созданы для Mail.ru (если вы их добавляли по их инструкции).

#### Шаг 4 — Добавить MX/SPF/DKIM Яндекс 360

| Тип | Subdomain | Значение | TTL |
|---|---|---|---|
| MX | @ | `mx.yandex.net.` (приоритет 10) | 3600 |
| TXT | @ | `v=spf1 redirect=_spf.yandex.net` | 3600 |
| TXT | mail._domainkey | (значение из Я.360 → Домены → DKIM) | 3600 |
| TXT | _dmarc | `v=DMARC1; p=none; rua=mailto:dmarc@aptekaa.ru` | 3600 |

⚠️ **DKIM-ключ** возьмите в Я.360 → «Домены» → ваш домен → раздел **«DKIM-подпись»**. Длинная строка вида `v=DKIM1; k=rsa; p=MIGfMA0G...`.

⚠️ **Запись `yandex-verification`** — оставьте, не удаляйте. Она для подтверждения владения.

### Для домена аптекаа.рф (xn--80aerl0afi.xn--p1ai)

| Тип | Subdomain | Значение | TTL |
|---|---|---|---|
| A | @ | `89.169.137.36` | 3600 |
| A | www | `89.169.137.36` | 3600 |

(MX для этого домена не нужны — почта только на aptekaa.ru, аптекаа.рф редиректит на aptekaa.ru)

## Время распространения

DNS-изменения распространяются от 5 минут до 24 часов. Обычно 15-30 минут.

Проверка снаружи:
```bash
dig aptekaa.ru +short              # должен вернуть 89.169.137.36
dig www.aptekaa.ru +short          # 89.169.137.36
dig MX aptekaa.ru +short           # 10 mx.yandex.net.
dig xn--80aerl0afi.xn--p1ai +short # 89.169.137.36
```

## Чеклист

- [ ] A для aptekaa.ru → 89.169.137.36
- [ ] A для www.aptekaa.ru → 89.169.137.36
- [ ] Удалены A-записи на DigitalOcean
- [ ] MX → mx.yandex.net (приоритет 10)
- [ ] Удалены MX Mail.ru
- [ ] SPF: `v=spf1 redirect=_spf.yandex.net`
- [ ] DKIM `mail._domainkey` (значение из Я.360)
- [ ] DMARC `_dmarc` (`v=DMARC1; p=none; ...`)
- [ ] A для аптекаа.рф → 89.169.137.36
- [ ] yandex-verification — НЕ удалять
