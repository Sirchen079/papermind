@echo off
REM PaperMind 双击启动入口（调用 start.ps1）。传参：start.bat -Dev
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start.ps1" %*
