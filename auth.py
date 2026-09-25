# -*- coding: utf-8 -*-
"""Разовая авторизация Telethon.

Запускается один раз: создаёт файл сессии data/session_monitor.session.
После этого остальные скрипты входят без кода подтверждения.

ВАЖНО: заходить нужно ВТОРЫМ аккаунтом, не основным.
Скрипт печатает имя и username вошедшего аккаунта — проверьте их.
"""

import asyncio

from telethon import TelegramClient
from telethon.errors import (
    PhoneCodeInvalidError,
    PhoneNumberInvalidError,
    SessionPasswordNeededError,
)

import config


async def main() -> None:
    config.require("TG_API_ID", "TG_API_HASH", "TG_PHONE")

    client = TelegramClient(
        config.SESSION_PATH,
        config.api_id_int(),
        config.TG_API_HASH,
    )

    await client.connect()

    if await client.is_user_authorized():
        print("Сессия уже существует, повторная авторизация не нужна.")
    else:
        print(f"Отправляю код подтверждения на {config.TG_PHONE} ...")
        try:
            await client.send_code_request(config.TG_PHONE)
        except PhoneNumberInvalidError:
            raise SystemExit("Неверный номер телефона в TG_PHONE (нужен формат +380...).")

        # Код приходит в приложение Telegram, а не по SMS
        code = input("Код из Telegram: ").strip()
        try:
            await client.sign_in(phone=config.TG_PHONE, code=code)
        except PhoneCodeInvalidError:
            raise SystemExit("Код введён неверно. Запустите auth.py ещё раз.")
        except SessionPasswordNeededError:
            # Включена двухфакторная аутентификация — нужен облачный пароль.
            # getpass, чтобы пароль не отображался и не попадал в историю терминала.
            from getpass import getpass

            password = getpass("Пароль 2FA (ввод скрыт): ")
            await client.sign_in(password=password)

    me = await client.get_me()
    username = f"@{me.username}" if me.username else "(без username)"
    full_name = " ".join(filter(None, [me.first_name, me.last_name])) or "(без имени)"

    print("-" * 50)
    print("Авторизация успешна. Проверьте, что это ВТОРОЙ аккаунт:")
    print(f"  Имя:      {full_name}")
    print(f"  Username: {username}")
    print(f"  ID:       {me.id}")
    print(f"  Телефон:  +{me.phone}" if me.phone else "  Телефон:  (скрыт)")
    print(f"Файл сессии: {config.SESSION_PATH}.session")
    print("-" * 50)

    await client.disconnect()


if __name__ == "__main__":
    asyncio.run(main())
