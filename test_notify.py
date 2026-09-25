# -*- coding: utf-8 -*-
"""Проверка канала уведомлений.

Шлёт тестовое сообщение ботом в TARGET_CHAT_ID.
Запускать ПЕРВЫМ делом: если уведомления не доходят,
остальная часть системы бессмысленна.

Вся работа с Bot API — в notify.py, здесь только проверка.
"""

from datetime import datetime

import config
import notify


def main() -> None:
    config.require("BOT_TOKEN", "TARGET_CHAT_ID")

    text = (
        "✅ <b>Тестовое сообщение</b> от монитора воздушной обстановки.\n"
        f"Время отправки: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        "Если вы это видите — канал уведомлений работает."
    )

    ok, info = notify.send(text)
    if ok:
        print(f"Успех. Сообщение отправлено ({info}).")
    else:
        print("ОШИБКА отправки:")
        print("  " + info)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
