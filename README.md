# Distro-Rating-Bot

Telegram-бот для учёта и подтверждения продаж, синхронизации данных из 1С и отображения единого мирового рейтинга.

## Быстрый запуск (Windows 11)

1) `git clone <repo-url>`
2) `cd Distro-Rating-Bot`
3) `py -3.12 -m venv .venv`
4) `\.\.venv\Scripts\Activate.ps1`
5) `pip install -r requirements.txt`
6) Скопировать `.env.example` → `.env` и заполнить переменные
7) `python -m bot.main`

## Как обновиться через git, если поменялась ветка

1) `git fetch --all --prune`
2) `git branch -a`
3) `git checkout -B <newbranch> origin/<newbranch>`
4) `git pull`
