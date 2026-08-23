# Развёртывание через Group Policy (GPO)

Самый быстрый способ поставить агент на все 20 ПК без ручной работы.

## Что нужно заранее

- Домен Active Directory (все ПК в домене)
- Доступ к Domain Controller
- Сетевая папка (share) видна всем ПК домена

## Шаг 1 — Подготовить сетевую папку

1. На сервере создайте папку, например `C:\Shares\SyncLayer`
2. Расшарьте с доступом на чтение для `Domain Computers`:
   - Правая кнопка → Свойства → Доступ → Общий доступ
   - Добавьте `Domain Computers` → Чтение
3. UNC путь будет: `\\ВАШ_СЕРВЕР\SyncLayer`
4. Скопируйте в эту папку всё содержимое папки `agent/`

## Шаг 2 — Настроить gpo_deploy.bat

Откройте `gpo_deploy.bat` и замените:
```
set SOURCE=\\YOUR_SERVER\SyncLayer\agent   → ваш UNC путь
set SVC_NAME=SyncLayer                     → имя сервиса из config.py
```

## Шаг 3 — Создать GPO

1. Откройте **Group Policy Management** (`gpmc.msc`) на контроллере домена
2. Создайте новую политику: ПКМ на домен/OU → *Create a GPO*
3. Назовите, например `SyncLayer Deploy`
4. Правой кнопкой → **Edit**
5. Перейдите:
   ```
   Computer Configuration
   └─ Policies
      └─ Windows Settings
         └─ Scripts (Startup/Shutdown)
            └─ Startup
   ```
6. Добавьте скрипт `gpo_deploy.bat`
7. **OK** → примените GPO к нужному OU с компьютерами

## Шаг 4 — Применить

GPO применяется при **следующей перезагрузке** каждого ПК.

Принудительно без перезагрузки (выполнить на каждом ПК или через remote):
```cmd
gpupdate /force
```

Или удалённо через PowerShell со списком ПК:
```powershell
$computers = @("PC01","PC02","PC03")  # список ПК
foreach ($pc in $computers) {
    Invoke-Command -ComputerName $pc -ScriptBlock { gpupdate /force }
}
```

## Если нет домена (рабочая группа)

Использовать `psexec` от Microsoft Sysinternals:

```cmd
:: Установить на один ПК удалённо
psexec \\192.168.1.100 -u Администратор -p пароль -s cmd /c "\\СЕРВЕР\SyncLayer\agent\install.bat"

:: Или через PowerShell Remoting
Invoke-Command -ComputerName 192.168.1.100 -Credential (Get-Credential) -FilePath "\\СЕРВЕР\SyncLayer\agent\install.bat"
```

## Проверка после установки

```powershell
# Проверить статус сервиса на удалённом ПК
Get-Service -ComputerName PC01 -Name SyncLayer

# Или через sc
sc \\PC01 query SyncLayer
```
