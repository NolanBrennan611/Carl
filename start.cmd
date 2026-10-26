@echo off
rem Start Carl from this folder.   Usage:  .\start -dev
rem (In PowerShell, plain "start" is a built-in alias, so type the leading ".\")
setlocal
cd /d "%~dp0"

if /i "%~1"=="-dev" goto dev
echo Usage: .\start -dev     Run the dev bot using the settings in .env
exit /b 2

:dev
set "PATH=%USERPROFILE%\.local\bin;%PATH%"

where uv >nul 2>&1
if errorlevel 1 (
  echo uv was not found. Install it from https://docs.astral.sh/uv/ or restart VS Code.
  exit /b 1
)

if not exist ".env" (
  echo No .env file here. Copy .env.example to .env and fill in your DEV bot token.
  exit /b 1
)

rem Two copies of the bot on one token would both answer every command.
where docker >nul 2>&1
if errorlevel 1 set "PATH=%PATH%;C:\Program Files\Docker\Docker\resources\bin"
for /f %%i in ('docker ps --filter "name=carl" --filter "status=running" -q 2^>nul') do (
  echo The Docker container "carl" is already running this bot. Stop it first:
  echo     docker compose stop
  exit /b 3
)

set "CARL_ENV=dev"
echo Starting Carl ^(dev^). Press Ctrl+C to stop.
uv run python -m carl run
exit /b %errorlevel%
