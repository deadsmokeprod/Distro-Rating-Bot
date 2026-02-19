# Чек-лист доработок по новому этапу (Stage 3)

Источник требований:
- `docs/business-requirements-2026-02-18.md` (оригинал бизнес-требований)
- пользовательские "хотелки" от 2026-02-18

Правило ведения этого файла:
- Разбивка по этапам внедрения.
- После реализации пункта: ставим `[x]`, добавляем "что сделано" и ссылку на код (`path + symbol`).
- Для каждого этапа обязательно фиксируется проверка (ручная/авто).

---

## Сквозные требования (для всех этапов)

- [ ] RBAC и tenant-изоляция не ослабляются ни в одном новом сценарии.
  - Код (план): `app/handlers/manager.py`, `app/handlers/seller.py`, `app/db/sqlite.py`.
- [ ] Все новые callback/FSM-сценарии устойчивы к повторным нажатиям и устаревшим сообщениям.
  - Код (план): `app/handlers/*`, `app/keyboards/*`.
- [ ] Ошибки интеграции и внешних API логируются безопасно (без секретов).
  - Код (план): `app/services/onec_client.py`, `app/services/turnover_sync.py`, `bot.py`.
- [ ] Не ломается private-only режим.
  - Код (план): `app/handlers/filters.py`, роутеры в `app/handlers/*`.

---

## Этап 0. Подготовка и диагностика baseline

- [x] Зафиксировать текущий baseline поведения меню, рассылки, поддержки и sync 1С.
  - Что сделано: оформлен baseline по BR-01..BR-06 с фиксацией текущего поведения и gap analysis.
  - Код/док: `docs/stage3-baseline-and-test-matrix-2026-02-18.md` (раздел 1), `app/handlers/start.py`, `app/handlers/manager.py`, `app/keyboards/seller.py`, `app/keyboards/manager.py`, `app/services/onec_client.py`.
  - Проверка: ручной анализ сценариев и сверка с текущими handlers/keyboards.
- [x] Сформировать тест-матрицу по BR-01..BR-06 (happy path + negative path).
  - Что сделано: создана матрица тестов T1..T20 с happy/negative/security/resilience кейсами.
  - Код/док: `docs/stage3-baseline-and-test-matrix-2026-02-18.md` (раздел 2).
  - Проверка: документированная матрица покрывает все требования BR-01..BR-06.
- [x] Подготовить безопасные тестовые данные и тестовый контур для 1С интеграции.
  - Что сделано: сформирован безопасный тест-контур, выполнено воспроизведение 401 по endpoint 1С (без auth и с test Basic header).
  - Код/док: `docs/stage3-baseline-and-test-matrix-2026-02-18.md` (разделы 3-4).
  - Проверка: 1С-ошибка `401` воспроизводится повторяемо вне Telegram-flow; диагностика готова к этапу фикса.

---

## Этап 1. Единое активное inline-меню (BR-01)

- [x] Ввести механизм хранения "последнего активного меню" на пользователя/контекст.
  - Что сделано: добавлен централизованный in-memory трекер активного inline-меню на пару `chat_id + actor_tg_user_id`.
  - Код: `app/utils/inline_menu.py` (`send_single_inline_menu`, `mark_inline_menu_active`, `clear_active_inline_menu`, `get_active_inline_menu_message_id`).
- [x] Перед отправкой нового inline-меню деактивировать/удалять предыдущее.
  - Что сделано: в ключевых inline-flow перед отправкой нового меню вызывается очистка предыдущего; основное меню также очищает активное inline-сообщение.
  - Код: `app/handlers/start.py`, `app/handlers/seller.py`, `app/handlers/manager.py`.
- [x] Обработать исключения Telegram API при удалении/редактировании старых сообщений.
  - Что сделано: helper использует safe delete и fallback на `edit_message_reply_markup(..., None)`; неопасные ошибки не роняют поток.
  - Код: `app/utils/inline_menu.py`.
- [x] Блокировать выполнение callback из устаревших меню.
  - Что сделано: добавлен `ActiveInlineMenuFilter`, который пропускает callback только с текущего активного inline-сообщения пользователя.
  - Код: `app/handlers/filters.py`, подключение в `app/handlers/seller.py`, `app/handlers/manager.py`.
- [x] Регресс: пагинации, подтверждения, merge/dispute/finance не ломаются.
  - Что сделано: проверено, что inline pagination/confirm ветки продолжают использовать единый активный message-id через `send_single_inline_menu` + `mark_inline_menu_active`; для устаревших callback добавлен явный ответ пользователю вместо "тихого" игнора.
  - Код: `app/handlers/seller.py`, `app/handlers/manager.py`, `app/handlers/filters.py`.
  - Проверка: технический smoke (`python -m compileall app/handlers/filters.py app/handlers/seller.py app/handlers/manager.py app/utils/inline_menu.py`) + ревью веток pagination/confirm/dispute/finance/merge.

---

## Этап 2. Интеграция с 1С: 401 и корректность импорта (BR-02)

- [x] Провести диагностику 401:
  - проверить endpoint/публикацию;
  - проверить auth-режим (анонимный или Basic Auth);
  - проверить корректность `ONEC_*` конфигов.
  - Что сделано: для `401/403/404` в клиенте 1С добавлены отдельные коды ошибок и actionable hints; в manager UI ошибка показывается с подсказкой по конфигу и auth-режиму.
  - Код: `app/services/onec_client.py`, `app/handlers/manager.py`, `README.md`.
- [x] Добавить улучшенную диагностическую телеметрию запросов к 1С (без утечки секретов).
  - Что сделано: добавлено безопасное логирование старта/итога запроса (`url`, период, `operation_type`, `auth_mode`) и ошибок (`status`, `error_code`, preview body без секретов), плюс audit `SYNC_TURNOVER_ERROR` для ручного sync.
  - Код: `app/services/onec_client.py`, `app/services/turnover_sync.py`, `app/handlers/manager.py`, `bot.py`.
- [x] Проверить и при необходимости исправить маппинг полей 1С -> `chz_turnover`.
  - Что сделано: парсер поддерживает alias-ключи (RU/EN) для полей `rows`, добавлена валидация обязательных полей (`Период`, `ПродавецИНН`, `ПокупательИНН`) с явной ошибкой контракта.
  - Код: `app/services/onec_client.py`, `app/db/sqlite.py` (`upsert_chz_turnover`).
- [x] Подтвердить идемпотентность и корректность `inserted_count/affected_*`.
  - Что сделано: верифицирована схема `INSERT ... DO NOTHING RETURNING` + последующий `UPSERT`: `inserted_count` считает только новые записи, `affected_*` строится только по новым `seller_inn` и соответствующим активным `company_group_id`.
  - Код: `app/db/sqlite.py` (`upsert_chz_turnover`), `app/services/turnover_sync.py`.
  - Проверка: code review ветки upsert и итогового `SyncTurnoverResult` + smoke компиляция сервисов/handler-ов.
- [x] Прогон: "текущий месяц" + "кастомный период" в менеджерском UI.
  - Проверка: auth успешен (401 устранен), кастомный период выполняется с корректным upsert (`rows=4364`, `fetched/upserted/inserted=4364`).
  - Что зафиксировано: при выборе "текущий месяц" и отсутствии данных в 1С за период API возвращает `400 ТипОперации не найден...` с `availableOperationTypes: []`; в bot-side подсказке добавлено явное пояснение, что чаще всего причина — отсутствие данных за выбранный период.

---

## Этап 3. Поддержка: текст -> подтверждение -> таймер 60 сек (BR-03)

- [x] Добавить FSM-сценарий ввода текста обращения.
  - Что сделано: callback `support_request` переводит пользователя в FSM (`wait_text`), после ввода текста — в шаг подтверждения.
  - Код: `app/handlers/start.py` (`SupportRequestStates`, `support_request_callback`, `support_request_collect_text`).
- [x] Добавить шаг "Подтвердить" с предпросмотром обращения.
  - Что сделано: добавлено preview-сообщение обращения с inline-кнопками `Отправить/Отмена`.
  - Код: `app/keyboards/common.py` (`support_confirm_keyboard`), `app/handlers/start.py` (`_support_preview_text`).
- [x] Реализовать 60-секундный таймер перед активацией кнопки "Отправить".
  - Что сделано: на confirm-шаге сначала показывается кнопка ожидания, затем через async helper кнопка переключается на активную отправку.
  - Код: `app/handlers/start.py` (`SUPPORT_CONFIRM_DELAY_SEC`, `_enable_support_send`, `support_request_wait`).
- [x] Обеспечить идемпотентность и защиту от повторной отправки.
  - Что сделано: используется одноразовый `support_token` в FSM, проверка актуальности callback, флаг `support_sent`, обработка устаревших кнопок.
  - Код: `app/handlers/start.py` (`_extract_support_token`, `support_request_send`, `support_request_stale`).
- [x] Сохранить текущую маршрутизацию в поддержку (`SUPPORT_USERNAME` / `SUPPORT_USER_ID`).
  - Что сделано: в inline-клавиатуре сохранена ссылка на `SUPPORT_USERNAME` (если задана), при этом добавлена bot-side отправка обращения на `SUPPORT_USER_ID`.
  - Код: `app/keyboards/common.py` (`support_inline_keyboard`), `app/handlers/start.py` (`support_request_send`).
  - Проверка: `python -m compileall app/handlers/start.py app/keyboards/common.py`, ручной e2e сценарий остается к выполнению.

---

## Этап 4. Регистрация без показа правил (BR-04)

- [x] Удалить отображение/кнопку "Правила" из незарегистрированного флоу.
  - Что сделано: из стартовых/повторных клавиатур регистрации убран пункт `SELLER_RULES`.
  - Код: `app/keyboards/seller.py` (`seller_start_menu`, `seller_retry_menu`, `seller_support_menu`).
- [x] Оставить "Правила" в меню зарегистрированных ролей.
  - Что сделано: пункт правил оставлен без изменений в меню зарегистрированных продавцов/РОП и менеджерском меню.
  - Код: `app/keyboards/seller.py` (`seller_main_menu`), `app/keyboards/manager.py` (`manager_main_menu`), handlers `seller_rules`/`manager_rules`.
- [x] Проверить, что fallback-сценарии регистрации не возвращают кнопку правил.
  - Что сделано: fallback для незарегистрированных пользователей продолжает использовать `seller_start_menu`, где кнопка правил удалена.
  - Код: `app/handlers/start.py` (`show_seller_start`), `app/handlers/seller.py` (`seller_fallback`).
  - Проверка: code review + ручной регресс по шагам регистрации остается к выполнению.

---

## Этап 5. Строгая ролевая видимость кнопок (BR-05)

- [x] Провести ревизию всех меню и callback-веток на предмет избыточной видимости.
  - Что сделано: выполнен аудит reply-меню и ключевых callback/message-входов; точки с роль-зависимым UI переведены на вычисление меню от реальной роли пользователя.
  - Код: `app/keyboards/seller.py`, `app/keyboards/manager.py`, `app/handlers/start.py`, `app/handlers/seller.py`, `app/handlers/manager.py`.
- [x] Убрать лишние кнопки из UI для каждой роли.
  - Что сделано: `seller_main_menu` разделено на `SELLER` и `ROP`; `manager_main_menu` разделено на `MANAGER` и `ADMIN` (admin-only пункты скрыты для manager).
  - Код: `app/keyboards/seller.py` (`seller_main_menu`), `app/keyboards/manager.py` (`manager_main_menu`), role-aware вызовы в handlers.
  - Проверка: `python -m compileall app/handlers/start.py app/handlers/seller.py app/handlers/manager.py app/keyboards/seller.py app/keyboards/manager.py`.
- [x] Подтвердить server-side запрет на вызов недоступных действий вручную.
  - Что сделано: сохранены и проверены role checks в handler-ах (`is_admin`, `is_manager_or_admin`, `role == "rop"`), в том числе для admin-only merge/goals и rop-only moderation/staff flows.
  - Код: `app/handlers/manager.py`, `app/handlers/seller.py`.
- [x] Проверить смену роли/статуса (active/fired) и актуализацию меню.
  - Что сделано: main/fallback/back сценарии показывают меню по актуальной роли из БД; fired-пользователи переводятся в registration flow без ролевого main-menu.
  - Код: `app/handlers/start.py` (`show_seller_menu`, `show_manager_menu`), `app/handlers/seller.py` (`_seller_main_menu_for`, `seller_fallback`), `app/handlers/manager.py` (`_manager_main_menu_for`, `manager_fallback`).
  - Проверка: code review; ручной регресс fired/restore flows остается к выполнению.

---

## Этап 6. Рассылка по выбранной компании (BR-06)

- [x] Добавить режим "рассылка по выбранной компании".
  - Что сделано: в меню таргета рассылки добавлен режим `По выбранной компании` с отдельным шагом выбора компании.
  - Код: `app/keyboards/manager.py` (`MANAGER_BROADCAST_BY_ORG`, `manager_broadcast_target_menu`), `app/handlers/manager.py` (`ManagerBroadcastStates.choose_org`, `_send_broadcast_org_list`, `manager_broadcast_org_*`).
- [x] Для Manager: показывать только свои компании.
  - Что сделано: список компаний для адресной рассылки у manager строится только через `count_orgs_by_manager/list_orgs_by_manager`; дополнительно на выборе и отправке стоит `_can_access_org`.
  - Код: `app/handlers/manager.py` (`_send_broadcast_org_list`, `manager_broadcast_org_pick`, `manager_broadcast_send`).
- [x] Для Admin: показывать все компании.
  - Что сделано: для admin в адресной рассылке используется полный список компаний (`count_orgs/list_orgs`).
  - Код: `app/handlers/manager.py` (`_send_broadcast_org_list`).
- [x] Фильтрация получателей по выбранной компании и активному статусу.
  - Что сделано: добавлена выборка получателей по `org_id` только для активных `seller/rop`.
  - Код: `app/db/sqlite.py` (`list_seller_ids_by_org`), `app/handlers/manager.py` (`manager_broadcast_send`).
- [x] Аудит отправки (кто, куда, сколько получателей).
  - Что сделано: в audit пишутся actor role, target mode, выбранная компания (для режима org), количество получателей и отправленных сообщений.
  - Код: `app/handlers/manager.py` (`manager_broadcast_send` -> `log_audit`).
  - Проверка: `python -m compileall app/handlers/manager.py app/keyboards/manager.py app/db/sqlite.py`, ручной e2e по ролям остается к выполнению.

---

## Этап 7. Финальная приемка и регресс

- [ ] Полный ручной e2e по ролям: ADMIN, MANAGER, ROP, SELLER.
  - Что сделано: подготовлен и выполнен технический smoke по role-aware меню и ключевым guard-ам.
  - Код/док: `scripts/stage7_smoke.py`, `docs/stage7-final-acceptance-2026-02-18.md`.
  - Статус: требуется отдельный ручной Telegram e2e-прогон с кликами по ролям.
- [ ] Проверка интеграции 1С (happy path + auth error path).
  - Что сделано: подтверждена готовность error-path обработки (`400/401/403/404`, `availableOperationTypes`) в smoke.
  - Код/док: `app/services/onec_client.py`, `docs/stage7-final-acceptance-2026-02-18.md`.
  - Статус: живой прогон happy/auth error against endpoint 1С требуется отдельно.
- [x] Проверка отсутствия утечек секретов в логах.
  - Что сделано: автоматическая проверка `logs/bot.log` на маркеры секретов и token-like паттерны.
  - Код: `scripts/stage7_smoke.py` (`check_no_obvious_secret_leaks_in_log`).
- [x] Проверка стабильности inline-UX (одно активное меню).
  - Что сделано: smoke проверяет подключение `ActiveInlineMenuFilter` и использование single-active inline helpers.
  - Код: `scripts/stage7_smoke.py` (`check_inline_single_menu_guards`), `app/handlers/seller.py`, `app/handlers/manager.py`.
- [x] Проверка антиспама поддержки (таймер, повторные нажатия, отмена).
  - Что сделано: smoke проверяет наличие целевого flow (FSM + 60s + token + stale callbacks).
  - Код: `scripts/stage7_smoke.py` (`check_support_antispam_flow`), `app/handlers/start.py`, `app/keyboards/common.py`.
- [x] Обновление эксплуатационной документации (`README.md`, `.env.example` при необходимости).
  - Что сделано: `README.md` обновлен по новым flows (role-aware меню, поддержка с таймером, рассылка по выбранной компании) и добавлена команда smoke-проверки Stage 7.
  - Код/док: `README.md`, `docs/stage7-final-acceptance-2026-02-18.md`.

---

## Журнал выполнения (заполняется по ходу работ)

Формат записи:
- Дата:
- Этап/пункт:
- Что сделано (кратко):
- Код-ссылки:
- Проверка (ручная/авто):

- Дата: 2026-02-18
- Этап/пункт: Этап 7 (техрегресс smoke)
- Что сделано (кратко): добавлен и выполнен smoke-скрипт Stage 7, проверены role-aware меню, anti-spam поддержки, inline single-menu, error-path 1С, утечки секретов в логах.
- Код-ссылки: `scripts/stage7_smoke.py`, `docs/stage7-final-acceptance-2026-02-18.md`
- Проверка (ручная/авто): авто (`python scripts/stage7_smoke.py` -> `total=6 failed=0`)

- Дата: 2026-02-18
- Этап/пункт: Этап 7 (документация)
- Что сделано (кратко): обновлена эксплуатационная документация под новые Stage 3 сценарии.
- Код-ссылки: `README.md`, `docs/implementation-checklist3.md`
- Проверка (ручная/авто): ревью изменений в документации
