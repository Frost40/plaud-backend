param([switch]$Check)

$ErrorActionPreference = 'Stop'
$taskName = 'Plaud dashboard'
if ($Check) {
    $task = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
    if (-not $task) {
        Write-Output 'Plaud dashboard: not registered'
    } else {
        schtasks /query /tn $taskName /fo LIST /v
        if ($LASTEXITCODE -ne 0) { throw 'Could not query the scheduled task' }
    }
    exit 0
}

$project = Split-Path -Parent $PSScriptRoot
$python = Join-Path $project '.venv\Scripts\pythonw.exe'
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) { throw "Missing $python" }
$user = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$action = New-ScheduledTaskAction -Execute $python -Argument '-m app.server' -WorkingDirectory $project
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $user
$principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Principal $principal -Settings $settings -Force | Out-Null
Write-Output 'Plaud dashboard: registered for your next sign-in'
