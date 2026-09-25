# -*- coding: utf-8 -*-
"""Стенд воспроизведения: прогоняет РЕАЛЬНУЮ историю каналов через боевой код.

    python replay.py [папка] [--from "2026-09-23 22:00"] [--to "2026-09-24 08:00"]

Папка по умолчанию — data/night (файлы <канал>.json: id, date, text, reply_to).
Часы подменяются, отправка в Telegram перехвачена, файлы состояния — во
временной папке: ничего не уходит наружу и ничего не пишется в data/.

Смысл: не гадать, а ВИДЕТЬ, сколько сообщений и звуковых повторов радар
отправил бы за ночь налёта — и сравнивать «до» и «после» любой правки.
Настройки берутся облачные (data/night/cloud_settings.json), потому что
именно облако сейчас основной экземпляр.
"""

import argparse
import asyncio
import json
import sys
import tempfile
from collections import Counter
from datetime import datetime as _RealDT, timedelta, timezone
from pathlib import Path


class Clock:
    """Управляемое время: aware-UTC."""
    now_utc = _RealDT(2026, 1, 1, tzinfo=timezone.utc)


class FakeDT(_RealDT):
    @classmethod
    def now(cls, tz=None):
        t = Clock.now_utc
        return t.astimezone(tz) if tz else t.astimezone().replace(tzinfo=None)


class Msg:
    def __init__(self, d, channel):
        self.id = d["id"]
        self.channel = channel
        self.date = _RealDT.fromisoformat(d["date"])
        self.text = d["text"]
        self.reply_to = d.get("reply_to")
        self.reply_text = None


def load_messages(folder: Path, only=None):
    msgs = []
    for path in sorted(folder.glob("*.json")):
        if path.name == "cloud_settings.json":
            continue
        channel = path.stem
        if only and channel not in only:
            continue
        raw = json.loads(path.read_text(encoding="utf-8"))
        by_id = {d["id"]: d["text"] for d in raw}
        for d in raw:
            m = Msg(d, channel)
            if m.reply_to:
                m.reply_text = by_id.get(m.reply_to)
            msgs.append(m)
    msgs.sort(key=lambda m: m.date)
    return msgs


class ReplayClient:
    """Клиент, который отдаёт только то, что уже «случилось» к текущему моменту."""

    def __init__(self, msgs):
        self.by_channel = {}
        for m in msgs:
            self.by_channel.setdefault(m.channel, []).append(m)

    async def iter_messages(self, channel, limit=20):
        now = Clock.now_utc
        pool = [m for m in self.by_channel.get(channel, []) if m.date <= now]
        for m in sorted(pool, key=lambda x: x.date, reverse=True)[:limit]:
            yield m


def run(folder="data/night", start=None, end=None, only=None, quiet=False):
    """Возвращает словарь со статистикой и журналом отправленного."""
    import importlib
    if "--sample" in sys.argv:
        import sample_profile
        sample_profile.apply()
    import config
    import settings

    cloud = Path(folder) / "cloud_settings.json"
    if cloud.exists():
        cloud_cfg = json.loads(cloud.read_text(encoding="utf-8"))
        settings.load = lambda: {**settings.DEFAULTS, **cloud_cfg}
        config.reload_settings()

    import monitor
    import notify

    tmp = Path(tempfile.mkdtemp())
    for name in ("STATE_FILE", "ALARM_FILE", "DAILY_FILE",
                 "ACTIVE_THREAT_FILE", "PREV_FILE"):
        setattr(monitor, name, tmp / (name.lower() + ".json"))
    monitor.datetime = FakeDT

    sent = []

    def fake_send(text, silent=False):
        sent.append({"t": FakeDT.now(), "text": text, "silent": bool(silent)})
        return True, "ok"

    notify.send = fake_send
    notify.send_to = lambda *a, **k: (True, "ok")

    real_sleep = asyncio.sleep

    async def fake_sleep(sec, *a, **k):
        Clock.now_utc += timedelta(seconds=sec)
        await real_sleep(0)

    monitor.asyncio.sleep = fake_sleep

    msgs = load_messages(Path(folder), only)
    if start:
        msgs = [m for m in msgs if m.date >= start]
    if end:
        msgs = [m for m in msgs if m.date <= end]
    if not msgs:
        raise SystemExit("нет сообщений в выбранном окне")

    async def main():
        radar = monitor.Radar()
        radar.dedup = monitor.Dedup(config.DEDUP_WINDOW_MIN)
        radar.client = ReplayClient(msgs)
        Clock.now_utc = msgs[0].date
        next_crit = Clock.now_utc
        next_watch = Clock.now_utc
        for m in msgs:
            # проматываем время до сообщения, вызывая фоновые проверки
            while Clock.now_utc < m.date:
                nxt = min(m.date, next_crit, next_watch)
                if nxt > Clock.now_utc:
                    Clock.now_utc = nxt
                if Clock.now_utc >= next_crit:
                    await radar._critical_tick()
                    next_crit = Clock.now_utc + timedelta(seconds=10)
                if Clock.now_utc >= next_watch:
                    await radar._watch_tick()
                    next_watch = Clock.now_utc + timedelta(seconds=60)
                if Clock.now_utc >= m.date:
                    break
            if Clock.now_utc < m.date:
                Clock.now_utc = m.date
            await radar._ingest(m.channel, m.id, m.date, m.text, m.reply_text)
        # доработать хвост: 15 минут тишины
        end_t = Clock.now_utc + timedelta(minutes=15)
        while Clock.now_utc < end_t:
            Clock.now_utc += timedelta(seconds=10)
            await radar._critical_tick()
            if int(Clock.now_utc.timestamp()) % 60 < 10:
                await radar._watch_tick()
        return radar

    radar = asyncio.run(main())
    return {"sent": sent, "radar": radar, "messages": len(msgs)}


def classify_sent(item):
    """Тип отправленного: для сводной таблицы."""
    text = item["text"]
    head = text.split("\n", 1)[0]
    if head.startswith("❗️") and "повтор" in text:
        return "повтор"
    if "ЗАГРОЗА, СКОРІШЕ ЗА ВСЕ, МИНУЛА" in text:
        return "знято"
    if "ТРИВОГУ СКАСОВАНО" in text:
        return "скасовано"
    if head.startswith("🔴") or "УВАГА" in text[:300]:
        return "HIGH"
    if "Поруч" in text[:200]:
        return "MEDIUM"
    return "інше"


def summary(result, title=""):
    sent = result["sent"]
    kinds = Counter(classify_sent(s) for s in sent)
    loud = sum(1 for s in sent if not s["silent"])
    print(f"=== {title} ===")
    print(f"сообщений на входе: {result['messages']} | отправлено в чат: "
          f"{len(sent)} | со звуком: {loud}")
    for k, v in kinds.most_common():
        loud_k = sum(1 for s in sent if classify_sent(s) == k and not s["silent"])
        print(f"   {k:<10} {v:4}   (со звуком {loud_k})")
    per_hour = Counter()
    for s in sent:
        if not s["silent"]:
            per_hour[s["t"].strftime("%d %H:00")] += 1
    if per_hour:
        print("   звуковых по часам:", dict(sorted(per_hour.items())))
    return kinds, loud


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("folder", nargs="?", default="data/night")
    ap.add_argument("--from", dest="start")
    ap.add_argument("--to", dest="end")
    ap.add_argument("--show", action="store_true", help="показать каждое сообщение")
    ap.add_argument("--sample", action="store_true", help="вигаданий профіль (демо)")
    args = ap.parse_args()
    tz = timezone(timedelta(hours=3))
    start = _RealDT.fromisoformat(args.start).replace(tzinfo=tz) if args.start else None
    end = _RealDT.fromisoformat(args.end).replace(tzinfo=tz) if args.end else None
    res = run(args.folder, start, end)
    summary(res, "ВОСПРОИЗВЕДЕНИЕ")
    if args.show:
        for s in res["sent"]:
            first = s["text"].replace("\n", " ")[:110]
            print(f"{s['t']:%d %H:%M:%S} {'🔇' if s['silent'] else '🔔'} {first}")
