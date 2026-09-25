# -*- coding: utf-8 -*-
"""Приложение «Радар міста» — иконка в строке меню macOS.

Пока приложение открыто, радар слушает каналы и шлёт уведомления.
Терминал не нужен: запускается двойным кликом по «Радар міста.app».

В строке меню видно текущее состояние:
  🟢 — работает, тихо
  🔴 — недавно была тревога уровня HIGH
  ⏸  — пауза
  ⚠️ — ошибка (нет сети, бот не отвечает)
"""

import asyncio
import subprocess
import threading
from datetime import datetime

import rumps

import config
import geo
import gui
import monitor

# Сколько минут держать «тревожную» иконку после уведомления
ALERT_ICON_MINUTES = 10


class RadarApp(rumps.App):
    def __init__(self):
        super().__init__("🟢", quit_button=None)
        self.radar = monitor.Radar(on_alert=self._on_alert)
        self.loop = None
        self.stop_event = None

        # Пункты меню. Первые три — только показывают состояние.
        self.item_status = rumps.MenuItem("Запуск…")
        self.item_last = rumps.MenuItem("Останнє: —")
        self.item_stats = rumps.MenuItem("Повідомлень: 0")
        self.item_pause = rumps.MenuItem("Пауза", callback=self.toggle_pause)
        self.window = None

        self.menu = [
            rumps.MenuItem("Відкрити вікно", callback=self.open_window),
            None,
            self.item_status,
            self.item_last,
            self.item_stats,
            None,
            self.item_pause,
            rumps.MenuItem("Оновити закріплений статус", callback=self.refresh_status),
            rumps.MenuItem("Смарт-звіт у канал", callback=self.send_review),
            rumps.MenuItem("Тиша на годину", callback=self.toggle_mute),
            rumps.MenuItem("Звіт за сьогодні в канал", callback=self.send_report),
            rumps.MenuItem("Звіт за вчора в канал",
                           callback=self.send_report_yesterday),
            rumps.MenuItem("Тестове повідомлення", callback=self.send_test),
            None,
            rumps.MenuItem("Показати лог", callback=self.open_log),
            rumps.MenuItem("Налаштування (config.py)", callback=self.open_config),
            None,
            rumps.MenuItem("Вийти", callback=self.quit_app),
        ]

        self._start_radar()
        # Обновление меню раз в 5 секунд — из главного потока
        rumps.Timer(self._refresh, 5).start()

    # --- Запуск радара в фоновом потоке -------------------------------------
    def _start_radar(self) -> None:
        def worker():
            self.loop = asyncio.new_event_loop()
            asyncio.set_event_loop(self.loop)
            self.stop_event = asyncio.Event()
            try:
                self.loop.run_until_complete(self.radar.run(self.stop_event))
            except SystemExit as e:
                self.title = "⚠️"
                self.item_status.title = str(e)[:60]
            except Exception as e:                      # noqa: BLE001
                self.title = "⚠️"
                self.item_status.title = f"Помилка: {type(e).__name__}"
                monitor.log.exception("Радар упал")

        threading.Thread(target=worker, daemon=True, name="radar").start()

    def restart_radar(self) -> None:
        """Перезапускает радар — после смены списка каналов.

        Telethon подписывается на каналы при подключении, поэтому
        новый список подхватывается только новым соединением.
        """
        old_loop, old_stop = self.loop, self.stop_event
        if old_loop and old_stop:
            old_loop.call_soon_threadsafe(old_stop.set)

        counts, stats = self.radar.counts, self.radar.stats
        self.radar = monitor.Radar(on_alert=self._on_alert)
        self.radar.counts, self.radar.stats = counts, stats   # счётчики не теряем
        self.item_status.title = "Перезапуск…"
        self._start_radar()

    # --- Реакция на отправленное уведомление --------------------------------
    def _on_alert(self, level: str, headline: str, text: str) -> None:
        # Вызывается из фонового потока — только записываем данные,
        # интерфейс обновит таймер в главном потоке.
        self.item_last.title = f"Останнє: {headline}"

    # --- Периодическое обновление меню --------------------------------------
    def _refresh(self, _timer) -> None:
        r = self.radar

        if not r.running:
            self.title = "⚠️"
            self.item_status.title = "Не працює"
        elif r.paused:
            self.title = "⏸"
            self.item_status.title = "Пауза — сповіщення не надсилаються"
        else:
            recent = (r.last_alert and r.last_alert[1] == "HIGH" and
                      (datetime.now() - r.last_alert[0]).total_seconds()
                      < ALERT_ICON_MINUTES * 60)
            # 🟡 — объявлена тревога по району, но конкретной угрозы [МІСТО] нет
            self.title = "🔴" if recent else ("🟡" if r.alarm else "🟢")
            if r.alarm:
                self.item_status.title = f"{r.alarm[0]} з {r.alarm[1]:%H:%M}"
            else:
                self.item_status.title = (
                    f"Працює · {len(config.CHANNELS)} каналів"
                    + (" · сусіди будять" if config.HIGH_INCLUDES_NEIGHBORS
                       else ""))

        if r.last_alert:
            when, _level, headline = r.last_alert
            self.item_last.title = f"Останнє: {headline} ({when.strftime('%H:%M')})"

        if self.window is not None:
            self.window.refresh()

        s = r.stats
        self.item_stats.title = (f"Переглянуто {s['seen']} · надіслано {s['sent']}"
                                 f" · дублів {s['dupes']}"
                                 + (f" · помилок {s['errors']}" if s["errors"] else ""))

    # --- Пункты меню ---------------------------------------------------------
    def toggle_pause(self, sender) -> None:
        self.radar.paused = not self.radar.paused
        sender.title = "Відновити" if self.radar.paused else "Пауза"
        self._refresh(None)

    def open_window(self, _sender) -> None:
        """Показывает главное окно (создаётся при первом открытии)."""
        if self.window is None:
            self.window = gui.RadarWindow.alloc().initWithApp_(self)
        self.window.show()

    def run_review(self, _sender) -> None:
        """Смарт-перевірка каналів на вимогу з застосунку."""
        if not (self.loop and self.radar.running):
            return

        async def job():
            import config as cfg

            if cfg.SMART_REVIEW:
                self.radar.review = await self.radar._smart_review()
            self.radar._wake_reason = "кнопка"
            if self.radar._status_dirty:
                self.radar._status_dirty.set()

        asyncio.run_coroutine_threadsafe(job(), self.loop)

    def cancel_alarm(self) -> None:
        """Скасувати хибну тривогу, не вимикаючи радар."""
        if not (self.loop and self.radar.running):
            return

        async def job():
            self.radar.mode_message = await self.radar.cancel_alarm(
                "із застосунку")

        asyncio.run_coroutine_threadsafe(job(), self.loop)

    def set_mode(self, online: bool) -> None:
        """Перемикає локально/онлайн. Результат читає gui.refresh() з radar.mode_message."""
        if not (self.loop and self.radar.running):
            return

        async def job():
            self.radar.mode_message = await self.radar.set_mode(online)

        asyncio.run_coroutine_threadsafe(job(), self.loop)

    def send_review(self, _sender) -> None:
        """Смарт-звіт окремим повідомленням у канал."""
        if self.loop and self.radar.running:
            asyncio.run_coroutine_threadsafe(
                self.radar.send_review_to_channel(), self.loop)

    def refresh_status(self, _sender) -> None:
        """Внеплановое обновление закреплённого сообщения."""
        if self.loop and self.radar._status_dirty:
            self.loop.call_soon_threadsafe(self.radar._status_dirty.set)

    def toggle_mute(self, _sender) -> None:
        """Тишина на час: сообщения приходят, но без звука."""
        from datetime import timedelta

        radar = self.radar
        if radar.is_muted():
            radar.mute_until = None
        else:
            radar.mute_until = datetime.now() + timedelta(hours=1)
        self._refresh(None)

    def send_report_yesterday(self, _sender) -> None:
        self.send_report(None, day="yesterday")

    def send_report(self, _sender, day: str = "today") -> None:
        """Отправляет в канал отчёт за сутки. Без звука."""
        import notify

        def worker():
            ok, info = notify.send(self.radar.build_report(day), silent=True)
            rumps.notification(f"Радар {geo.main_name()}",
                               "Звіт надіслано" if ok else "Помилка", info)

        threading.Thread(target=worker, daemon=True).start()

    def send_test(self, _sender) -> None:
        import notify

        ok, info = notify.send(
            f"🧪 <b>Перевірка зв'язку</b>\nРадар {geo.main_name()} працює, "
            f"канал сповіщень доступний.\n{datetime.now().strftime('%H:%M:%S')}")
        rumps.notification(f"Радар {geo.main_name()}",
                           "Тест надіслано" if ok else "Помилка",
                           info if ok else info)

    def open_log(self, _sender) -> None:
        subprocess.run(["open", "-a", "Console", str(monitor.LOG_FILE)], check=False)

    def open_config(self, _sender) -> None:
        subprocess.run(["open", "-e", str(config.BASE_DIR / "config.py")], check=False)

    def quit_app(self, _sender) -> None:
        # Аккуратно гасим радар, чтобы состояние дедупликации сохранилось
        if self.loop and self.stop_event:
            self.loop.call_soon_threadsafe(self.stop_event.set)
        rumps.quit_application()


if __name__ == "__main__":
    RadarApp().run()
