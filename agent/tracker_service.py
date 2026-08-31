"""
Windows Service для агента мониторинга.

Запускается от имени SYSTEM — обычный пользователь не может остановить.
При сбое автоматически перезапускается через 10 секунд.

Установка:   python tracker_service.py install
Запуск:      python tracker_service.py start
Остановка:   python tracker_service.py stop   (только Администратор)
Удаление:    python tracker_service.py remove  (только Администратор)
"""
import sys
import os
import time
import logging
import subprocess
import threading
import win32service
import win32serviceutil
import win32event
import servicemanager

# Добавляем папку агента в sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import SERVICE_NAME, SERVICE_DISPLAY_NAME, SERVICE_DESCRIPTION
from process_monitor import ProcessMonitor
from network_monitor import NetworkMonitor
from print_monitor import PrintMonitor

# Логирование в файл рядом с агентом
LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "agent.log")
logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("service")


class WatcherService(win32serviceutil.ServiceFramework):
    _svc_name_ = SERVICE_NAME
    _svc_display_name_ = SERVICE_DISPLAY_NAME
    _svc_description_ = SERVICE_DESCRIPTION

    def __init__(self, args):
        win32serviceutil.ServiceFramework.__init__(self, args)
        self._stop_event = win32event.CreateEvent(None, 0, 0, None)
        self._tracker = None
        self._sender = None
        self._screenshots = None
        self._processes = None
        self._network = None
        self._print = None
        self._tray_proc = None

    def SvcStop(self):
        logger.info("Service stop requested")
        self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
        win32event.SetEvent(self._stop_event)

    def SvcDoRun(self):
        # Сразу отвечаем SCM — иначе ошибка 1053
        self.ReportServiceStatus(win32service.SERVICE_RUNNING)
        logger.info("SyncLayer service starting")
        try:
            self._run()
        except Exception as e:
            logger.exception("Service crashed: %s", e)
        finally:
            if self._tracker:
                self._tracker.stop()
            if self._sender:
                self._sender.stop()
            if self._screenshots:
                self._screenshots.stop()
            if self._processes:
                self._processes.stop()
            if self._network:
                self._network.stop()
            if self._print:
                self._print.stop()
        logger.info("SyncLayer service stopped")

    def _run(self):
        # В Session 0 нельзя корректно снимать пользовательский экран/активное окно:
        # эти модули запускаются из user-сессии через SyncLayerAgent task.
        self._tracker = None
        self._sender = None
        self._screenshots = None
        self._processes = ProcessMonitor()
        self._network = NetworkMonitor()
        self._print = PrintMonitor()

        self._processes.start()
        self._network.start()
        self._print.start()

        logger.info("Service modules started (process/network/print). User activity modules run in SyncLayerAgent task.")
        win32event.WaitForSingleObject(self._stop_event, win32event.INFINITE)

    def _start_tray(self):
        """Запуск иконки в трее от имени текущего пользователя через Task Scheduler."""
        try:
            agent_dir = os.path.dirname(os.path.abspath(__file__))
            python_exe = sys.executable
            tray_script = os.path.join(agent_dir, "tray_app.py")
            task_name = "WatcherManagerTray"

            # Создаём задачу в планировщике, которая запускается при входе любого пользователя
            cmd = (
                f'schtasks /Create /F /TN "{task_name}" '
                f'/TR "\\"{python_exe}\\" \\"{tray_script}\\"" '
                f"/SC ONLOGON /RL HIGHEST"
            )
            subprocess.run(cmd, shell=True, capture_output=True)
            # Немедленно запустить для текущего пользователя
            subprocess.Popen([python_exe, tray_script])
        except Exception as e:
            logger.warning(f"Tray startup failed (non-critical): {e}")


def _configure_service_recovery():
    """
    Настраивает автоматический перезапуск сервиса при сбое.
    Вызывается после установки.
    """
    try:
        import subprocess
        cmd = (
            f'sc failure "{SERVICE_NAME}" reset= 86400 '
            f'actions= restart/10000/restart/10000/restart/10000'
        )
        subprocess.run(cmd, shell=True, capture_output=True)
        logger.info("Service recovery configured")
    except Exception as e:
        logger.warning(f"Could not configure recovery: {e}")


def _protect_service():
    """
    Устанавливает защиту сервиса от остановки обычным пользователем
    через изменение SDDL (дескриптор безопасности).
    Только Администраторы и SYSTEM смогут управлять сервисом.
    """
    try:
        import subprocess
        # D: — DACL; A — Allow; 0x00020002 — SERVICE_START; только Administrators (LA) и SYSTEM (SY)
        # Запрещаем всем остальным (WD — Everyone) останавливать сервис
        sddl = f'D:(A;;CCLCSWLOCRRC;;;SY)(A;;CCDCLCSWRPWPDTLOCRSDRCWDWO;;;BA)'
        cmd = f'sc sdset "{SERVICE_NAME}" "{sddl}"'
        subprocess.run(cmd, shell=True, capture_output=True)
        logger.info("Service ACL configured (users cannot stop)")
    except Exception as e:
        logger.warning(f"Could not set service ACL: {e}")


if __name__ == "__main__":
    if len(sys.argv) == 1:
        servicemanager.Initialize()
        servicemanager.PrepareToHostSingle(WatcherService)
        servicemanager.StartServiceCtrlDispatcher()
    else:
        win32serviceutil.HandleCommandLine(WatcherService)
        if len(sys.argv) > 1 and sys.argv[1].lower() == "install":
            _configure_service_recovery()
            _protect_service()
