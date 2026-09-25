# -*- coding: utf-8 -*-
"""Резервная копия и восстановление рабочих файлов радара.

Один файл .zip, в котором лежит всё, что нельзя восстановить заново:
  .env                          секреты (api_hash, токен бота)
  data/session_monitor.session  авторизация Telegram
  data/settings.json            настройки
  data/status_msg.json          id закреплённого сообщения

Зачем отдельным файлом, а не внутри приложения: файл сессии даёт полный
доступ к аккаунту Telegram. Если зашить его в .app, то любой, кому вы
передадите приложение, получит доступ к вашему аккаунту. Поэтому копия —
отдельный файл, который вы храните сами.
"""

import zipfile
from pathlib import Path

import config

# Что кладём в копию: путь относительно BASE_DIR
BACKUP_ITEMS = [
    ".env",
    "data/session_monitor.session",
    "data/settings.json",
    "data/status_msg.json",
    "data/alarm.json",
]


def create(target: str) -> tuple:
    """Складывает рабочие файлы в zip. Возвращает (успех, описание)."""
    base = Path(config.BASE_DIR)
    saved = []
    try:
        with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as zf:
            for item in BACKUP_ITEMS:
                path = base / item
                if path.exists():
                    zf.write(path, item)
                    saved.append(item)
    except OSError as e:
        return False, f"не вдалося записати файл: {e}"

    if not saved:
        return False, "нічого зберігати — робочих файлів не знайдено"
    return True, f"збережено {len(saved)} файлів"


def restore(source: str) -> tuple:
    """Распаковывает копию в рабочую папку. Возвращает (успех, описание)."""
    base = Path(config.BASE_DIR)
    try:
        with zipfile.ZipFile(source) as zf:
            names = [n for n in zf.namelist() if n in BACKUP_ITEMS]
            if not names:
                return False, "це не схоже на резервну копію радара"
            for name in names:
                # Пути берём только из белого списка — распаковка чужого
                # архива не должна писать куда попало
                dest = base / name
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(zf.read(name))
                if name == ".env":
                    dest.chmod(0o600)      # секреты не для чужих глаз
    except (zipfile.BadZipFile, OSError) as e:
        return False, f"не вдалося прочитати копію: {e}"

    return True, f"відновлено {len(names)} файлів"
