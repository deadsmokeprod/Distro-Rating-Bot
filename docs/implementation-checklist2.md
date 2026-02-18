# История изменений по итогам аудита (минимально-инвазивные правки)

Дата: 2026-02-18

## Цель

Закрыть найденные в ревью логические риски без ломки текущих пользовательских сценариев.

## Внесенные изменения

- [x] Бонус `pool_bonus` переведен на расчет по дате продажи (`period`), а не по дате фиксации (`claimed_at`).
  - Что сделано: в проверке окна бассейна используется `claim_period`.
  - Код: `app/services/goals.py` (`_sync_pool_bonus`).

- [x] Усилена устойчивость фиксации продажи к гонкам.
  - Что сделано: добавлена отдельная обработка `sqlite3.IntegrityError` в потоке подтверждения продажи (`sale_confirm`), чтобы корректно сообщать, что продажа уже зафиксирована другим пользователем.
  - Код: `app/handlers/seller.py` (`seller_sales_confirm`).

- [x] Разделена критическая операция фиксации и пост-обновления.
  - Что сделано: после успешного `claim_turnover` пост-этапы (пересчет целей/рейтинга/челленджа/аудит) выполняются отдельно; при их ошибке продажа остается зафиксированной и пользователь получает честный статус.
  - Код: `app/handlers/seller.py` (`seller_sales_confirm`).

- [x] Закрыты утечки временных файлов `.xlsx`.
  - Что сделано: добавлено удаление временных файлов после отправки/обработки в `finally`.
  - Код:
    - `app/handlers/seller.py` (`seller_my_staff_export`);
    - `app/handlers/manager.py` (`manager_goals_download_template`, `manager_goals_upload_template_file`, `manager_export_ratings_run`).

- [x] Добавлен безопасный разбор callback-данных в менеджерских экранах организаций.
  - Что сделано: добавлены проверки `callback.message`, длины `split(':')` и `ValueError`.
  - Код: `app/handlers/manager.py` (`manager_org_list_page`, `manager_org_open`).

- [x] Синхронизирована логика reminder по незакрепленным продажам с основной логикой фиксации.
  - Что сделано:
    - напоминания отправляются только активным `seller`;
    - подсчет незакрепленных продаж идет по ИНН всей группы компании;
    - учитывается порог `BOT_LAUNCH_DATE`.
  - Код: `bot.py` (`scheduled_reminders`).

- [x] Корректное завершение планировщика при остановке бота.
  - Что сделано: `scheduler.shutdown(wait=True)`.
  - Код: `bot.py` (`main` -> `finally`).

## Примечания

- Изменения выполнены точечно и не меняют структуру меню/ролей/состояний FSM.
- Основные пользовательские сценарии (фиксация, споры, экспорт, менеджерские экраны) сохранены.

---

## Дополнение: закрытие уязвимостей (Critical/High/Medium/Low)

Дата: 2026-02-18

### Critical

- [x] Закрыт обход tenant-изоляции в финальном подтверждении спора.
  - Что сделано: в `disp_confirm` добавлены повторные проверки принадлежности `claim` к `company_group_id`, запрет self-dispute для `seller` и блок на уже открытый спор.
  - Код: `app/handlers/seller.py` (`seller_dispute_confirm`).

- [x] Закрыт RBAC-обход в confirm-шаге увольнения/восстановления РОП.
  - Что сделано: перед `fire_user/restore_user` добавлены проверки `_can_access_org` и проверка принадлежности `tg_user_id` выбранной организации.
  - Код: `app/handlers/manager.py` (`manager_fire_rop_confirm`, `manager_restore_rop_confirm`).

- [x] Закрыт риск double-spend при выводе средств.
  - Что сделано: проверка баланса и создание `withdrawal_request` выполняются атомарно в `BEGIN IMMEDIATE`; при недостатке средств возвращается `ValueError`.
  - Код: `app/db/sqlite.py` (`create_withdrawal_request`), `app/handlers/seller.py` (`seller_finance_withdraw_confirm`).

### High

- [x] Включен режим private-only для всех пользовательских/менеджерских роутеров.
  - Что сделано: добавлен `PrivateChatFilter` и подключен в `start`, `seller`, `manager` роутеры.
  - Код: `app/handlers/filters.py` (`PrivateChatFilter`), `app/handlers/start.py`, `app/handlers/seller.py`, `app/handlers/manager.py`.

- [x] Добавлена защита от brute-force/abuse на критичных шагах.
  - Что сделано: in-memory rate limit для регистрации (ИНН/пароль), открытия споров и подтверждения вывода.
  - Код: `app/utils/rate_limit.py`, `app/handlers/seller.py`.

- [x] Снижен риск утечки секретов в истории чата менеджера.
  - Что сделано: пароли при создании/сбросе отправляются отдельным сообщением с авто-удалением по TTL.
  - Код: `app/handlers/manager.py` (`_send_secret_with_ttl`, `manager_org_confirm_create`, `manager_org_reset_confirm`).

- [x] Защищено хранение реквизитов (at-rest) с обратной совместимостью.
  - Что сделано: добавено прозрачное шифрование/дешифрование для `requisites_history` и `withdrawal_requests.requisites_text`; старые plaintext-записи продолжают читаться.
  - Код: `app/db/sqlite.py` (`_encrypt_sensitive`, `_decrypt_sensitive`, `add_requisites`, `get_requisites_history`, `get_latest_requisites`, `create_withdrawal_request`).

- [x] Закрыта эскалация роли через повторную регистрацию.
  - Что сделано: в регистрации запрещена смена роли активного пользователя внутри одной организации; на уровне `create_user` роль обновляется только если прежний статус `fired`.
  - Код: `app/handlers/seller.py` (`_process_registration`), `app/db/sqlite.py` (`create_user`).

### Medium

- [x] Усилена атомарность открытия спора.
  - Что сделано: `create_sale_dispute` переведен в `BEGIN IMMEDIATE`; claim читается внутри транзакции, `sales_claims` обновляется условно и проверяется `rowcount`.
  - Код: `app/db/sqlite.py` (`create_sale_dispute`).

- [x] Усилена атомарность разрешения спора.
  - Что сделано: в `resolve_dispute` добавлена проверка `rowcount` при `UPDATE ... status='open'`; при 0 изменений функция возвращает `False`.
  - Код: `app/db/sqlite.py` (`resolve_dispute`).

### Low

- [x] Убран динамический SQL для обновления паролей организации.
  - Что сделано: `update_org_password` переведен на два статических параметризованных запроса (seller/rop).
  - Код: `app/db/sqlite.py` (`update_org_password`).

### Примечания по совместимости

- Все изменения внедрены точечно, без изменения структуры меню и основных FSM-сценариев.
- Шифрование реквизитов реализовано прозрачно: чтение старых данных сохраняется, новые записи защищаются автоматически.
