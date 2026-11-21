# Dang ky lich quet Wyckoff luc 15:30 thu 2-6 trong Windows Task Scheduler.
# Chay:  powershell -ExecutionPolicy Bypass -File D:\wyckoff-app\scripts\register-task.ps1
# Go:    Unregister-ScheduledTask -TaskName "Wyckoff Scanner" -Confirm:$false
$bat = Join-Path $PSScriptRoot "scan.bat"
$action = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c `"$bat`""
$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At 3:30PM
# StartWhenAvailable: may tat/ngu luc 15:30 thi chay bu khi bat lai
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 30) -RunOnlyIfNetworkAvailable
Register-ScheduledTask -TaskName "Wyckoff Scanner" -Action $action -Trigger $trigger -Settings $settings `
    -Description "Quet Wyckoff cuoi ngay va gui Telegram" -Force | Out-Null
Write-Host "Da dang ky task 'Wyckoff Scanner' (15:30, thu 2-6)."

# Canh bao gia trong phien: 9:10 thu 2-6, tu chay den 14:45 (kiem tra moi 5 phut). Go: Unregister-ScheduledTask -TaskName "Wyckoff Intraday"
$bat2 = Join-Path $PSScriptRoot "intraday.bat"
$action2 = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c `"$bat2`" --loop"
$trigger2 = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At 9:10AM
$settings2 = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 6) -RunOnlyIfNetworkAvailable
Register-ScheduledTask -TaskName "Wyckoff Intraday" -Action $action2 -Trigger $trigger2 -Settings $settings2 `
    -Description "Canh bao gia trong phien (cat lo / muc tieu / vung mua)" -Force | Out-Null
Write-Host "Da dang ky task 'Wyckoff Intraday' (9:10-14:45, thu 2-6)."
