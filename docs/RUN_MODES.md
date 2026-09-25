# Способи запуску

Оберіть один. Почніть із «Б» — він найпростіший і працює скрізь.

## А. Застосунок macOS (іконка в рядку меню)

Потрібен акаунт Telegram: радар читає канали через нього (файл сесії).

```bash
pip install -r requirements.txt py2app rumps pyobjc
python3 auth.py                   # одноразовий вхід у Telegram (код із SMS)
python3 setup.py py2app           # збирає dist/CityRadar.app
cp -R dist/CityRadar.app /Applications/
```

Робочі файли застосунок тримає в `~/Library/Application Support/CityRadar`
(там `.env`, `data/settings.json`, сесія, логи). Налаштування міста, району й
каналів — у вікні застосунку. Село-таблиці профілю (CLOSE/NEAR/FAR) у зібраному
застосунку задаються файлом `~/Library/Application Support/CityRadar/data/region_profile.json`
(формат — наприкінці `region_profile.py`): сам `.py` зашито в `.app`.

⚠️ Файл сесії Telegram = повний доступ до акаунта. Не копіюйте його на чужі
сервери й не публікуйте. Радше використовуйте **другий** акаунт для радара.

## Б. Окремий процес на будь-якій ОС (без акаунта)

Читає публічні сторінки каналів `t.me/s/<канал>` — акаунт і сесія не потрібні.

```bash
cp .env.example .env               # впишіть BOT_TOKEN і TARGET_CHAT_ID
python3 cloud_main.py
```

Налаштування — `data/settings.json`. Щоб працювало у фоні:

**Linux (systemd)** — `/etc/systemd/system/city-radar.service`:

```ini
[Unit]
Description=City Radar
After=network-online.target

[Service]
WorkingDirectory=/шлях/до/city-radar
ExecStart=/шлях/до/city-radar/.venv/bin/python cloud_main.py
Environment=TZ=Europe/Kyiv
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

`sudo systemctl enable --now city-radar` · логи: `journalctl -u city-radar -f`.

**macOS** — `launchd`-агент або просто термінал із `caffeinate -i python3 cloud_main.py`.

## В. Хмара (наприклад Railway)

У репозиторії є `Procfile` (`worker: python cloud_main.py`) і `requirements.txt`.
Створіть сервіс із цього репозиторію та задайте змінні:

| Змінна | Значення |
|---|---|
| `BOT_TOKEN`, `TARGET_CHAT_ID` | бот і канал сповіщень |
| `RADAR_IS_CLOUD` | `1` |
| `RADAR_DATA_DIR` | шлях підключеного **постійного диска** (Volume), напр. `/data` |
| `RADAR_SETTINGS_JSON` | вміст вашого `data/settings.json` одним рядком |
| `RADAR_REGION_JSON` | вміст вашого профілю регіону (`region_profile.json`) одним рядком |
| `TZ` | `Europe/Kyiv` |

Без постійного диска стан тривоги й закріпленого забувається при кожному
перезапуску, і радар дублюватиме повідомлення.

⚠️ **Ніколи** не кладіть на хмару файл сесії Telegram і токени керування
хмарою (`RAILWAY_TOKEN`).

## Г. Два екземпляри з резервом (необов'язково)

Основний працює в хмарі (`role: "main"`), запасний — застосунок на Mac
(`role: "backup"`): мовчить, доки живе основний, і сам вмикається, якщо
закріплене повідомлення перестало оновлюватись. Налаштовуйте лише після того,
як один екземпляр працює стабільно.
