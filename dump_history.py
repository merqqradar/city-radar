# -*- coding: utf-8 -*-
"""Выгрузка истории каналов за последние DUMP_DAYS дней.

Сохраняет только текст и метаданные. Медиа НЕ скачивается вообще.
Результат: data/dump_<channel>.json — список объектов
{id, date (ISO), text, link}.

Один недоступный канал не роняет скрипт: ошибка пишется в лог,
канал помечается как проблемный, работа продолжается.
"""

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone

from telethon import TelegramClient
from telethon.errors import (
    ChannelPrivateError,
    ChannelInvalidError,
    FloodWaitError,
    UsernameInvalidError,
    UsernameNotOccupiedError,
)

import config

# --- Логирование ------------------------------------------------------------
LOG_FILE = config.LOGS_DIR / "dump.log"
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger("dump")


def extract_text(message) -> str:
    """Текст сообщения: обычный текст или подпись к медиа."""
    # В Telethon message.text уже включает caption для медиа-сообщений,
    # но подстрахуемся на случай пустого значения.
    return (message.text or getattr(message, "message", "") or "").strip()


async def dump_channel(client: TelegramClient, username: str, cutoff: datetime) -> dict:
    """Выгружает один канал. Возвращает запись для итоговой сводки."""
    result = {
        "channel": username,
        "count": 0,
        "first": None,
        "last": None,
        "status": "ок",
    }
    items = []
    offset_id = 0          # с какого id продолжать (для восстановления после FloodWait)
    finished = False

    while not finished:
        try:
            async for msg in client.iter_messages(username, offset_id=offset_id, limit=None):
                offset_id = msg.id            # запоминаем прогресс

                if msg.date < cutoff:         # вышли за пределы периода
                    finished = True
                    break

                text = extract_text(msg)
                if not text:                  # чисто медийные посты без подписи пропускаем
                    continue

                items.append(
                    {
                        "id": msg.id,
                        "date": msg.date.astimezone(timezone.utc).isoformat(),
                        "text": text,
                        "link": f"https://t.me/{username}/{msg.id}",
                    }
                )
            else:
                finished = True               # цикл дошёл до конца истории

        except FloodWaitError as e:
            wait = e.seconds + 5
            log.warning("%s: FloodWait %s c — жду и продолжаю", username, e.seconds)
            await asyncio.sleep(wait)
            continue                          # продолжаем с сохранённого offset_id

        except (ChannelPrivateError, ChannelInvalidError) as e:
            result["status"] = f"ошибка: канал закрыт/недоступен ({type(e).__name__})"
            log.error("%s: канал закрыт или недоступен — пропускаю", username)
            return result

        except (UsernameNotOccupiedError, UsernameInvalidError):
            result["status"] = "ошибка: username не существует"
            log.error("%s: username не существует — пропускаю", username)
            return result

        except ValueError as e:
            # Telethon кидает ValueError, если не может разрешить entity
            result["status"] = f"ошибка: не удалось найти канал ({e})"
            log.error("%s: не удалось разрешить канал — пропускаю", username)
            return result

        except Exception as e:                # непредвиденное — тоже не роняем скрипт
            result["status"] = f"ошибка: {type(e).__name__}: {e}"
            log.exception("%s: непредвиденная ошибка — пропускаю", username)
            return result

    # Сохраняем в хронологическом порядке (от старых к новым)
    items.reverse()
    out = config.DATA_DIR / f"dump_{username}.json"
    out.write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")

    result["count"] = len(items)
    if items:
        result["first"] = items[0]["date"][:10]
        result["last"] = items[-1]["date"][:10]
    log.info("%s: сохранено %d сообщений -> %s", username, len(items), out.name)
    return result


async def main() -> None:
    config.require("TG_API_ID", "TG_API_HASH")
    cutoff = datetime.now(timezone.utc) - timedelta(days=config.DUMP_DAYS)
    log.info("Период выгрузки: с %s", cutoff.date())

    client = TelegramClient(config.SESSION_PATH, config.api_id_int(), config.TG_API_HASH)
    await client.connect()

    if not await client.is_user_authorized():
        raise SystemExit("Сессия не найдена. Сначала запустите: python auth.py")

    summary = []
    for i, username in enumerate(config.CHANNELS):
        log.info("--- %s (%d/%d)", username, i + 1, len(config.CHANNELS))
        summary.append(await dump_channel(client, username, cutoff))
        if i < len(config.CHANNELS) - 1:
            await asyncio.sleep(config.PAUSE_BETWEEN_CHANNELS)

    await client.disconnect()

    # --- Сводка -------------------------------------------------------------
    print()
    print("=" * 78)
    print(f"{'КАНАЛ':<22}{'СООБЩ.':>8}  {'ПЕРИОД':<26}СТАТУС")
    print("-" * 78)
    for r in summary:
        period = f"{r['first']} .. {r['last']}" if r["first"] else "—"
        print(f"{r['channel']:<22}{r['count']:>8}  {period:<26}{r['status']}")
    print("=" * 78)
    total = sum(r["count"] for r in summary)
    bad = [r["channel"] for r in summary if r["status"] != "ок"]
    print(f"Всего сообщений: {total}")
    if bad:
        print("Проблемные каналы: " + ", ".join(bad))
    print(f"Лог: {LOG_FILE}")


if __name__ == "__main__":
    asyncio.run(main())
