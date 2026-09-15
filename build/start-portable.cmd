@echo off
setlocal
set "PAPERMIND_DATA_DIR=%~dp0data"
set "PAPERMIND_DB_PATH="
set "PAPERMIND_MASTER_KEY_PATH="
set "PAPERMIND_NO_BROWSER="
set "PAPERMIND_PORT="
start "" "%~dp0PaperMind.exe"
endlocal
