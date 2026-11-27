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

# Tu mua thu nghiem: 14:05 thu 2-6, quet 14:10-14:25 (moi 5 phut) roi tu tat; khong canh bao gia. Go: Unregister-ScheduledTask -TaskName "Wyckoff Intraday"
$bat2 = Join-Path $PSScriptRoot "intraday.bat"
$action2 = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c `"$bat2`" --loop --only-auto"
$trigger2 = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At 2:05PM
$settings2 = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 40) -RunOnlyIfNetworkAvailable
Register-ScheduledTask -TaskName "Wyckoff Intraday" -Action $action2 -Trigger $trigger2 -Settings $settings2 `
    -Description "Tu mua thu nghiem 14h10-14h29 (so lenh thu nghiem)" -Force | Out-Null
Write-Host "Da dang ky task 'Wyckoff Intraday' (14:05-14:29, thu 2-6)."

# Xem lai so lenh thu nghiem: 16:00 thu 6 (Claude Code chi doc, ghi bao cao vao logs\, gui tom tat Telegram). Go: Unregister-ScheduledTask -TaskName "Wyckoff Weekly Review"
$bat3 = Join-Path $PSScriptRoot "weekly-review.bat"
$action3 = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c `"$bat3`""
$trigger3 = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Friday -At 4:00PM
$settings3 = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Minutes 30) -RunOnlyIfNetworkAvailable
Register-ScheduledTask -TaskName "Wyckoff Weekly Review" -Action $action3 -Trigger $trigger3 -Settings $settings3 `
    -Description "Xem lai so lenh thu nghiem hang tuan" -Force | Out-Null
Write-Host "Da dang ky task 'Wyckoff Weekly Review' (16:00 thu 6)."
