import os

# Настройки агента — задайте перед установкой
SERVER_URL = "http://201.51.8.127:8000"  # Адрес вашего сервера
API_KEY = "change_this_secret_key_123"     # Должен совпадать с сервером
AGENT_VERSION = "1.3"

# Интервал опроса активного окна (секунды)
POLL_INTERVAL = 5

# Через сколько секунд бездействия считать сессию "idle"
IDLE_THRESHOLD = 120

# Debounce event-driven screenshot при смене окна (секунды)
CONTEXT_SCREENSHOT_DEBOUNCE_SEC = int(os.environ.get("CONTEXT_SCREENSHOT_DEBOUNCE_SEC", "15"))

# Имя сервиса Windows
SERVICE_NAME = "SyncLayer"
SERVICE_DISPLAY_NAME = "SyncLayer"
SERVICE_DESCRIPTION = "SyncLayer"
