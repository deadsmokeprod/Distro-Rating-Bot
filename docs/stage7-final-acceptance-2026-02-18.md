# Stage 7: финальная приемка и регресс (технический smoke)

Дата: 2026-02-18  
Контур: локальный smoke + ревью кода по BR-01..BR-06.

---

## 1) Что проверено автоматически

Выполнен запуск:

```bash
python scripts/stage7_smoke.py
```

Результат: `total=6 failed=0`.

Покрытые проверки:

1. Role UI (`SELLER` vs `ROP`) — в `SELLER`-меню нет ROP-only пунктов, в `ROP` они присутствуют.
2. Role UI (`MANAGER` vs `ADMIN`) — admin-only пункты скрыты для manager.
3. Антиспам поддержки — в коде присутствует flow `text -> confirm -> 60s -> send` + token/stale guards.
4. Inline UX — подключены фильтры/хелперы single-active inline menu.
5. 1С error-path — присутствуют статусы `400/401/403/404` и обработка `availableOperationTypes`.
6. Логи — в `logs/bot.log` не обнаружены явные маркеры утечки секретов.

---

## 2) Дополнительно прогнано

- `python -m compileall app/handlers/start.py app/handlers/seller.py app/handlers/manager.py app/keyboards/seller.py app/keyboards/manager.py app/db/sqlite.py`
- `python -m compileall scripts/stage7_smoke.py`

Обе проверки завершены успешно.

---

## 3) Ограничения текущей приемки

Не выполнялся живой Telegram E2E с кликами по ролям и не запускался live-вызов 1С endpoint из этого smoke-прогона.  
Для финальной бизнес-приемки нужен отдельный ручной прогон по матрице сценариев (ADMIN/MANAGER/ROP/SELLER + 1С happy/error path).

---

## 4) Кодовые ссылки

- Smoke-скрипт: `scripts/stage7_smoke.py`
- Role-aware меню: `app/keyboards/seller.py`, `app/keyboards/manager.py`
- Поддержка с таймером/подтверждением: `app/handlers/start.py`, `app/keyboards/common.py`
- Единое активное inline-меню: `app/handlers/seller.py`, `app/handlers/manager.py`, `app/handlers/filters.py`, `app/utils/inline_menu.py`
- Рассылка по выбранной компании: `app/handlers/manager.py`, `app/db/sqlite.py`

