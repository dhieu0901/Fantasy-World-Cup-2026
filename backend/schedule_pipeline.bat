@echo off
cd /d "%~dp0"
if not exist logs mkdir logs

echo Setting up Auto-Sync...
schtasks /create /tn "WC2026 Pipeline" /tr "cmd.exe /c python \"%~dp0pipeline.py\" --schedule >> \"%~dp0logs\pipeline.log\" 2>&1" /sc minute /mo 240 /f

echo Setting up Daily Backup...
schtasks /create /tn "WC2026 Backup" /tr "cmd.exe /c python \"%~dp0backup_db.py\" >> \"%~dp0logs\backup.log\" 2>&1" /sc daily /st 03:00 /f

echo Tasks scheduled successfully! You can verify them in Windows Task Scheduler.
pause
