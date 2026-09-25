# -*- coding: utf-8 -*-
"""Сборка standalone-приложения «Радар міста».

Запуск:  ./.venv/bin/python setup.py py2app

Получается самостоятельный .app: внутри своя копия Python и всех
библиотек. Работает, даже если проект и виртуальное окружение удалить.
Рабочие файлы (.env, сессия, логи, настройки) приложение держит в
~/Library/Application Support/CityRadar.
"""

from setuptools import setup

APP = ["menubar.py"]

OPTIONS = {
    "argv_emulation": False,
    "iconfile": "CityRadar.icns",
    "plist": {
        # Имя каталога бандла — без пробелов и кириллицы:
        # py2app рвёт по пробелу путь при подписи. Видимое имя задаёт
        # CFBundleDisplayName, его и показывает Finder.
        "CFBundleName": "CityRadar",
        "CFBundleDisplayName": "Радар міста",
        "CFBundleIdentifier": "local.cityradar.app",
        "CFBundleVersion": "1.0.0",
        "CFBundleShortVersionString": "1.0",
        # Иконка и в строке меню, и в Dock: так приложение проще найти
        # и вернуть окно, если его закрыли.
        "LSUIElement": False,
        "LSMinimumSystemVersion": "11.0",
        "NSHighResolutionCapable": True,
        "NSHumanReadableCopyright": "Локальний монітор повітряної обстановки",
    },
    "packages": ["telethon", "rumps", "certifi", "dotenv"],
    # Tcl/Tk тянет 90 МБ и нам не нужен — интерфейс на Cocoa
    "excludes": ["tkinter", "numpy", "matplotlib", "PIL", "test", "unittest"],
    "includes": ["classify", "config", "geo", "gui", "monitor", "notify",
                 "reader", "region_profile", "settings", "status", "threats"],
}

setup(
    name="CityRadar",
    app=APP,
    options={"py2app": OPTIONS},
    setup_requires=["py2app"],
)
