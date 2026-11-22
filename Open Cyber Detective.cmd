@echo off
setlocal
cd /d "%~dp0"
if exist "%LOCALAPPDATA%\Programs\Python\Python310\python.exe" (
  "%LOCALAPPDATA%\Programs\Python\Python310\python.exe" -m backend.demo
) else (
  py -3 -m backend.demo
)
if errorlevel 1 pause
