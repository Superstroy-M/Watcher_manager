# Развёртывание через Group Policy (GPO)

Самый быстрый способ поставить агент на все ПК без ручной работы.

Целевая схема на каждом ПК:

- **1** процесс `SyncLayerAgent.exe`
- **1** Scheduled Task `SyncLayerAgent` (`ONLOGON`)
- **0** Windows Services
- **0** tray helpers

## Что нужно заранее

- Домен Active Directory (все ПК в домене) или удалённый запуск `install.bat`
- Доступ к Domain Controller
- Сетевая папка (share), видимая всем ПК домена
- Собранный `SyncLayerAgent.exe` в share

## Шаг 1 — Подготовить сетевую папку

1. На сервере создайте папку, например `C:\Shares\SyncLayer`
2. Расшарьте с доступом на чтение для `Domain Computers`
3. UNC путь будет: `\\ВАШ_СЕРВЕР\SyncLayer`
4. Скопируйте в share:
   - `SyncLayerAgent.exe`
   - `install_common.ps1`
   - `install_finalize.ps1`
   - `install_verify.ps1`
   - `gpo_deploy.bat`

Полная установка из исходников также доступна через `install.bat`.

## Шаг 2 — Настроить gpo_deploy.bat

Откройте `gpo_deploy.bat` и замените:

```bat
set SOURCE=\\YOUR_SERVER\SyncLayer\agent
```

на ваш UNC путь.

## Шаг 3 — Создать GPO

1. Откройте **Group Policy Management** (`gpmc.msc`)
2. Создайте GPO, например `SyncLayer Deploy`
3. Перейдите:
   ```
   Computer Configuration
   └─ Policies
      └─ Windows Settings
         └─ Scripts (Startup/Shutdown)
            └─ Startup
   ```
4. Добавьте `gpo_deploy.bat`
5. Примените GPO к нужному OU

## Шаг 4 — Применить

GPO применяется при **следующем входе пользователя** (задача `ONLOGON`).

Принудительно обновить политику:

```cmd
gpupdate /force
```

## Если нет домена (рабочая группа)

```cmd
psexec \\192.168.1.100 -u Администратор -p пароль -s cmd /c "\\СЕРВЕР\SyncLayer\agent\install.bat"
```

Или one-file установка:

```cmd
\\СЕРВЕР\SyncLayer\agent\INSTALL-ONE.bat
```

## Проверка после установки

На ПК сотрудника:

```cmd
install_verify.bat
```

Или в PowerShell:

```powershell
powershell -File "C:\Program Files\SyncLayer\install_verify.ps1"
```

Ожидаемый результат:

- `SyncLayerAgent.exe processes : 1`
- `SyncLayer service installed  : False`
- `SyncLayerAgent task present  : True`
- `Legacy scheduled tasks       : (none)`
- `Registry Run entries         : (none)`
