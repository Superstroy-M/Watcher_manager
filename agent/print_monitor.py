"""
Мониторинг печати через Windows Print Spooler (WMI).
Перехватывает события при добавлении задания в очередь.
"""
import time
import socket
import logging
import threading
from datetime import datetime
from typing import Optional

import requests

from config import SERVER_URL, API_KEY

logger = logging.getLogger("print")
HEADERS = {"X-API-Key": API_KEY, "Content-Type": "application/json"}


class PrintMonitor:
    def __init__(self):
        self._running = False
        self._thread: Optional[threading.Thread] = None

    def start(self):
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False

    def _loop(self):
        """Подписываемся на WMI события очереди печати."""
        try:
            import wmi
            c = wmi.WMI()
            watcher = c.Win32_PrintJob.watch_for("creation")
            logger.info("Print monitor started via WMI")

            while self._running:
                try:
                    job = watcher(timeout_ms=5000)
                    if job:
                        self._on_print_job(job)
                except wmi.x_wmi_timed_out:
                    continue
                except Exception as e:
                    logger.warning(f"WMI watch error: {e}")
                    time.sleep(10)

        except ImportError:
            logger.warning("WMI not available, using polling fallback")
            self._loop_polling()
        except Exception as e:
            logger.warning(f"Print monitor WMI init failed: {e}, using polling")
            self._loop_polling()

    def _loop_polling(self):
        """Fallback: опрос очереди печати раз в 30 сек."""
        import win32print

        seen_jobs = set()
        while self._running:
            try:
                printers = win32print.EnumPrinters(
                    win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS
                )
                for _, _, printer_name, _ in printers:
                    try:
                        handle = win32print.OpenPrinter(printer_name)
                        jobs = win32print.EnumJobs(handle, 0, 100, 1)
                        for job in jobs:
                            job_id = (printer_name, job.get("JobId", 0))
                            if job_id not in seen_jobs:
                                seen_jobs.add(job_id)
                                self._send_job(
                                    document=job.get("Document", ""),
                                    printer=printer_name,
                                    pages=job.get("TotalPages", 0) or job.get("PagesPrinted", 0),
                                    username=job.get("UserName", ""),
                                )
                        win32print.ClosePrinter(handle)
                    except Exception:
                        pass
            except Exception as e:
                logger.warning(f"Print poll error: {e}")
            time.sleep(30)

    def _on_print_job(self, job):
        try:
            self._send_job(
                document=getattr(job, "Document", "") or "",
                printer=getattr(job, "Name", "").split(",")[0] if getattr(job, "Name", "") else "",
                pages=getattr(job, "TotalPages", 0) or 0,
                username=getattr(job, "Owner", "") or "",
            )
        except Exception as e:
            logger.warning(f"Print job parse error: {e}")

    def _send_job(self, document: str, printer: str, pages: int, username: str):
        payload = {
            "hostname": socket.gethostname(),
            "printed_at": datetime.utcnow().isoformat(),
            "document_name": document,
            "printer_name": printer,
            "pages": pages or 0,
            "username": username,
        }
        try:
            resp = requests.post(
                f"{SERVER_URL}/api/print",
                json=payload,
                headers=HEADERS,
                timeout=10,
            )
            resp.raise_for_status()
            logger.info(f"Print job sent: {document} ({pages} стр.) → {printer}")
        except Exception as e:
            logger.warning(f"Print job send failed: {e}")
