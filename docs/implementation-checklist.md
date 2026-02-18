# Чек-лист доработок по ТЗ

Источник требований:
- `docs/dev 2 18 02 25.docx` (оригинал)
- `docs/dev-2-18-02-25.extracted.md` (извлеченный текст с якорями `Pxxx`)

Правило ведения этого файла:
- Разбивка идет по смыслу и этапам (не по абзацам).
- После реализации пункта: ставим `[x]`, добавляем короткий факт "что сделано", и ссылку на код (`path + symbol`).

---

## Сквозные требования (для всех этапов)

Ссылка: [P116-P130](./dev-2-18-02-25.extracted.md#p116)

- [x] UX-правила навигации: одна колонка, понятный "Назад", inline-пагинация по `INLINE_PAGE_SIZE`, окно рейтинга `RATING_WINDOW_SIZE`.
  - Выполнение: в клавиатурах используется одно-колоночная компоновка и единый `⬅️ Назад`; inline-пагинация вынесена в `INLINE_PAGE_SIZE`; размер окна рейтинга вынесен в `RATING_WINDOW_SIZE`.
  - Код: `app/keyboards/common.py` (`build_reply_keyboard`, `build_inline_keyboard`, `BACK_TEXT`), `app/config.py` (`Config.inline_page_size`, `Config.rating_window_size`), `.env.example`, `app/handlers/seller.py` (`_build_rating_window`, `_months_keyboard`, `_render_my_staff_page`), `app/handlers/manager.py` (пагинация списков организаций/слияний).
- [x] 2-шаговые подтверждения с таймером: спор (`DISPUTE_CONFIRM_DELAY_SEC`) и слияние (`MERGE_CONFIRM_DELAY_SEC`).
  - Выполнение: для споров и слияния реализованы 2 шага подтверждения с отложенной активацией финальной кнопки через соответствующие таймеры.
  - Код: `app/config.py` (`Config.dispute_confirm_delay_sec`, `Config.merge_confirm_delay_sec`), `.env.example`, `app/handlers/seller.py` (`seller_dispute_wait_confirm`, `_enable_dispute_confirm`), `app/handlers/manager.py` (`manager_merge_wait`, `_enable_merge_confirm`).
- [x] Аудит и логирование действий/событий (`audit_log`, `LOG_PATH`).
  - Выполнение: ключевые действия пользователей и системные операции пишутся в `audit_log`; runtime-логи пишутся в `LOG_PATH` (консоль + ротация файла).
  - Код: `app/db/sqlite.py` (`audit_log`, `log_audit`), `bot.py` (инициализация `RotatingFileHandler` по `config.log_path`), `app/handlers/seller.py`, `app/handlers/manager.py`.
- [x] Тихие часы: единая стратегия отложить/пропустить уведомления.
  - Выполнение: в плановых уведомлениях используется единая проверка quiet-time; в тихие часы отправка пропускается (defer/skip стратегия).
  - Код: `app/services/notifications.py` (`is_quiet_time`), `bot.py` (`scheduled_reminders`).

---

## Этап 0. UX-рамки и старт

Ссылка: [P132-P148](./dev-2-18-02-25.extracted.md#p132)

- [x] Убрать вопрос "Ваша компания зарегистрирована?" и показать меню для незарегистрированного пользователя.
  - Выполнение: заменен сценарий старта незарегистрированного пользователя на меню действий (регистрация/поддержка/правила), без ветки "Да/Нет".
  - Код: `app/handlers/start.py` (`show_seller_start`), `app/keyboards/seller.py` (`seller_start_menu`), `app/handlers/seller.py` (`seller_register_start`, `seller_fallback`).
- [x] Скрыть мировой рейтинг для `SELLER/ROP` (при этом расчет/таблицы сохранить).
  - Выполнение: кнопка мирового рейтинга удалена из меню SELLER/ROP; прямой вызов старого пункта теперь возвращает сообщение о недоступности.
  - Код: `app/keyboards/seller.py` (`seller_main_menu`), `app/handlers/seller.py` (`seller_global_rating`).
- [x] Ограничить лиги/челленджи рамками компании (`company_rank`).
  - Выполнение: расчет лиги в пользовательских экранах переключен на выборку внутри организации и ранжирование по `company_rank`.
  - Код: `app/services/leagues.py` (`compute_league` -> `rank_attr`), `app/handlers/start.py` (`show_seller_menu`), `app/handlers/seller.py` (`seller_profile`, `seller_company_rating`).
- [x] Выдача PDF "Правила и рекомендации" всем ролям (`RULES_FILE_PATH`).
  - Выполнение: добавлен конфиг `RULES_FILE_PATH`; реализована отправка PDF из меню SELLER/ROP и MANAGER c fallback в поддержку при отсутствии файла.
  - Код: `app/config.py` (`Config.rules_file_path`, `load_config`), `.env.example`, `app/keyboards/seller.py`, `app/keyboards/manager.py`, `app/handlers/seller.py` (`seller_rules`), `app/handlers/manager.py` (`manager_rules`).

---

## Этап 1. RBAC, регистрация, 2 пароля, лимит ROP, увольнения, база для ИНН/слияний

Ссылка: [P149-P204](./dev-2-18-02-25.extracted.md#p149)

- [x] Расширить схему БД: `company_groups`, `organizations` (2 пароля), `org_inns`, `users` (role/status/nickname), снапшоты в `sales_claims`.
  - Выполнение: схема БД переведена на целевую структуру этапа 1, добавлены новые таблицы/поля/индексы и снапшоты принадлежности в `sales_claims`.
  - Код: `app/db/sqlite.py` (`init_db`, `claim_turnover`).
- [x] Единый сценарий регистрации: ИНН -> выбор роли (`SELLER/ROP`) -> пароль роли -> ФИО -> никнейм (уникально в группе).
  - Выполнение: регистрация переработана на 5 шагов с выбором роли, проверкой role-specific пароля и обязательным никнеймом.
  - Код: `app/handlers/seller.py` (`SellerRegisterStates`, `seller_register_inn_input`, `seller_register_role_input`, `seller_register_password_input`, `seller_register_nickname`), `app/keyboards/seller.py` (`seller_role_menu`).
- [x] Корректная обработка повторной регистрации fired-пользователя и запрета active в другой компании.
  - Выполнение: добавлен запрет активной регистрации в другой компании; fired-пользователь может заново зарегистрироваться при соблюдении правил.
  - Код: `app/db/sqlite.py` (`has_active_registration_in_other_org`, `create_user`), `app/handlers/seller.py` (`_process_registration`, `seller_fallback`), `app/handlers/start.py` (`handle_start`).
- [x] Создание организации менеджером с двумя паролями (seller/rop) и заполнением `org_inns`.
  - Выполнение: менеджер при создании организации получает отдельные пароли `SELLER` и `ROP`, ИНН заносится в `org_inns`.
  - Код: `app/handlers/manager.py` (`manager_org_confirm_create`), `app/db/sqlite.py` (`create_org`).
- [x] Ограничение активных ROP по `ROP_LIMIT_PER_ORG`.
  - Выполнение: лимит из `.env` добавлен в конфиг и проверяется в регистрации роли `ROP`.
  - Код: `app/config.py` (`Config.rop_limit_per_org`, `load_config`), `.env.example`, `app/db/sqlite.py` (`count_active_rops_by_org`), `app/handlers/seller.py` (`_process_registration`).
- [x] Soft-увольнение/восстановление `SELLER` и `ROP` по правилам этапа.
  - Выполнение: для `ROP` добавлено увольнение/восстановление `SELLER`; для `MANAGER/ADMIN` добавлено увольнение/восстановление `ROP`; проверяется запрет восстановления при активной регистрации в другой компании.
  - Код: `app/db/sqlite.py` (`fire_user`, `restore_user`, `list_fired_sellers_by_org`, `list_fired_rops_by_org`), `app/handlers/seller.py` (`seller_fire_staff_open`, `seller_fire_staff_mode`, `seller_fire_staff_confirm`, `seller_restore_staff_confirm`), `app/handlers/manager.py` (`manager_fire_rop_menu`, `manager_fire_rop_org`, `manager_fire_rop_list`, `manager_fire_rop_confirm`, `manager_restore_rop_confirm`), `app/keyboards/manager.py` (`MANAGER_MENU_FIRE_ROP`), `app/keyboards/seller.py` (`SELLER_MENU_FIRE_STAFF`).

---

## Этап 2. BOT_LAUNCH_DATE и расчет по дате продажи

Ссылка: [P205-P215](./dev-2-18-02-25.extracted.md#p205)

- [x] В "Фиксация продажи" показывать только `turnover.period >= BOT_LAUNCH_DATE` и только по своей компании/группе.
  - Выполнение: добавлен конфиг даты запуска и фильтрация выдачи продаж по активным ИНН всей группы компании и по порогу `BOT_LAUNCH_DATE`; защита добавлена и в pick/confirm.
  - Код: `app/config.py` (`Config.bot_launch_date`, `load_config`), `.env.example`, `app/db/sqlite.py` (`count_unclaimed_turnover_by_inns`, `list_unclaimed_turnover_by_inns`), `app/handlers/seller.py` (`_get_seller_org_inns`, `_render_sales_list`, `seller_sales_pick`, `seller_sales_confirm`).
- [x] Все агрегаты рейтингов/челленджей считать по `chz_turnover.period`, а не по дате фиксации.
  - Выполнение: расчеты рейтингов и прогресса челленджей переведены на дату продажи из `chz_turnover.period`.
  - Код: `app/services/ratings.py` (`_totals_for_period`), `app/services/challenges.py` (`_last_month_volume`, `update_challenge_progress`).

---

## Этап 3. Пуши после sync 1C только при новых продажах

Ссылка: [P216-P231](./dev-2-18-02-25.extracted.md#p216)

- [x] `upsert_chz_turnover` возвращает `inserted_count` и список затронутых групп/ИНН.
  - Выполнение: upsert возвращает структуру с `upserted_count`, `inserted_count`, `affected_seller_inns`, `affected_company_group_ids`.
  - Код: `app/db/sqlite.py` (`upsert_chz_turnover`), `app/services/turnover_sync.py` (`SyncTurnoverResult`, `sync_turnover`).
- [x] Пуши отправляются только если `inserted_count > 0`.
  - Выполнение: отправка push встроена в отдельный сервисный шаг и срабатывает только при `inserted_count > 0`.
  - Код: `app/services/turnover_sync.py` (`send_sync_push_if_needed`), `app/handlers/manager.py` (`manager_sync_current_month`, `manager_sync_custom_range`), `bot.py` (`scheduled_sync`).
- [x] Пуши получают только релевантные активные `SELLER/ROP` затронутых компаний/групп.
  - Выполнение: получатели выбираются по `company_group_id IN affected_company_group_ids` и фильтру `status='active'`, `role IN ('seller','rop')`.
  - Код: `app/services/turnover_sync.py` (`send_sync_push_if_needed`).
- [x] Учитывать `SYNC_PUSH_ENABLED`.
  - Выполнение: добавлен флаг в конфиг и `.env.example`; при выключенном флаге пуши не отправляются.
  - Код: `app/config.py` (`Config.sync_push_enabled`, `load_config`), `.env.example`, `app/services/turnover_sync.py` (`send_sync_push_if_needed`).

---

## Этап 4. Оспаривание продаж и модерация ROP

Ссылка: [P232-P264](./dev-2-18-02-25.extracted.md#p232)

- [x] Добавить `sale_disputes` и привязку/статусы споров в `sales_claims`.
  - Выполнение: добавлена таблица `sale_disputes`; в `sales_claims` добавлены поля `dispute_status` и `dispute_id`; реализованы CRUD-операции споров и резолв.
  - Код: `app/db/sqlite.py` (`init_db`, `create_sale_dispute`, `cancel_dispute`, `resolve_dispute`, `list_*_dispute*`).
- [x] Меню "Оспорить продажу": доступные, мои спорные, споры со мной; корректная видимость для `SELLER` и `ROP`.
  - Выполнение: добавлен раздел `⚖️ Оспорить продажу` с тремя подменю; для `SELLER` скрываются свои фиксации, для `ROP` доступны и свои.
  - Код: `app/keyboards/seller.py` (`SELLER_MENU_DISPUTE`), `app/handlers/seller.py` (`seller_dispute_menu`, `seller_dispute_available`, `seller_dispute_my`, `seller_dispute_against`, `_render_available_disputes`).
- [x] 2-шаговое подтверждение оспаривания с таймером.
  - Выполнение: реализован шаг "Вы уверены?" и отложенное подтверждение через `DISPUTE_CONFIRM_DELAY_SEC` перед кнопкой финального подтверждения.
  - Код: `app/config.py` (`Config.dispute_confirm_delay_sec`), `.env.example`, `app/handlers/seller.py` (`_dispute_confirm_step1_keyboard`, `_enable_dispute_confirm`, `seller_dispute_wait_confirm`, `seller_dispute_confirm`).
- [x] Меню ROP "Спорные продажи": подтвердить/отклонить, включая кейс "РОП спорит сам с собой".
  - Выполнение: добавлен раздел `⚖️ Спорные продажи` для `ROP`; модерация поддерживает approve/reject и кейс self-dispute (инициатор=модератор) не блокируется.
  - Код: `app/keyboards/seller.py` (`SELLER_MENU_DISPUTE_MODERATE`), `app/handlers/seller.py` (`seller_dispute_moderate_menu`, `seller_dispute_mod_open`, `seller_dispute_mod_approve`, `seller_dispute_mod_reject`, `_resolve_dispute_moderator`), `app/db/sqlite.py` (`resolve_dispute`).
- [x] Уведомления по спору (`DISPUTE_PUSH_ENABLED`).
  - Выполнение: добавлен конфиг-флаг и push модератору при открытии спора с деталями продажи.
  - Код: `app/config.py` (`Config.dispute_push_enabled`), `.env.example`, `app/handlers/seller.py` (`seller_dispute_confirm`).

---

## Этап 5. Медкоины, финансы, вывод, помесячная детализация

Ссылка: [P265-P314](./dev-2-18-02-25.extracted.md#p265)

- [x] Добавить `medcoin_ledger` и `withdrawal_requests`.
  - Выполнение: в схему БД добавлены таблицы медкоинов и заявок на вывод с индексами; реализованы операции создания заявок, записей ledger и агрегатов по финансам.
  - Код: `app/db/sqlite.py` (`init_db`, `add_medcoin_ledger_entry`, `create_withdrawal_request`, `get_medcoin_totals`, `list_finance_months`).
- [x] Раздел "Финансы" для `SELLER/ROP`: available/frozen/earned/withdrawn.
  - Выполнение: добавлен раздел `💳 Финансы` с расчетом доступного баланса, заморозки в открытых спорах, общего заработка и общего вывода.
  - Код: `app/keyboards/seller.py` (`SELLER_MENU_FINANCE`, `seller_main_menu`), `app/handlers/seller.py` (`seller_finance_menu`, `_render_finance_menu`), `app/db/sqlite.py` (`get_dispute_frozen_amount`).
- [x] Поток вывода: реквизиты (история в `requisites_history`) -> подтверждение -> заявка -> уведомление менеджеру.
  - Выполнение: реализован сценарий вывода на карту: выбор текущих/новых реквизитов, валидация формата, двухшаговое подтверждение, создание `withdrawal_request` и push менеджеру организации.
  - Код: `app/handlers/seller.py` (`seller_finance_withdraw_card`, `seller_finance_requisites_new_input`, `seller_finance_amount_input`, `seller_finance_withdraw_confirm`, `_notify_manager_withdraw_request`), `app/utils/validators.py` (`validate_card_requisites_line`), `app/db/sqlite.py` (`get_latest_requisites`, `create_withdrawal_request`).
- [x] Экран "Моя статистика по месяцам" с пагинацией и детализацией метрик.
  - Выполнение: добавлен экран со списком месяцев (inline-пагинация через `INLINE_PAGE_SIZE`) и детализацией: earned/frozen/withdrawn, литры, место в рейтинге компании, число фиксаций и новых ИНН, breakdown по этапам бонусов.
  - Код: `app/config.py` (`Config.inline_page_size`, `load_config`), `.env.example`, `app/handlers/seller.py` (`seller_finance_months`, `seller_finance_month_open`, `_render_months_menu`, `_render_month_details`), `app/db/sqlite.py` (`get_month_ledger_totals`, `list_month_bonus_breakdown`, `get_month_claim_metrics`, `count_new_buyer_inns_for_user_month`, `get_company_rank_for_user_org_month`).

---

## Этап 6. Личные цели: бассейн, сверхзадачи, new buyer, среднемесячное

Ссылка: [P315-P368](./dev-2-18-02-25.extracted.md#p315)

- [x] Реализовать правило "бассейна" (`POOL_DAYS`, `POOL_MEDCOIN_PER_LITER`, `BOT_LAUNCH_DATE`).
  - Выполнение: добавлен расчет бонуса бассейна для фиксаций в окне `POOL_DAYS` от старта группы компании с учетом порога `BOT_LAUNCH_DATE`; начисление пересчитывается при изменении владельца фиксации после споров.
  - Код: `app/services/goals.py` (`_ensure_pool_state`, `_sync_pool_bonus`, `sync_claim_goals`), `app/db/sqlite.py` (`pool_state`, `upsert_pool_state_for_group`, `get_pool_state_for_group`, `claim_stage_awards`), `app/config.py`, `.env.example`.
- [x] Реализовать контур сверхзадач (включая Excel-импорт) и кандидатные статусы.
  - Выполнение: добавлены таблицы сверхзадач и кандидатов; реализована загрузка Excel (`region, inn, reward`), перевод задачи в pending/completed, фиксация победителя/проигравших кандидатов, отображение активных сверхзадач в "Личные цели".
  - Код: `app/db/sqlite.py` (`supertasks`, `supertask_candidates`, `create_supertask`, `upsert_supertask_candidate`, `set_supertask_assignment`, `close_supertask_with_winner`), `app/handlers/manager.py` (`manager_goals_upload_template_file`, `_build_supertask_template`), `app/services/goals.py` (`_sync_supertask_bonus`), `app/handlers/seller.py` (`seller_personal_goals_menu`).
- [x] Бонус за новый ИНН покупателя (`NEW_BUYER_BONUS`) с защитой от повторного начисления.
  - Выполнение: реализован бонус за первый покупательский ИНН в группе компании с хранением факта награждения и защитой от повторного начисления; при открытом споре начисление не выдается до финального статуса.
  - Код: `app/db/sqlite.py` (`new_buyer_awards`, `has_group_sales_before_period`, `upsert_new_buyer_award`, `get_new_buyer_award_by_buyer`), `app/services/goals.py` (`_sync_new_buyer_bonus`), `app/config.py`, `.env.example`.
- [x] Среднемесячные уровни: таблицы, правила, история изменений, 1 начисление за период уровня.
  - Выполнение: добавлены уровни среднемесячного (`avg_levels`) с историей (`avg_levels_history`) и таблицей факта награждений (`avg_level_awards`), обеспечено одно начисление за период уровня.
  - Код: `app/db/sqlite.py` (`avg_levels`, `avg_levels_history`, `avg_level_awards`, `create_avg_level`, `create_avg_level_award`, `has_avg_level_award`), `app/services/goals.py` (`sync_avg_levels_for_user`, `compute_avg_target`), `app/config.py`, `.env.example`.
- [x] Админ-панель управления правилами/уровнями + пуши сверхзадач.
  - Выполнение: добавлен админ-раздел "Личные цели (админ)" с управлением сверхзадачами и уровнями; реализованы push о новых сверхзадачах и о выполнении сверхзадачи.
  - Код: `app/keyboards/manager.py` (`MANAGER_MENU_GOALS_ADMIN`, `manager_goals_menu`, `manager_supertasks_menu`, `manager_avg_levels_menu`), `app/handlers/manager.py` (`manager_goals_admin_open`, `manager_goals_download_template`, `manager_goals_upload_template_file`, `manager_goals_avg_create_submit`), `app/handlers/seller.py` (`seller_sales_confirm`, `seller_dispute_mod_approve`, `seller_dispute_mod_reject`, `seller_dispute_cancel`), `app/config.py`, `.env.example`.

---

## Этап 7. ROP -> Мои сотрудники + профиль + Excel

Ссылка: [P369-P380](./dev-2-18-02-25.extracted.md#p369)

- [x] Меню ROP "Мои сотрудники" со списком активных продавцов и метриками.
  - Выполнение: добавлен раздел `👥 Мои сотрудники` для роли `ROP`; выводится список активных продавцов своей организации с литрами за текущий месяц и местом в рейтинге компании, есть inline-пагинация.
  - Код: `app/keyboards/seller.py` (`SELLER_MENU_MY_STAFF`, `seller_main_menu`), `app/handlers/seller.py` (`seller_my_staff_menu`, `seller_my_staff_page`, `_render_my_staff_page`, `_my_staff_list_menu`), `app/db/sqlite.py` (`list_active_sellers_with_metrics_current_month`, `count_active_sellers_by_org`).
- [x] Профиль сотрудника (без реквизитов).
  - Выполнение: реализована карточка сотрудника по клику из списка с метриками и рейтингами; реквизиты и их история не показываются.
  - Код: `app/handlers/seller.py` (`seller_my_staff_open`, `_my_staff_profile_menu`), `app/db/sqlite.py` (`get_user_month_metrics`, `get_company_rank_for_user_org_month`).
- [x] Excel-выгрузка продаж сотрудника за весь период с нужными полями.
  - Выполнение: добавлена выгрузка `.xlsx` по сотруднику за весь период с полями: период продажи, покупатель, ИНН покупателя, объем, номенклатура, дата фиксации, статус спора.
  - Код: `app/handlers/seller.py` (`seller_my_staff_export`), `app/services/staff_export.py` (`build_staff_sales_excel`), `app/db/sqlite.py` (`list_claimed_sales_for_user_all_time`).

---

## Этап 8. Смена ИНН компании

Ссылка: [P381-P391](./dev-2-18-02-25.extracted.md#p381)

- [x] Флоу смены ИНН (ADMIN/MANAGER): старый ИНН -> новый ИНН -> подтверждение.
  - Выполнение: добавлен отдельный сценарий `🔁 Смена ИНН` в меню менеджера/админа: выбор компании, ввод старого ИНН, ввод нового ИНН, явное подтверждение действия.
  - Код: `app/keyboards/manager.py` (`MANAGER_MENU_CHANGE_INN`, `manager_main_menu`), `app/handlers/manager.py` (`ManagerInnChangeStates`, `manager_change_inn_start`, `manager_change_inn_org_pick`, `manager_change_inn_old_input`, `manager_change_inn_new_input`, `manager_change_inn_confirm_yes`).
- [x] В `org_inns`: старый ИНН деактивируется (`active_to`), новый активируется (`active_from`).
  - Выполнение: реализована атомарная ротация ИНН: активная запись старого ИНН закрывается (`is_active=0`, `active_to`), новый ИНН активируется/добавляется с `active_from`; в `organizations.inn` записывается новый ИНН.
  - Код: `app/db/sqlite.py` (`rotate_org_inn`, `list_active_org_inns`, `is_active_inn_for_org`).
- [x] Статистика продолжает считаться по `company_group_id`.
  - Выполнение: смена ИНН не меняет `company_group_id` и не трогает историю `sales_claims`, поэтому расчеты и срезы по группе сохраняются без миграций.
  - Код: `app/db/sqlite.py` (`rotate_org_inn`), `app/services/ratings.py` (`_totals_for_period`), `app/services/goals.py` (`sync_claim_goals` и расчеты по `company_group_id_at_claim`).

---

## Этап 9. Слияние компаний

Ссылка: [P392-P403](./dev-2-18-02-25.extracted.md#p392)

- [x] Флоу слияния только для `ADMIN`: выбор мастер-компании и присоединяемых компаний.
  - Выполнение: добавлен admin-only сценарий `🔗 Слияние компаний` с выбором мастер-организации и мультивыбором присоединяемых компаний.
  - Код: `app/keyboards/manager.py` (`MANAGER_MENU_MERGE_ORGS`), `app/handlers/manager.py` (`AdminMergeStates`, `manager_merge_start`, `manager_merge_master_pick`, `manager_merge_join_toggle`).
- [x] Двойное подтверждение + таймер `MERGE_CONFIRM_DELAY_SEC`.
  - Выполнение: реализованы два этапа подтверждения; второй этап становится доступен после таймера `MERGE_CONFIRM_DELAY_SEC`.
  - Код: `app/config.py` (`Config.merge_confirm_delay_sec`, `load_config`), `.env.example`, `app/handlers/manager.py` (`manager_merge_step1`, `manager_merge_wait`, `_enable_merge_confirm`, `manager_merge_execute`).
- [x] Результат слияния: единая группа, перенос ИНН, merged/inactive для присоединенных организаций.
  - Выполнение: при слиянии пользователи и ИНН присоединяемых организаций переводятся в мастер-группу; присоединенные организации помечаются `merged/inactive` (`merged_into_org_id`, `is_active=0`), с дедупликацией ИНН в `org_inns`.
  - Код: `app/db/sqlite.py` (`merge_organizations`), `app/handlers/manager.py` (`manager_merge_execute`).

---

## Конфигурация `.env` (контроль внедрения ключей)

Ссылка: [P404-P483](./dev-2-18-02-25.extracted.md#p404)

- [x] Добавить/обновить ключи ролей и лимитов (`ADMIN_IDS`, `MANAGER_IDS`, `ROP_LIMIT_PER_ORG`).
- [x] Проверить ключи синка/пушей (`ONEC_*`, `SYNC_PUSH_ENABLED`, `DISPUTE_PUSH_ENABLED`, `SUPERTASK_PUSH_*`).
- [x] Проверить UI/таймеры/даты (`INLINE_PAGE_SIZE`, `RATING_WINDOW_SIZE`, `BOT_LAUNCH_DATE`, `DISPUTE_CONFIRM_DELAY_SEC`, `MERGE_CONFIRM_DELAY_SEC`).
- [x] Проверить ключи целей/бонусов (`POOL_*`, `NEW_BUYER_BONUS`, `AVG_*`, `MAX_AVG_LEVELS`).

---

## Журнал выполнения (заполняется по ходу работ)

Формат записи:
- Дата:
- Этап/пункт:
- Что сделано (кратко):
- Код-ссылки:
- Проверка (ручная/авто):

