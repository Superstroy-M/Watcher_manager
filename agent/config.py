import os

# Production server (baked into SyncLayerAgent.exe at PyInstaller build time).
# Override at runtime only for dev: SYNCLAYER_SERVER_URL / SYNCLAYER_API_KEY
SERVER_URL = os.environ.get("SYNCLAYER_SERVER_URL", "https://watcher.tunellink.ru").rstrip("/")
API_KEY = os.environ.get("SYNCLAYER_API_KEY", "change_this_secret_key_123")
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
