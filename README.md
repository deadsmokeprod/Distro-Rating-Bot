# MJOLNIR RATE DISTR — Telegram-бот рейтинга дистрибьютеров

Коротко: бот на **aiogram 3.x** для рейтинга дистрибьютеров и сотрудников, фиксации продаж, техподдержки через форум-треды Telegram и синхронизации продаж из 1С:ERP (HTTP). Данные хранятся в **SQLite**.

## Что умеет бот
- Роли и доступы (SUPER_ADMIN/ADMIN/MINI_ADMIN/USER).
- Регистрация дистрибьютеров и сотрудников по паролю организации.
- Рейтинги компании и личные рейтинги по месяцам.
- Фиксация продаж пользователями с защитой от гонок.
- Экспорт рейтинга в Excel.
- Техподдержка с форум-тредами в Telegram.
- Синхронизация продаж из 1С:ERP по HTTP.

---

# Что нужно подготовить заранее
1. **Telegram Bot Token** (через BotFather).
2. **Группа поддержки** в Telegram (с включённым Forum Topics) + права бота создавать темы.
3. **(Опционально)** Доступ к HTTP-сервису 1С:ERP (URL, логин/пароль).

---

# ПЕРВЫЙ ЗАПУСК на Windows 11 (для новичков)

> Все команды ниже выполняются в **PowerShell** в папке проекта.

1. Установите **Python 3.11+** с галочкой **“Add python to PATH”**.
2. Скачайте/распакуйте проект.
3. Откройте PowerShell в папке проекта.
4. Создайте виртуальное окружение:
   ```powershell
   python -m venv .venv
   ```
5. Активируйте его:
   ```powershell
   .\.venv\Scripts\activate
   ```
6. Установите зависимости:
   ```powershell
   pip install -r requirements.txt
   ```
7. Создайте `.env` по образцу `.env.example` и заполните значения.
8. Убедитесь, что файл **`bot/1cerpsql`** уже существует (он в репозитории).
9. Запустите бота:
   ```powershell
   python -m bot.main
   ```
10. Проверка: откройте бота в Telegram → `/start` → регистрация.

---

# ПОСЛЕДУЮЩИЕ ЗАПУСКИ
1. Откройте PowerShell в папке проекта.
2. Активируйте venv:
   ```powershell
   .\.venv\Scripts\activate
   ```
3. Запуск:
   ```powershell
   python -m bot.main
   ```

Или используйте:
```powershell
scripts\run_windows.bat
```

---

# ОБНОВЛЕНИЕ

**Если через git:**
```powershell
git pull
pip install -r requirements.txt
```

**Если без git:**
1. Скачайте новую версию проекта.
2. Перенесите в неё файлы:
   - `.env`
   - `data/database.sqlite3`

---

# РЕЗЕРВНОЕ КОПИРОВАНИЕ
Просто копируйте файл базы:
```
/data/database.sqlite3
```

---

# ТИПИЧНЫЕ ПРОБЛЕМЫ
- **“python не найден”** → переустановите Python с галочкой PATH.
- **“BOT_TOKEN invalid”** → проверьте токен.
- **“message thread not found / TOPIC_ID_INVALID”** → тред закрыт → создайте новое обращение.
- **Нет прав на создание тредов** → выдайте права боту в группе.
- **1С не отвечает** → проверьте `ERP_HTTP_URL`/доступ/логи.

---

# Где лежат логи
`logs/app.log`

---

# Быстрый запуск батниками
- `scripts/setup_windows.bat` — создаёт venv и ставит зависимости.
- `scripts/run_windows.bat` — запускает бота.

---

# Структура проекта
```
/bot
  main.py
  config.py
  routers/
    start.py
    rating.py
    sales_confirm.py
    profile.py
    settings.py
    support.py
  keyboards/
  middlewares/
  services/
    erp_client.py
    erp_sync.py
    rating_service.py
    excel_export.py
    time_utils.py
  db/
    engine.py
    models.py
    repo.py
    migrations.py
  data/
    database.sqlite3
  1cerpsql
  .env.example
  requirements.txt
  README.md
  scripts/
    setup_windows.bat
    run_windows.bat
```

---

# Важные параметры .env
Смотрите `.env.example`. Обязательно заполнить:
- `BOT_TOKEN`
- `BOT_SUPPORT_GROUP_ID`
- `SUPER_ADMIN_IDS`, `ADMIN_IDS`
- `MENU_CONFIG_JSON`
- `DB_PATH`
- `TIMEZONE`

---

# Команды 1С (файл 1cerpsql)
Запрос хранится в `bot/1cerpsql`. При необходимости адаптируйте `bot/services/erp_client.py` под нужный формат HTTP-пейлоада.
