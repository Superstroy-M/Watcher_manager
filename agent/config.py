# Настройки агента — задайте перед установкой
SERVER_URL = "http://YOUR_SERVER_IP:8000"  # Адрес вашего сервера
API_KEY = "change_this_secret_key_123"     # Должен совпадать с сервером
AGENT_VERSION = "1.0"

# Интервал опроса активного окна (секунды)
POLL_INTERVAL = 5

# Через сколько секунд бездействия считать сессию "idle"
IDLE_THRESHOLD = 120

# Имя сервиса Windows
SERVICE_NAME = "WatcherManagerAgent"
SERVICE_DISPLAY_NAME = "Watcher Manager — Учёт рабочего времени"
SERVICE_DESCRIPTION = "Мониторинг рабочих станций. Ведётся учёт активных приложений и рабочего времени."
