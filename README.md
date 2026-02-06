# Distro-Rating-Bot

Telegram бот для подтверждения продаж и мирового рейтинга продавцов.

## Запуск на Windows 11

1) `git clone <repo_url>`
2) `cd Distro-Rating-Bot`
3) `py -3.12 -m venv .venv`
4) `./.venv/Scripts/Activate.ps1`
5) `pip install -r requirements.txt`
6) Скопируйте `.env.example` в `.env` и заполните значения
7) `python -m bot.main`

## Как обновиться через git, если поменялась ветка

1) `git fetch --all --prune`
2) `git branch -a`
3) `git checkout -B <newbranch> origin/<newbranch>`
4) `git pull`
