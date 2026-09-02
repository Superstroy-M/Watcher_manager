# WatcherManager

Система мониторинга рабочих станций: агент на каждом Windows-ПК → централизованный сервер → веб-дашборд.

## Структура проекта

```
WatcherManager/
├── agent/                  # Агент для Windows-ПК
│   ├── config.py           # Настройки (URL сервера, API ключ)
│   ├── window_tracker.py   # Отслеживание активного окна
│   ├── sender.py           # Отправка событий на сервер
│   ├── tray_app.py         # Иконка в системном трее
│   ├── tracker_service.py  # Windows Service (не убить пользователю)
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
- Установщик кладёт файлы в `C:\ProgramData\SyncLayer`, регистрирует и запускает службу `SyncLayer`, включает автозапуск после перезагрузки.

## Как работает защита от закрытия

Агент устанавливается как **Windows Service** с учётной записью SYSTEM:
- Обычный пользователь не может остановить сервис
- При падении — автоматически перезапускается через 10 секунд
- Иконка в трее показывает статус, но не управляет сервисом
- Удалить можно только от имени Администратора через `uninstall.bat`

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
