# MJOLNIR RATE DISTR

Telegram-бот для рейтинга дистрибьюторов и сотрудников на основе данных 1С:ERP, с поддержкой через форум-треды Telegram и хранением данных в SQLite.

## Возможности
- Регистрация дистрибьютера/продавца по ИНН и паролю организации.
- Рейтинги: личный, внутри компании, общий (с обезличиванием конкурентов для MINI_ADMIN/USER).
- Фиксация продаж (с защитой от гонок и дедупликацией).
- Экспорт рейтинга в Excel (ADMIN/SUPER_ADMIN).
- Автосинхронизация 1С:ERP (еженедельно) + ручной запуск.
- Техподдержка через форум-треды Telegram.
- Логи: файл `logs/app.log` + таблица `audit_log`.

## Что нужно подготовить заранее
1. **Telegram Bot Token** (BotFather).
2. **ID группы поддержки** с включёнными Forum Topics + права бота на создание/удаление тем.
3. (Опционально) **данные доступа к HTTP-сервису 1С**.

## Первый запуск на Windows 11 (пошагово)
1. Установите Python 3.11+ с галочкой **“Add python to PATH”**.
2. Скачайте и распакуйте проект.
3. Откройте PowerShell в папке проекта.
4. Создайте виртуальное окружение:
   ```powershell
   python -m venv .venv
   ```
5. Активируйте виртуальное окружение:
   ```powershell
   .\.venv\Scripts\activate
   ```
6. Установите зависимости:
   ```powershell
   pip install -r requirements.txt
   ```
7. Создайте файл `.env` из `.env.example` и заполните значения.
8. Убедитесь, что файл `1cerpsql` находится в корне проекта (уже в репозитории).
9. Запуск бота:
   ```powershell
   python -m bot.main
   ```
10. Проверка: откройте бота в Telegram → `/start` → регистрация.

## Последующие запуски
- Откройте папку проекта → активируйте `.venv` → `python -m bot.main`.
- Или используйте:
  ```powershell
  scripts\run_windows.bat
  ```

## Обновление проекта
- Если используете git:
  ```powershell
  git pull
  pip install -r requirements.txt
  ```
- Если без git: скачайте новую версию и перенесите `data/database.sqlite3` и `.env`.

## Резервное копирование
- Достаточно скопировать файл `data/database.sqlite3`.

## Типичные проблемы и решения
- **“python не найден”** → переустановите Python с включённым PATH.
- **“BOT_TOKEN invalid”** → проверьте токен BotFather.
- **“message thread not found / TOPIC_ID_INVALID”** → тред был закрыт → начните новое обращение.
- **Нет прав на создание тредов** → выдайте права боту в группе поддержки.
- **1С не отвечает** → проверьте `ERP_HTTP_URL`, доступ и логи `logs/app.log`.

## Скрипты для Windows
- `scripts/setup_windows.bat` — создать `.venv` и установить зависимости.
- `scripts/run_windows.bat` — активировать окружение и запустить бота.

## Структура проекта
```
/bot
  main.py
  config.py
  routers/
  keyboards/
  middlewares/
  services/
  db/
  data/
  1cerpsql
  .env.example
  requirements.txt
  README.md
  scripts/
```

## Логи
- Основной лог: `logs/app.log`.
- Аудит-лог в SQLite: таблица `audit_log`.
