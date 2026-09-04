# WatcherManager

Система мониторинга рабочих станций: агент на каждом Windows-ПК → централизованный сервер → веб-дашборд.

## Структура проекта

```
WatcherManager/
├── agent/                  # Агент для Windows-ПК
│   ├── config.py           # Настройки (URL сервера, API ключ)
│   ├── window_tracker.py   # Отслеживание активного окна
│   ├── sender.py           # Отправка событий на сервер
│   ├── tray_app.py         # Legacy UI helper (не используется installer flow)
│   ├── tracker_service.py  # Legacy Windows Service (не используется installer flow)
│   ├── install_common.ps1  # Общая зачистка/verify Windows-установки
│   ├── install_finalize.ps1
│   ├── install_verify.ps1
│   ├── requirements.txt
│   └── install.bat         # Установка на ПК (запускать от Администратора)
│
└── server/                 # Сервер (Linux/Windows VPS)
    ├── main.py             # FastAPI приложение
    ├── models.py           # Модели базы данных
    ├── database.py         # Подключение к PostgreSQL
    ├── templates/          # HTML шаблоны дашборда
    ├── static/             # CSS/JS
    ├── requirements.txt
    └── docker-compose.yml  # PostgreSQL + сервер
```

## Быстрый старт

### 1. Сервер

```bash
cd server
cp .env.example .env       # Задайте DATABASE_URL и SECRET_KEY
docker-compose up -d       # Поднять PostgreSQL
pip install -r requirements.txt
python main.py             # Запустить сервер
```

### 2. Агент на ПК (Windows, от Администратора)

```bat
cd agent
# В config.py прописать SERVER_URL и API_KEY
install.bat
```

### 3. Один готовый установщик (SyncLayerSetup.exe)

Если нужен единый файл для массового развёртывания (GPO/RMM/PowerShell):

- В репозитории есть workflow `Build Windows Installer`.
- Он собирает `SyncLayerSetup.exe` на Windows runner в GitHub Actions.
- Установщик кладёт `SyncLayerAgent.exe` в `C:\ProgramData\SyncLayer`, создаёт одну задачу `SyncLayerAgent` (`ONLOGON`) и проверяет, что на ПК нет лишних служб/автозапусков.

## Схема Windows-установки

На рабочем ПК после установки:

- **1** процесс `SyncLayerAgent.exe`
- **1** Scheduled Task `SyncLayerAgent`
- **0** Windows Services
- **0** tray helpers

Проверка:

```bat
cd agent
install_verify.bat
```

## Автозапуск и защита

Актуальный installer flow использует **одну** Scheduled Task `SyncLayerAgent` при входе пользователя.

- Не создаются записи `HKLM\Run` / `HKCU\Run`, если задача создана успешно
- При переустановке удаляются legacy service/task/run entries от старых версий
- Удалить агент можно от имени Администратора через `uninstall.bat`

## Что отслеживается

- Название активного приложения (имя процесса)
- Заголовок открытого окна (документ, сайт, файл)
- Время начала и окончания работы с приложением
- Периоды простоя (нет активности мыши/клавиатуры)
- Вход/выход из системы

## Дашборд

Открыть в браузере: `http://ВАШ_СЕРВЕР:8000`

- **Логин:** `administrator`
- **Пароль:** `superwatcher` (задаётся в `.env`: `AUTH_USERNAME`, `AUTH_PASSWORD`)

- Список всех ПК с онлайн/офлайн статусом
- Таймлайн активности за любой день
- Статистика по приложениям
- Поиск по заголовкам окон
