# -*- coding: utf-8 -*-
"""Окно приложения «Радар міста».

Нативное окно macOS: карточка состояния, кнопки действий и настройки,
разложенные по раскрывающимся блокам. У каждой настройки — кнопка «?»
с кратким пояснением.

Показываются только те настройки, которые действительно работают.
"""

import subprocess
import threading
import time
from datetime import datetime

import objc
from AppKit import (
    NSAlert, NSApplication, NSBackingStoreBuffered, NSBezelStyleRounded,
    NSBox, NSButton, NSColor, NSFont, NSMakeRect, NSSwitch, NSSwitchButton,
    NSTextField, NSCenterTextAlignment, NSForegroundColorAttributeName,
    NSTitledWindowMask, NSClosableWindowMask, NSMiniaturizableWindowMask,
    NSResizableWindowMask, NSSavePanel, NSOpenPanel, NSScreen, NSScrollView,
    NSTabView, NSTabViewItem, NSTextView, NSView, NSViewHeightSizable, NSViewMinXMargin,
    NSViewWidthSizable, NSWindow, NSLeftTextAlignment,
)
from Foundation import NSObject, NSAttributedString

import backup
import config
import geo
import settings
import status as status_mod

WIDTH = 520          # начальная ширина; окно тянется мышью
MIN_WIDTH = 460
PAD = 18
ROW = 28            # высота строки настройки
HEADER_H = 30       # высота заголовка раскрывающегося блока
CARD_H = 118        # высота карточки состояния (растёт, когда открыт отчёт)
CARD_H_OPEN = 330

HELP_BEZEL = 9      # NSBezelStyleHelpButton — круглая кнопка «?»
DISCLOSURE_OPEN, DISCLOSURE_SHUT = "▾", "▸"


class Flipped(NSView):
    """Вид с началом координат сверху — так вертикальную раскладку
    считать в разы проще, чем в родной системе координат Cocoa."""

    def isFlipped(self):
        return True


def _text(cls, frame):
    f = cls.alloc().initWithFrame_(frame)
    return f


def label(text, x, y, w, h=18, size=12, bold=False, color=None, align=None):
    f = _text(NSTextField, NSMakeRect(x, y, w, h))
    f.setStringValue_(text)
    f.setBezeled_(False)
    f.setDrawsBackground_(False)
    f.setEditable_(False)
    f.setSelectable_(False)
    f.setFont_(NSFont.boldSystemFontOfSize_(size) if bold
               else NSFont.systemFontOfSize_(size))
    if color:
        f.setTextColor_(color)
    if align is not None:
        f.setAlignment_(align)
    return f


def field(value, x, y, w, h=22):
    f = _text(NSTextField, NSMakeRect(x, y, w, h))
    f.setStringValue_(value)
    f.setFont_(NSFont.systemFontOfSize_(12))
    return f


def text_area(value, x, y, w, h):
    """Многострочное поле с прокруткой — для списков, которые растут."""
    scroll = NSScrollView.alloc().initWithFrame_(NSMakeRect(x, y, w, h))
    scroll.setHasVerticalScroller_(True)
    scroll.setBorderType_(2)                       # NSBezelBorder
    scroll.setAutoresizingMask_(NSViewWidthSizable)

    view = NSTextView.alloc().initWithFrame_(NSMakeRect(0, 0, w, h))
    view.setFont_(NSFont.userFixedPitchFontOfSize_(11))
    view.setString_(value or "")
    view.setRichText_(False)
    view.setAutomaticQuoteSubstitutionEnabled_(False)
    view.setMinSize_((0, 0))
    view.setMaxSize_((100000, 100000))
    view.setVerticallyResizable_(True)
    view.setHorizontallyResizable_(False)
    view.setAutoresizingMask_(NSViewWidthSizable)
    view.textContainer().setWidthTracksTextView_(True)
    scroll.setDocumentView_(view)
    return scroll, view


def button(title, x, y, w, h, target, action, tag=0):
    b = NSButton.alloc().initWithFrame_(NSMakeRect(x, y, w, h))
    b.setTitle_(title)
    b.setBezelStyle_(NSBezelStyleRounded)
    b.setTarget_(target)
    b.setAction_(action)
    b.setTag_(tag)
    return b


def checkbox(title, x, y, w, target, action):
    b = NSButton.alloc().initWithFrame_(NSMakeRect(x, y, w, 20))
    b.setButtonType_(NSSwitchButton)
    b.setTitle_(title)
    b.setFont_(NSFont.systemFontOfSize_(12))
    b.setTarget_(target)
    b.setAction_(action)
    return b


def help_button(x, y, target, tag):
    b = NSButton.alloc().initWithFrame_(NSMakeRect(x, y, 21, 21))
    b.setBezelStyle_(HELP_BEZEL)
    b.setTitle_("")
    b.setTarget_(target)
    b.setAction_("showHelp:")
    b.setTag_(tag)
    return b


def autosize(container):
    """Расставляет правила растягивания дочерним элементам.

    Широкие поля и надписи тянутся вместе с окном, круглые кнопки «?»
    прижимаются к правому краю. Без этого при растягивании окна
    содержимое остаётся узким, а «?» уезжает за границу.
    """
    for view in container.subviews():
        frame = view.frame()
        # К правому краю прижимаем только круглые кнопки «?».
        # Раньше сюда попадали и короткие подписи «хв», «до», «год» —
        # они улетали вправо, отрываясь от своих полей.
        if (view.isKindOfClass_(NSButton) and frame.size.width <= 24
                and frame.size.height <= 24):
            view.setAutoresizingMask_(NSViewMinXMargin)
        elif frame.size.width >= 150:
            view.setAutoresizingMask_(NSViewWidthSizable)   # тянется по ширине
        else:
            view.setAutoresizingMask_(0)                    # стоит на месте


class RadarWindow(NSObject):
    """Главное окно приложения."""

    def initWithApp_(self, app):
        self = objc.super(RadarWindow, self).init()
        if self is None:
            return None
        self.app = app
        self.help_keys = []          # tag -> ключ в settings.HELP
        self.sections = []           # [{"title","btn","view","h","open"}]
        self.channel_fields = []
        self.width = WIDTH
        self._build()
        return self

    # ======================================================================
    #  Построение
    # ======================================================================
    @objc.python_method
    def _build(self):
        style = (NSTitledWindowMask | NSClosableWindowMask
                 | NSMiniaturizableWindowMask | NSResizableWindowMask)
        self.window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(0, 0, WIDTH, 600), style, NSBackingStoreBuffered, False)
        self.window.setTitle_(f"Радар {geo.main_name()} {config.VERSION}")
        self.window.setReleasedWhenClosed_(False)
        self.window.setMinSize_((MIN_WIDTH, 520))
        self.window.setDelegate_(self)

        # Содержимое кладём в прокручиваемый вид: с раскрытыми блоками
        # окно выше экрана ноутбука, и без прокрутки часть настроек
        # оказалась бы недоступной.
        self.scroll = NSScrollView.alloc().initWithFrame_(
            NSMakeRect(0, 0, WIDTH, 600))
        self.scroll.setHasVerticalScroller_(True)
        self.scroll.setDrawsBackground_(False)
        self.scroll.setAutohidesScrollers_(True)
        self.scroll.setAutoresizingMask_(NSViewWidthSizable | NSViewHeightSizable)

        self.root = Flipped.alloc().initWithFrame_(NSMakeRect(0, 0, WIDTH, 600))
        self.scroll.setDocumentView_(self.root)
        self.window.setContentView_(self.scroll)

        self._build_card()
        self._build_actions()
        self._build_tabs()
        self._build_footer()

        self._load_settings()
        self._layout()
        self.window.center()

    # --- Карточка состояния -------------------------------------------------
    @objc.python_method
    def _build_card(self):
        card = NSBox.alloc().initWithFrame_(
            NSMakeRect(PAD, PAD, WIDTH - 2 * PAD, CARD_H))
        card.setBoxType_(4)                     # NSBoxCustom
        card.setBorderWidth_(0)
        card.setCornerRadius_(10)
        card.setFillColor_(NSColor.controlBackgroundColor())
        card.setContentViewMargins_((0, 0))
        self.card = card

        inner = Flipped.alloc().initWithFrame_(
            NSMakeRect(0, 0, WIDTH - 2 * PAD, CARD_H))
        card.setContentView_(inner)

        self.lbl_state = label("Запуск…", 14, 12, WIDTH - 2 * PAD - 28, 28,
                               size=21, bold=True)
        inner.addSubview_(self.lbl_state)

        self.lbl_sub = label("", 14, 42, WIDTH - 2 * PAD - 28, 18, size=11,
                             color=NSColor.secondaryLabelColor())
        inner.addSubview_(self.lbl_sub)

        self.lbl_last = label("Останнє: —", 14, 66, WIDTH - 2 * PAD - 28, 18,
                              size=12)
        inner.addSubview_(self.lbl_last)

        # Раскрывающийся отчёт за сегодня вместо разноцветных кружочков:
        # цифры без подписей всё равно никто не помнил.
        self.btn_toggle_report = button("▸ Звіт за сьогодні", 12, 86, 194, 22,
                                        self, "toggleReport:")
        self.btn_toggle_report.setBezelStyle_(1)
        inner.addSubview_(self.btn_toggle_report)
        self.btn_report_refresh = button("Оновити", 212, 86, 90, 22,
                                         self, "refreshReport:")
        self.btn_report_refresh.setBezelStyle_(1)
        self.btn_report_refresh.setHidden_(True)
        inner.addSubview_(self.btn_report_refresh)

        self.lbl_counts = label("", 14, 112, WIDTH - 2 * PAD - 28, 200, size=11)
        # Отчёт многострочный: одностроковий режим обрізав би його
        self.lbl_counts.setUsesSingleLineMode_(False)
        self.lbl_counts.cell().setWraps_(True)
        self.lbl_counts.setHidden_(True)
        inner.addSubview_(self.lbl_counts)
        self.report_open = False
        card.setAutoresizingMask_(NSViewWidthSizable)
        autosize(inner)
        self.root.addSubview_(card)

    # --- Верхняя панель кнопок ----------------------------------------------
    def _build_actions(self):
        """Основные действия — всегда на виду, над вкладками.

        У каждой кнопки всплывающая подсказка: без неё по одному слову
        не всегда понятно, что произойдёт.
        """
        y = PAD + CARD_H + 10
        self.action_row = []
        specs = (
            ("Зняти тривогу", "cancelAlarm:",
             "ЗНЯТИ ТРИВОГУ ВРУЧНУ.\n\n"
             "Прибирає активну ціль і зупиняє гучні повтори, але радар "
             "продовжує працювати.\n\n"
             "Натискайте, коли ціль уже збили, вона пішла чи вибухнула, "
             "а радар цього не побачив, — або коли він помилився. Це "
             "не означає, що сповіщення було хибним.\n\n"
             "Ще 15 хвилин повідомлення про те саме місце йдуть без "
             "звуку. Якщо загроза зросте (ракета, балістика, бандероль, "
             "5+ цілей) — звук повернеться.\n\n"
             "У канал піде коротке повідомлення, що тривогу знято вручну."),
            ("Пауза сповіщень", "pause:",
             "Тимчасово припинити сповіщення. Радар продовжує слухати "
             "канали, але нічого не надсилає."),
            ("Тиша на годину", "mute:",
             "Тиша на годину: повідомлення приходять, але без звуку. "
             "Корисно, коли обстріл триває довго, а ви вже в укритті. "
             "Діє й на екстрені повтори."),
            ("Перевірка зв'язку", "test:",
             "Надіслати в канал перевірочне повідомлення — переконатися, "
             "що зв'язок з ботом працює."),
            ("Оновити закріп", "refreshStatus:",
             "Оновити закріплене повідомлення в каналі просто зараз, "
             "не чекаючи розкладу."),
            ("Звіт сьогодні", "report:",
             "Надіслати в канал звіт від 00:00 до цього моменту: загрози "
             "з розбивкою за типами, прильоти, тривоги, світло."),
            ("Звіт за вчора", "reportPrev:",
             "Надіслати в канал звіт за минулу добу."),
            ("Смарт-звіт у канал", "sendReview:",
             "Перевірити канали і надіслати мікрозвіт окремим "
             "повідомленням у канал, без звуку."),
            ("Перезапустити радар", "reload:",
             "Скинути закріплене повідомлення і перезапустити радар. "
             "Створюється нове закріплене, стан тривоги перечитується "
             "з історії каналів."),
            ("Смарт-Оновити", "toggleSmartButton:",
             "Перемикач для кнопки «Оновити» під закріпленим у каналі.\n\n"
             "Підсвічено (увімкнено) — кнопка «Оновити» переглядає останні "
             "повідомлення каналів і сама вирішує, чи знята ціль.\n\n"
             "Тьмяно (вимкнено) — кнопка просто перемальовує час, як "
             "стара версія, без жодного аналізу."),
        )
        for title, action, tip in specs:
            btn = button(title, 0, y, 10, 34, self, action)
            btn.setToolTip_(tip)
            if title.startswith("Пауза"):
                self.btn_pause = btn
            elif title.startswith("Зняти"):
                self.btn_cancel = btn
            elif title.startswith("Тиша"):
                self.btn_mute = btn
            elif title.startswith("Смарт-Оновити"):
                self.btn_smart_button = btn
            self.root.addSubview_(btn)
            self.action_row.append(btn)

        # --- Тумблер «Локально / Онлайн» ------------------------------------
        # Просте, наочне перемикання: де саме зараз працює радар.
        # Активний бік підсвічується, неактивний — тьмяний.
        tip = ("Де зараз працює радар. «Локально» — на цьому пристрої. "
              "«Онлайн» — на сервері 24/7, цей пристрій можна вимкнути. "
              "Перемикання одразу застосовується з обох боків, якщо "
              "хмара налаштована (див. «Додатково»).")

        self.lbl_local = label("Локально", 0, y + 84, 100, 22, size=13, bold=True)
        self.lbl_local.setAlignment_(NSCenterTextAlignment)
        self.lbl_local.setToolTip_(tip)
        self.root.addSubview_(self.lbl_local)

        self.mode_switch = NSSwitch.alloc().init()
        self.mode_switch.setFrame_(NSMakeRect(0, y + 82, 40, 26))
        self.mode_switch.setTarget_(self)
        self.mode_switch.setAction_("toggleMode:")
        self.mode_switch.setToolTip_(tip)
        self.root.addSubview_(self.mode_switch)

        self.lbl_online = label("Онлайн", 0, y + 84, 100, 22, size=13, bold=True)
        self.lbl_online.setAlignment_(NSCenterTextAlignment)
        self.lbl_online.setToolTip_(tip)
        self.root.addSubview_(self.lbl_online)

        self.lbl_mode_status = label("", 0, y + 108, 10, 16, size=11,
                                     color=NSColor.secondaryLabelColor())
        self.lbl_mode_status.setAlignment_(NSCenterTextAlignment)
        self.root.addSubview_(self.lbl_mode_status)

        self.actions_bottom = y + 132

    # --- Вкладки --------------------------------------------------------------
    def _build_tabs(self):
        """Три вкладки, чтобы настройки не сваливались в одну кучу.

        Высота содержимого считается по фактическому расположению виджетов,
        а не задаётся вручную: при ручном значении часть кнопок оказывалась
        ниже видимой области, и прокрутка до них не доставала.
        """
        top = self.actions_bottom + 12
        height = 360
        self.tabs = NSTabView.alloc().initWithFrame_(
            NSMakeRect(PAD - 6, top, WIDTH - 2 * (PAD - 6), height))

        for title, builder in (("Сповіщення", self._fill_alerts),
                               ("Канали і міста", self._fill_channels),
                               ("Додатково", self._fill_extra)):
            item = NSTabViewItem.alloc().initWithIdentifier_(title)
            item.setLabel_(title)

            content = Flipped.alloc().initWithFrame_(
                NSMakeRect(0, 0, WIDTH - 2 * PAD - 20, 2000))
            builder(content)

            # Нижняя граница самого нижнего виджета + запас снизу
            bottom = 0
            for view in content.subviews():
                frame = view.frame()
                bottom = max(bottom, frame.origin.y + frame.size.height)
            content.setFrame_(NSMakeRect(0, 0, WIDTH - 2 * PAD - 20, bottom + 16))

            scroll = NSScrollView.alloc().initWithFrame_(
                NSMakeRect(0, 0, WIDTH - 2 * PAD, height - 40))
            scroll.setHasVerticalScroller_(True)
            scroll.setDrawsBackground_(False)
            scroll.setAutohidesScrollers_(True)
            scroll.setAutoresizingMask_(NSViewWidthSizable | NSViewHeightSizable)
            scroll.setDocumentView_(content)

            autosize(content)
            item.setView_(scroll)       # вкладка сама растянет прокрутку
            self.tabs.addTabViewItem_(item)

        self.tabs.setAutoresizingMask_(NSViewWidthSizable | NSViewHeightSizable)
        self.root.addSubview_(self.tabs)
        self.tabs_bottom = top + height

    @objc.python_method
    def _row_help(self, view, key, x, y):
        """Кнопка «?» справа от строки настройки."""
        self.help_keys.append(key)
        view.addSubview_(help_button(x, y, self, len(self.help_keys) - 1))

    # --- Вкладка «Сповіщення» -------------------------------------------------
    @objc.python_method
    def _fill_alerts(self, v):
        w = int(v.frame().size.width)
        y = 4
        v.addSubview_(label("Звичайні налаштування", 0, y, 250, 18,
                            size=12, bold=True))
        y += 24

        plain = [
            ("cb_neighbors", "Будити на підльоті через сусідні села",
             "high_includes_neighbors"),
            ("cb_medium", "Надсилати повідомлення рівня MEDIUM", "send_medium"),
            ("cb_low", "Надсилати відбій (LOW)", "send_low"),
            ("cb_info", "Надсилати «звуки наші», роботу ППО (INFO)", "send_info"),
            ("cb_critical", "Особлива небезпека: 3 гучні повтори",
             "critical_enabled"),
            ("cb_civil", "Світло, вода, газ, хімія, ДРГ (без звуку)", "send_civil"),
            ("cb_near", "Цілі на найближчі села (тихо)", "send_near"),
            ("cb_dup_notice", "Позначка можливого дубляжу цілі з іншого каналу",
             "dup_notice_enabled"),
            ("cb_smart_read", "Глибокий розбір повідомлення (тип — з потрібного рядка)",
             "smart_read"),
            ("cb_report_clear", "Знімати ціль за свіжими зведеннями по області",
             "report_clear"),
            ("cb_raid_calm", "Наліт: звук лише на початку й при зростанні загрози",
             "raid_calm"),
        ]
        for attr, title, key in plain:
            box = checkbox(title, 0, y, w - 40, self, "touched:")
            setattr(self, attr, box)
            v.addSubview_(box)
            self._row_help(v, key, w - 28, y - 1)
            y += ROW

        self.cb_clear = checkbox("Повідомляти, коли загроза минула", 0, y, 240,
                                 self, "touched:")
        v.addSubview_(self.cb_clear)
        v.addSubview_(label("через", 244, y, 44))
        self.f_clear = field("", 286, y - 2, 42)
        v.addSubview_(self.f_clear)
        v.addSubview_(label("хв", 332, y, 30,
                            color=NSColor.secondaryLabelColor()))
        self._row_help(v, "clear_threat", w - 28, y - 1)
        y += ROW

        self.cb_quiet = checkbox("Тихі години — без звуку з", 0, y, 180,
                                 self, "touched:")
        v.addSubview_(self.cb_quiet)
        self.f_quiet_from = field("", 186, y - 2, 42)
        v.addSubview_(self.f_quiet_from)
        v.addSubview_(label("до", 234, y, 22))
        self.f_quiet_to = field("", 258, y - 2, 42)
        v.addSubview_(self.f_quiet_to)
        v.addSubview_(label("год", 306, y, 30,
                            color=NSColor.secondaryLabelColor()))
        self._row_help(v, "quiet_hours", w - 28, y - 1)
        y += ROW + 14

        # --- Смарт-режим: вмикається одним прапорцем або поштучно ---------
        v.addSubview_(label("Смарт-режим", 0, y, 150, 18, size=12, bold=True))
        self.cb_smart_all = checkbox("усі разом", 160, y, 120, self, "smartAll:")
        v.addSubview_(self.cb_smart_all)
        y += 22
        v.addSubview_(label("Перевірки, що прибирають хибні тривоги. "
                            "Вимикайте, якщо котрась заважає.",
                            0, y, w - 20, 16, size=11,
                            color=NSColor.secondaryLabelColor()))
        y += 22

        smart = [
            ("cb_replace", "Власні типи ЗАМІНЮЮТЬ вбудовані", "types_replace"),
            ("cb_planned", "Розмінування — не вважати прильотом", "filter_planned"),
            ("cb_conf", "Невпевнені висновки — без звуку", "filter_confidence"),
            ("cb_votes", "Відбій лише після двох каналів", "filter_votes"),
            ("cb_context", "Враховувати відповіді каналів", "filter_context"),
            ("cb_review", "Кнопка «Оновити» переглядає канали", "smart_review"),
            ("cb_explain", "Шукати ймовірне джерело вибуху", "smart_explain"),
            ("cb_series", "Перевіряти канали перед серією загроз",
             "smart_before_series"),
        ]
        for attr, title, key in smart:
            box = checkbox("      " + title, 0, y, w - 40, self, "touched:")
            setattr(self, attr, box)
            v.addSubview_(box)
            self._row_help(v, key, w - 28, y - 1)
            y += ROW

    # --- Вкладка «Канали і міста» ---------------------------------------------
    @objc.python_method
    def _fill_channels(self, v):
        w = int(v.frame().size.width)
        v.addSubview_(label("Канали, які слухає радар. По одному в рядок, "
                            "без «@». Порожні рядки ігноруються.", 0, 2,
                            w - 44, 16, size=11,
                            color=NSColor.secondaryLabelColor()))
        self._row_help(v, "channels", w - 28, 0)
        for i in range(10):
            y = 24 + i * 26
            v.addSubview_(label(f"{i + 1}.", 0, y + 3, 20, 16, size=11,
                                color=NSColor.tertiaryLabelColor()))
            f = field("", 22, y, w - 50)
            v.addSubview_(f)
            self.channel_fields.append(f)

        y = 24 + 10 * 26 + 16
        v.addSubview_(label("Міста", 0, y, 120, 18, size=12, bold=True))
        self._row_help(v, "cities", w - 28, y - 2)
        y += 22
        v.addSubview_(label("Назва міста і всі його написання через кому — "
                            "усіма мовами й відмінками.",
                            0, y, w - 20, 16, size=11,
                            color=NSColor.secondaryLabelColor()))
        y += 22

        self.city_fields = []
        self.city_switches = []
        for idx, title in enumerate(("Головне", "Додаткове 1", "Додаткове 2")):
            if idx == 0:
                v.addSubview_(label(title, 0, y + 3, 90, 16, size=11))
            else:
                # Місто можна заповнити один раз і вмикати за потреби —
                # наприклад, коли їдете в інше місто.
                box = checkbox(title, 0, y + 1, 110, self, "touched:")
                v.addSubview_(box)
                self.city_switches.append(box)
            name = field("", 116, y, 120)
            v.addSubview_(name)
            scroll, area = text_area("", 0, y + 28, w - 20, 54)
            v.addSubview_(scroll)
            self.city_fields.append((name, area))
            y += 92

        v.addSubview_(label("Головне місто йде і в закріплене, і в пости. "
                            "Додаткові — лише пости.", 0, y, w - 20, 16,
                            size=11, color=NSColor.secondaryLabelColor()))
        y += 24

        v.addSubview_(label("Район", 0, y + 3, 90, 16, size=11))
        self.f_district_name = field("", 92, y, 130)
        v.addSubview_(self.f_district_name)
        self._row_help(v, "district", w - 28, y)
        y += 28
        scroll, self.f_district_var = text_area("", 0, y, w - 20, 44)
        v.addSubview_(scroll)
        y += 54

        v.addSubview_(label("Перш ніж міняти місто — змініть канали: нинішні "
                            "мають писати про ваш регіон.", 0, y, w - 20, 32,
                            size=11, color=NSColor.systemOrangeColor()))

    # --- Низ окна --------------------------------------------------------------
    @objc.python_method
    def _build_footer(self):
        self.btn_save = button("Зберегти", PAD, 0, 110, 30, self, "save:")
        self.root.addSubview_(self.btn_save)
        self.lbl_saved = label("", PAD + 120, 0, WIDTH - PAD - 130, 20, size=11,
                               color=NSColor.secondaryLabelColor())
        self.root.addSubview_(self.lbl_saved)

    # --- Вкладка «Додатково» ---------------------------------------------------
    @objc.python_method
    def _fill_extra(self, v):
        w = int(v.frame().size.width)
        y = 4
        v.addSubview_(label("Закріплене повідомлення", 0, y, 250, 18,
                            size=12, bold=True))
        y += 24

        v.addSubview_(label("Оновлювати кожні", 0, y + 3, 130))
        self.f_status = field("", 134, y, 46)
        v.addSubview_(self.f_status)
        v.addSubview_(label("хв", 186, y + 3, 24,
                            color=NSColor.secondaryLabelColor()))
        self._row_help(v, "status_update_min", w - 28, y)
        y += ROW

        v.addSubview_(label("Тримати «Є загроза»", 0, y + 3, 130))
        self.f_alarm = field("", 134, y, 46)
        v.addSubview_(self.f_alarm)
        v.addSubview_(label("хв", 186, y + 3, 24,
                            color=NSColor.secondaryLabelColor()))
        self._row_help(v, "status_alarm_window_min", w - 28, y)
        y += ROW

        self.cb_oblast = checkbox("Враховувати тривогу по району / області",
                                  0, y, w - 40, self, "touched:")
        v.addSubview_(self.cb_oblast)
        self._row_help(v, "track_oblast_alarm", w - 28, y - 1)
        y += ROW

        self.cb_announce = checkbox("Тривогу і відбій — окремим повідомленням",
                                    0, y, w - 40, self, "touched:")
        v.addSubview_(self.cb_announce)
        self._row_help(v, "announce_alarm", w - 28, y - 1)
        y += ROW

        self.cb_button = checkbox("Кнопка «Оновити» під закріпленим",
                                  0, y, w - 40, self, "touched:")
        v.addSubview_(self.cb_button)
        self._row_help(v, "status_refresh_button", w - 28, y - 1)
        y += ROW + 10

        v.addSubview_(label("Службове", 0, y, 250, 18, size=12, bold=True))
        y += 24

        v.addSubview_(label("Склейка дублів", 0, y + 3, 110))
        self.f_dedup = field("", 114, y, 46)
        v.addSubview_(self.f_dedup)
        v.addSubview_(label("хв", 166, y + 3, 24,
                            color=NSColor.secondaryLabelColor()))
        self._row_help(v, "dedup_window_min", w - 28, y)
        y += ROW

        v.addSubview_(label("Режим роботи", 0, y + 3, 110))
        self._row_help(v, "role", w - 28, y)
        y += 24
        v.addSubview_(button("Показати лог", 0, y, 140, 26, self, "log:"))
        v.addSubview_(button("Папка з даними", 148, y, 150, 26, self, "folder:"))
        y += 36

        v.addSubview_(label("Резервна копія — щоб не переносити файли вручну "
                            "при перевстановленні:", 0, y, w - 20, 16, size=11,
                            color=NSColor.secondaryLabelColor()))
        y += 20
        v.addSubview_(button("Зберегти копію…", 0, y, 150, 26,
                             self, "saveBackup:"))
        v.addSubview_(button("Відновити з копії…", 158, y, 160, 26,
                             self, "loadBackup:"))
        y += 36

        v.addSubview_(label("Онлайн-екземпляр (сервер):", 0, y, w - 20, 16,
                            size=11, color=NSColor.secondaryLabelColor()))
        y += 20
        v.addSubview_(button("🔁 Перезапустити онлайн", 0, y, 200, 26,
                             self, "restartCloud:"))
        self.lbl_cloud_status = label("", 208, y + 5, w - 210, 18, size=11,
                                      color=NSColor.secondaryLabelColor())
        v.addSubview_(self.lbl_cloud_status)
        y += 36

        sync_tip = ("Надсилає ВСІ налаштування з цього застосунку (канали, "
                   "міста, фільтри, пороги тощо — все, крім ролі, власника "
                   "бота й токена каналу) на сервер і перезапускає його, "
                   "щоб вони одразу застосувались.\n\n"
                   "Працює лише в один бік: з комп'ютера на хмару. Якщо "
                   "після цього щось перемкнути через бота (наприклад, "
                   "паузу чи розумні фільтри), наступна синхронізація зі "
                   "старими налаштуваннями з комп'ютера може це скасувати — "
                   "тому тисніть цю кнопку саме тоді, коли щось змінили тут, "
                   "у застосунку.")
        btn_sync = button("🔄 Синхронізувати налаштування", 0, y, 200, 26,
                          self, "syncSettings:")
        btn_sync.setToolTip_(sync_tip)
        v.addSubview_(btn_sync)
        self.lbl_sync_status = label("", 208, y + 5, w - 210, 18, size=11,
                                     color=NSColor.secondaryLabelColor())
        self.lbl_sync_status.setToolTip_(sync_tip)
        v.addSubview_(self.lbl_sync_status)
        y += 42

        v.addSubview_(label("Власні типи загроз", 0, y, 220, 18,
                            size=12, bold=True))
        self._row_help(v, "types_custom", w - 28, y - 2)
        y += 22
        v.addSubview_(label("Один тип у рядку: «Назва: корінь, корінь». "
                            "Наприклад — Зевс: зевс, zeus",
                            0, y, w - 20, 16, size=11,
                            color=NSColor.secondaryLabelColor()))
        y += 22
        for caption, attr in (("Гучні — будять", "f_types_loud"),
                              ("Тихі — без звуку", "f_types_silent"),
                              ("Лише в закріплене", "f_types_pinned")):
            v.addSubview_(label(caption, 0, y, 200, 16, size=11))
            scroll, area = text_area("", 0, y + 20, w - 20, 56)
            v.addSubview_(scroll)
            setattr(self, attr, area)
            y += 84

        v.addSubview_(label("Канал сповіщень", 0, y, 200, 18, size=12, bold=True))
        self._row_help(v, "target_chat", w - 28, y - 2)
        y += 22
        v.addSubview_(label("Порожньо — брати з .env. Заповніть, щоб "
                            "перенаправити радар в інший канал.",
                            0, y, w - 20, 16, size=11,
                            color=NSColor.secondaryLabelColor()))
        y += 22

        v.addSubview_(label("ID каналу", 0, y + 3, 90, 16, size=11))
        self.f_chat_id = field("", 92, y, w - 112)
        v.addSubview_(self.f_chat_id)
        y += 28

        v.addSubview_(label("Токен бота", 0, y + 3, 90, 16, size=11))
        self.f_bot_token = field("", 92, y, w - 112)
        v.addSubview_(self.f_bot_token)
        y += 28

        v.addSubview_(label("Змінюйте токен лише якщо втрачено самого бота. "
                            "Після зміни каналу закріплене створюється заново.",
                            0, y, w - 20, 32, size=11,
                            color=NSColor.systemOrangeColor()))

    def windowDidResize_(self, _notification):
        """Окно растянули — пересчитываем раскладку под новую ширину."""
        self._layout()

    @objc.python_method
    def _layout(self):
        """Раскладка под текущий размер окна.

        Ширина берётся у окна, а не из константы: иначе при растягивании
        содержимое остаётся узким и кнопки «?» вылезают за край.
        """
        size = self.scroll.contentSize()
        width = max(MIN_WIDTH, int(size.width))
        self.width = width

        # Карточка состояния и вкладки тянутся, кнопки — раскладываются заново
        card_h = CARD_H_OPEN if getattr(self, "report_open", False) else CARD_H
        self.card.setFrame_(NSMakeRect(PAD, PAD, width - 2 * PAD, card_h))
        self.card.contentView().setFrame_(
            NSMakeRect(0, 0, width - 2 * PAD, card_h))

        # Кнопки в два ряда по три: в один ряд шесть штук не помещаются
        # на узком окне, подписи обрезались.
        gap, per_row = 6, 3
        btn_w = (width - 2 * PAD - gap * (per_row - 1)) / per_row
        y = PAD + card_h + 10
        for i, btn in enumerate(self.action_row):
            row, col = divmod(i, per_row)
            btn.setFrame_(NSMakeRect(PAD + col * (btn_w + gap),
                                     y + row * 40, btn_w, 34))
        rows_used = (len(self.action_row) + per_row - 1) // per_row
        role_y = y + rows_used * 40 + 8

        # Тумблер по центру, підписи по боках від нього
        switch_w, gap2 = 44, 14
        cx = width / 2
        self.mode_switch.setFrame_(NSMakeRect(cx - switch_w / 2, role_y, switch_w, 26))
        self.lbl_local.setFrame_(NSMakeRect(PAD, role_y + 2,
                                            cx - switch_w / 2 - gap2 - PAD, 22))
        self.lbl_local.setAlignment_(NSCenterTextAlignment)
        self.lbl_online.setFrame_(NSMakeRect(cx + switch_w / 2 + gap2, role_y + 2,
                                             width - PAD - (cx + switch_w / 2 + gap2), 22))
        self.lbl_online.setAlignment_(NSCenterTextAlignment)
        self.lbl_mode_status.setFrame_(NSMakeRect(PAD, role_y + 30, width - 2 * PAD, 16))

        self.actions_bottom = role_y + 52

        tabs_top = self.actions_bottom + 12
        available = int(size.height) - tabs_top - 56
        tabs_h = max(240, available)
        self.tabs.setFrame_(NSMakeRect(PAD - 6, tabs_top,
                                       width - 2 * (PAD - 6), tabs_h))

        # Содержимое вкладок тоже подгоняем по ширине
        for i in range(self.tabs.numberOfTabViewItems()):
            scroll = self.tabs.tabViewItemAtIndex_(i).view()
            doc = scroll.documentView()
            frame = doc.frame()
            doc.setFrame_(NSMakeRect(0, 0, scroll.contentSize().width,
                                     frame.size.height))

        y = tabs_top + tabs_h + 10
        self.btn_save.setFrame_(NSMakeRect(PAD, y, 110, 30))
        self.lbl_saved.setFrame_(NSMakeRect(PAD + 120, y + 7,
                                            width - PAD - 130, 20))
        total = y + 30 + PAD

        self.root.setFrame_(NSMakeRect(0, 0, width,
                                       max(total, int(size.height))))

    # ======================================================================
    #  Настройки
    # ======================================================================
    @objc.python_method
    def _load_settings(self):
        s = settings.load()
        import railway_ctl
        self.lbl_cloud_status.setStringValue_(
            "Готово до керування" if railway_ctl.available()
            else "Не налаштовано (див. .env)")
        self.cb_neighbors.setState_(1 if s["high_includes_neighbors"] else 0)
        self.cb_medium.setState_(1 if s["send_medium"] else 0)
        self.cb_low.setState_(1 if s["send_low"] else 0)
        self.cb_info.setState_(1 if s["send_info"] else 0)
        self.cb_quiet.setState_(1 if s["quiet_hours_enabled"] else 0)
        self.cb_oblast.setState_(1 if s["track_oblast_alarm"] else 0)
        self.cb_announce.setState_(1 if s["announce_alarm"] else 0)
        self.cb_button.setState_(1 if s["status_refresh_button"] else 0)
        self.cb_clear.setState_(1 if s["clear_threat"] else 0)
        self.cb_critical.setState_(1 if s["critical_enabled"] else 0)
        self.cb_civil.setState_(1 if s["send_civil"] else 0)
        self.cb_near.setState_(1 if s["send_near"] else 0)
        self.cb_dup_notice.setState_(1 if s.get("dup_notice_enabled", True) else 0)
        self.cb_smart_read.setState_(1 if s.get("smart_read", True) else 0)
        self.cb_report_clear.setState_(1 if s.get("report_clear", True) else 0)
        self.cb_raid_calm.setState_(1 if s.get("raid_calm", True) else 0)
        self.cb_replace.setState_(1 if s.get("types_replace") else 0)
        self.cb_planned.setState_(1 if s["filter_planned"] else 0)
        self.cb_conf.setState_(1 if s["filter_confidence"] else 0)
        self.cb_votes.setState_(1 if s["filter_votes"] else 0)
        self.cb_context.setState_(1 if s["filter_context"] else 0)
        self.cb_review.setState_(1 if s.get("smart_review") else 0)
        self.cb_explain.setState_(1 if s.get("smart_explain") else 0)
        self.cb_series.setState_(1 if s.get("smart_before_series") else 0)
        self.cb_smart_all.setState_(
            1 if all(s[k] for k in ("filter_planned", "filter_confidence",
                                    "filter_votes", "filter_context",
                                    "smart_review", "smart_explain",
                                    "smart_before_series")) else 0)
        self.f_clear.setStringValue_(str(s["clear_after_min"]))
        self.f_quiet_from.setStringValue_(str(s["quiet_from"]))
        self.f_quiet_to.setStringValue_(str(s["quiet_to"]))
        self.f_status.setStringValue_(str(s["status_update_min"]))
        self.f_alarm.setStringValue_(str(s["status_alarm_window_min"]))
        self.f_dedup.setStringValue_(str(s["dedup_window_min"]))
        for i, f in enumerate(self.channel_fields):
            f.setStringValue_(s["channels"][i] if i < len(s["channels"]) else "")

        keys = (("city_main_name", "city_main_variants"),
                ("city_2_name", "city_2_variants"),
                ("city_3_name", "city_3_variants"))
        for (name_f, var_f), (kn, kv) in zip(self.city_fields, keys):
            name_f.setStringValue_(s.get(kn, ""))
            var_f.setString_(s.get(kv, ""))
        self.city_switches[0].setState_(1 if s.get("city_2_on") else 0)
        self.city_switches[1].setState_(1 if s.get("city_3_on") else 0)
        self.f_district_name.setStringValue_(s.get("district_name", ""))
        self.f_chat_id.setStringValue_(s.get("target_chat_id", ""))
        self.f_bot_token.setStringValue_(s.get("bot_token", ""))
        self.f_district_var.setString_(s.get("district_variants", ""))
        # Порожні поля заповнюємо вбудованими типами: щоб було видно,
        # що зараз працює, і можна було відредагувати або видалити рядок.
        import threats as _threats

        loud_txt, silent_txt = _threats.builtin_as_text()
        self.f_types_loud.setString_(s.get("types_loud") or loud_txt)
        self.f_types_silent.setString_(s.get("types_silent") or silent_txt)
        self.f_types_pinned.setString_(s.get("types_pinned", ""))

    @objc.python_method
    def _num(self, widget, fallback, low, high):
        try:
            value = int(str(widget.stringValue()).strip())
        except ValueError:
            return fallback
        return max(low, min(high, value))

    def save_(self, _sender):
        old = settings.load()
        channels = []
        for f in self.channel_fields:
            name = str(f.stringValue()).strip().lstrip("@")
            if name and name not in channels:
                channels.append(name)

        cities = {}
        keys = (("city_main_name", "city_main_variants"),
                ("city_2_name", "city_2_variants"),
                ("city_3_name", "city_3_variants"))
        for (name_f, var_f), (kn, kv) in zip(self.city_fields, keys):
            cities[kn] = str(name_f.stringValue()).strip()
            cities[kv] = str(var_f.string()).strip()
        cities["city_2_on"] = bool(self.city_switches[0].state())
        cities["city_3_on"] = bool(self.city_switches[1].state())
        # Главный город без вариантов написания сломал бы весь фильтр
        if not cities["city_main_variants"]:
            cities["city_main_name"] = old["city_main_name"]
            cities["city_main_variants"] = old["city_main_variants"]

        settings.save({
            **cities,
            "district_name": str(self.f_district_name.stringValue()).strip()
                             or old["district_name"],
            "district_variants": str(self.f_district_var.string()).strip()
                                 or old["district_variants"],
            "types_loud": str(self.f_types_loud.string()).strip(),
            "types_silent": str(self.f_types_silent.string()).strip(),
            "types_pinned": str(self.f_types_pinned.string()).strip(),
            "owner_id": old["owner_id"],
            "target_chat_id": str(self.f_chat_id.stringValue()).strip(),
            "bot_token": str(self.f_bot_token.stringValue()).strip(),
            "role": old["role"],
            "telegram_control": old["telegram_control"],
            "channels": channels or old["channels"],
            "high_includes_neighbors": bool(self.cb_neighbors.state()),
            "send_medium": bool(self.cb_medium.state()),
            "send_low": bool(self.cb_low.state()),
            "send_info": bool(self.cb_info.state()),
            "quiet_hours_enabled": bool(self.cb_quiet.state()),
            "quiet_from": self._num(self.f_quiet_from, old["quiet_from"], 0, 23),
            "quiet_to": self._num(self.f_quiet_to, old["quiet_to"], 0, 23),
            "status_update_min": self._num(self.f_status,
                                           old["status_update_min"], 1, 120),
            "status_alarm_window_min": self._num(
                self.f_alarm, old["status_alarm_window_min"], 5, 240),
            "track_oblast_alarm": bool(self.cb_oblast.state()),
            "announce_alarm": bool(self.cb_announce.state()),
            "status_refresh_button": bool(self.cb_button.state()),
            "clear_threat": bool(self.cb_clear.state()),
            "critical_enabled": bool(self.cb_critical.state()),
            "send_civil": bool(self.cb_civil.state()),
            "send_near": bool(self.cb_near.state()),
            "dup_notice_enabled": bool(self.cb_dup_notice.state()),
            "smart_read": bool(self.cb_smart_read.state()),
            "report_clear": bool(self.cb_report_clear.state()),
            "raid_calm": bool(self.cb_raid_calm.state()),
            "types_replace": bool(self.cb_replace.state()),
            "filter_planned": bool(self.cb_planned.state()),
            "filter_confidence": bool(self.cb_conf.state()),
            "filter_votes": bool(self.cb_votes.state()),
            "filter_context": bool(self.cb_context.state()),
            "smart_review": bool(self.cb_review.state()),
            "smart_explain": bool(self.cb_explain.state()),
            "smart_before_series": bool(self.cb_series.state()),
            "clear_after_min": self._num(self.f_clear, old["clear_after_min"],
                                         3, 180),
            "dedup_window_min": self._num(self.f_dedup,
                                          old["dedup_window_min"], 1, 120),
            "dump_days": old["dump_days"],
        })
        config.reload_settings()
        import geo
        geo.reload_cities()
        self._load_settings()

        # Канал сменился — старое закреплённое осталось в другом канале,
        # его id больше не годится: создаём новое.
        new_chat = str(self.f_chat_id.stringValue()).strip()
        if new_chat != (old.get("target_chat_id") or ""):
            import status as status_module
            status_module.STATE_FILE.unlink(missing_ok=True)
            self.app.restart_radar()
            self.lbl_saved.setStringValue_(
                "Збережено ✓ · канал змінено, радар перезапускається")
            return

        # Список каналов читается при подключении, поэтому радар
        # перезапускается — иначе настройка бы не работала.
        if channels and channels != old["channels"]:
            self.app.restart_radar()
            self.lbl_saved.setStringValue_("Збережено ✓ · радар перезапускається")
        else:
            self.lbl_saved.setStringValue_("Збережено ✓")

    def smartAll_(self, sender):
        """Один прапорець вмикає або вимикає всі смарт-перевірки."""
        state = 1 if sender.state() else 0
        for attr in ("cb_planned", "cb_conf", "cb_votes", "cb_context",
                     "cb_review", "cb_explain", "cb_series"):
            getattr(self, attr).setState_(state)
        self.lbl_saved.setStringValue_("Є незбережені зміни")

    def touched_(self, _sender):
        self.lbl_saved.setStringValue_("Є незбережені зміни")

    # ======================================================================
    #  Действия
    # ======================================================================
    def showHelp_(self, sender):
        key = self.help_keys[sender.tag()]
        alert = NSAlert.alloc().init()
        alert.setMessageText_("Про це налаштування")
        alert.setInformativeText_(settings.HELP.get(key, ""))
        alert.addButtonWithTitle_("Зрозуміло")
        alert.runModal()

    def toggleMode_(self, sender):
        """Перемикач «Локально / Онлайн» — керує застосунком через app.set_mode."""
        online = bool(sender.state())
        self.lbl_mode_status.setStringValue_("Перемикаю…")
        self.app.set_mode(online)

    def reload_(self, _sender):
        """Сбрасывает закреплённое сообщение и перезапускает радар."""
        alert = NSAlert.alloc().init()
        alert.setMessageText_("Перезапустити радар?")
        alert.setInformativeText_(
            "У каналі буде створене нове закріплене повідомлення, "
            "а стан тривоги радар перечитає з історії каналів за 6 годин.\n\n"
            "Старе закріплене залишиться в каналі як звичайний пост.")
        alert.addButtonWithTitle_("Перезапустити")
        alert.addButtonWithTitle_("Скасувати")
        if alert.runModal() != 1000:            # 1000 — первая кнопка
            return

        import status as status_module
        status_module.STATE_FILE.unlink(missing_ok=True)   # забыть старое
        self.app.restart_radar()
        self.lbl_saved.setStringValue_("Радар перезапускається…")

    def toggleReport_(self, _sender):
        """Разворачивает и сворачивает отчёт за сегодня."""
        self.report_open = not self.report_open
        # Окно подрастает, чтобы отчёт был виден целиком
        frame = self.window.frame()
        delta = CARD_H_OPEN - CARD_H
        change = delta if self.report_open else -delta
        frame.origin.y -= change
        frame.size.height += change
        self.window.setFrame_display_animate_(frame, True, True)
        self.btn_toggle_report.setTitle_(
            ("▾ " if self.report_open else "▸ ") + "Звіт за сьогодні")
        self.lbl_counts.setHidden_(not self.report_open)
        self.btn_report_refresh.setHidden_(not self.report_open)
        self.refresh()
        self._layout()

    def refreshReport_(self, _sender):
        self.refresh()

    def mute_(self, _sender):
        self.app.toggle_mute(None)
        self.refresh()

    def pause_(self, _sender):
        self.app.toggle_pause(None)
        self.refresh()

    def test_(self, _sender):
        self.app.send_test(None)

    def cancelAlarm_(self, _sender):
        """Прибирає хибну тривогу, лишаючи радар працювати."""
        self.app.cancel_alarm()
        self.lbl_saved.setStringValue_("Тривогу знято — радар працює далі")
        self.refresh()

    def toggleSmartButton_(self, _sender):
        """Смарт-режим кнопки «Оновити» під закріпленим у каналі.

        Окремо від загальних «Розумних фільтрів»: той перемикач чіпає
        ще й live-обробку кожного повідомлення, а цей — лише поведінку
        самої кнопки «Оновити».
        """
        saved = settings.load()
        saved["smart_review"] = not saved.get("smart_review", True)
        settings.save(saved)
        config.reload_settings()
        self.refresh()

    def refreshStatus_(self, _sender):
        """Смарт-перевірка каналів і оновлення закріпленого."""
        self.app.run_review(None)
        self.report_open = True
        self.btn_toggle_report.setTitle_("▾ Звіт за сьогодні")
        self.lbl_counts.setHidden_(False)
        self.btn_report_refresh.setHidden_(False)
        self.lbl_saved.setStringValue_("Перевіряю канали…")
        self._layout()
        self.refresh()
        self.lbl_saved.setStringValue_("Закріплене оновлюється…")

    def saveBackup_(self, _sender):
        """Складывает секреты и настройки в один файл."""
        panel = NSSavePanel.savePanel()
        panel.setTitle_("Зберегти резервну копію радара")
        panel.setNameFieldStringValue_("CityRadar-backup.zip")
        if panel.runModal() != 1:
            return
        ok, info = backup.create(panel.URL().path())
        self._alert("Резервна копія",
                    (f"Копію збережено. {info}.\n\nУ ній лежать секрети "
                     "й авторизація Telegram — зберігайте її в надійному "
                     "місці й нікому не передавайте.") if ok
                    else f"Не вдалося: {info}")

    def restartCloud_(self, _sender):
        """Перезапускає онлайн-екземпляр — на випадок збою в хмарі."""
        import railway_ctl

        if not railway_ctl.available():
            self.lbl_cloud_status.setStringValue_("Не налаштовано (див. .env)")
            return

        self.lbl_cloud_status.setStringValue_("Перезапускаю…")

        def worker():
            ok, info = railway_ctl.restart()
            self.lbl_cloud_status.setStringValue_(
                "✅ Перезапущено" if ok else f"⚠️ {info}")

        threading.Thread(target=worker, daemon=True).start()

    def syncSettings_(self, _sender):
        """Надсилає локальні налаштування в хмару й перезапускає її.

        Односторонньо: комп'ютер -> хмара. Мітка часу _synced_at у
        settings.json дозволяє хмарі застосувати їх лише один раз,
        а не при кожному наступному перезапуску (інакше вони б "тягнули
        назад" будь-яку зміну, зроблену тим часом через бота).
        """
        import railway_ctl

        if not railway_ctl.available():
            self.lbl_sync_status.setStringValue_("Не налаштовано (див. .env)")
            return

        self.lbl_sync_status.setStringValue_("Надсилаю…")

        def worker():
            data = settings.load()
            data["_synced_at"] = f"{time.time():.6f}"
            settings.save(data)
            ok, info = railway_ctl.push_settings(data)
            self.lbl_sync_status.setStringValue_(
                "✅ Надіслано, хмара перезапускається" if ok else f"⚠️ {info}")

        threading.Thread(target=worker, daemon=True).start()

    def loadBackup_(self, _sender):
        """Восстанавливает рабочие файлы из копии."""
        panel = NSOpenPanel.openPanel()
        panel.setTitle_("Виберіть резервну копію")
        panel.setAllowedFileTypes_(["zip"])
        panel.setAllowsMultipleSelection_(False)
        if panel.runModal() != 1:
            return
        ok, info = backup.restore(panel.URL().path())
        if ok:
            config.reload_settings()
            self._load_settings()
            self.app.restart_radar()
            self._alert("Відновлення",
                        f"{info.capitalize()}. Радар перезапускається.")
        else:
            self._alert("Відновлення", f"Не вдалося: {info}")

    @objc.python_method
    def _alert(self, title, text):
        alert = NSAlert.alloc().init()
        alert.setMessageText_(title)
        alert.setInformativeText_(text)
        alert.addButtonWithTitle_("Гаразд")
        alert.runModal()

    def report_(self, _sender):
        self.app.send_report(None)
        self.refresh()

    def sendReview_(self, _sender):
        self.app.send_review(None)
        self.lbl_saved.setStringValue_("Смарт-звіт надсилається…")

    def reportPrev_(self, _sender):
        self.app.send_report(None, day="yesterday")
        self.refresh()
        self.lbl_saved.setStringValue_("Звіт надсилається…")

    def log_(self, _sender):
        subprocess.run(["open", "-a", "Console",
                        str(config.LOGS_DIR / "monitor.log")], check=False)

    def folder_(self, _sender):
        subprocess.run(["open", str(config.BASE_DIR)], check=False)

    # ======================================================================
    #  Обновление данных
    # ======================================================================
    @objc.python_method
    def refresh(self):
        r = self.app.radar
        now = datetime.now()
        recent_high = (r.last_alert and r.last_alert[1] == "HIGH"
                       and (now - r.last_alert[0]).total_seconds()
                       < config.STATUS_ALARM_WINDOW_MIN * 60)

        if not r.running:
            state, color = "⚠️ Не працює", NSColor.systemOrangeColor()
            sub = "Радар зупинено або не зміг стартувати"
        elif r.paused:
            state, color = "⏸ Пауза", NSColor.systemGrayColor()
            sub = "Сповіщення не надсилаються"
        else:
            uptime = status_mod.human_uptime(now - r.started)
            sub = f"Працює · {len(config.CHANNELS)} каналів · {uptime}"
            if recent_high:
                state, color = "🔴 Є загроза", NSColor.systemRedColor()
            elif r.alarm:
                state = f"🟡 {r.alarm[0]}"
                color = NSColor.systemYellowColor()
                sub = f"Оголошена о {r.alarm[1]:%H:%M} · " + sub
            else:
                state, color = "🟢 Загроз немає", NSColor.systemGreenColor()

        self.lbl_state.setStringValue_(state)
        self.lbl_state.setTextColor_(color)
        self.lbl_sub.setStringValue_(sub)

        if r.last_alert:
            when, _lvl, head = r.last_alert
            self.lbl_last.setStringValue_(f"Останнє: {head}  ({when:%H:%M})")

        if getattr(self, "report_open", False):
            try:
                import re as _re
                import status as _status

                text = ""
                if getattr(r, "review", None):
                    text = _status.format_review(
                        r.review, config.CITY_MAIN_NAME, html=False) + "\n\n"
                text += _re.sub(r"<[^>]+>", "", r.build_report())
            except Exception:                               # noqa: BLE001
                text = "Звіт недоступний"
            self.lbl_counts.setStringValue_(text)
        self.btn_pause.setTitle_("Відновити сповіщення" if r.paused
                                 else "Пауза сповіщень")

        muted = hasattr(r, "is_muted") and r.is_muted()
        self.btn_mute.setTitle_(f"🔕 Тиша до {r.mute_until:%H:%M}" if muted
                                else "Тиша на годину")

        # Кнопка-тумблер: підсвічена (зелений, жирний) — смарт-режим
        # увімкнено, тьмяна — кнопка «Оновити» в каналі лише перемальовує
        # час, без аналізу.
        smart_on = bool(config.SMART_REVIEW)
        smart_title = "🔎 Смарт-Оновити" if smart_on else "🔄 Смарт-Оновити"
        smart_color = (NSColor.systemGreenColor() if smart_on
                       else NSColor.tertiaryLabelColor())
        smart_attrs = NSAttributedString.alloc().initWithString_attributes_(
            smart_title, {NSForegroundColorAttributeName: smart_color})
        self.btn_smart_button.setAttributedTitle_(smart_attrs)

        # Тумблер: підсвічуємо активний бік, тьмяним — неактивний.
        # Стан застосунку (config.ROLE) — не хмари: перемикач керує ЦИМ
        # пристроєм, а хмару лише просимо синхронно зробити протилежне.
        online = config.ROLE == "backup"
        self.mode_switch.setState_(1 if online else 0)

        active_color = NSColor.systemGreenColor()
        dim_color = NSColor.tertiaryLabelColor()
        self.lbl_local.setTextColor_(dim_color if online else active_color)
        self.lbl_online.setTextColor_(active_color if online else dim_color)

        # Під тумблером — що відбувається насправді: якщо резерв мовчить,
        # значить інший бік живий; якщо взяв на себе — той бік не відповідає.
        msg = getattr(r, "mode_message", "") or ""
        if msg:
            self.lbl_mode_status.setStringValue_(msg.splitlines()[0][:60])
        elif online and getattr(r, "standby", False):
            self.lbl_mode_status.setStringValue_("Онлайн активний, цей пристрій мовчить")
        elif online:
            self.lbl_mode_status.setStringValue_(
                "⚠️ Онлайн не відповідає — тимчасово працює цей пристрій")
        else:
            self.lbl_mode_status.setStringValue_("Активний саме цей пристрій")

    @objc.python_method
    def show(self):
        self.refresh()
        NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
        self.window.makeKeyAndOrderFront_(None)
