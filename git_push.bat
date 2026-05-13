@echo off
setlocal EnableDelayedExpansion

cd /d "%~dp0"

echo ============================================================
echo  SimpliSQL - Git Add / Commit / Push
echo ============================================================
echo.

:: Ensure this is a git repository
if not exist ".git" (
    echo [ERROR] This folder is not a git repository.
    pause
    exit /b 1
)

:: Show current branch
for /f "delims=" %%b in ('git rev-parse --abbrev-ref HEAD 2^>nul') do set "BRANCH=%%b"
if "%BRANCH%"=="" (
    echo [ERROR] Could not detect git branch.
    pause
    exit /b 1
)

echo Current branch: %BRANCH%
echo.

:: Show status
echo [1/4] Git status:
git status --short
echo.

:: Stage all changes
echo [2/4] Staging files...
git add .
if errorlevel 1 (
    echo [ERROR] git add failed.
    pause
    exit /b 1
)

:: Ask for commit message
set "COMMIT_MSG="
set /p COMMIT_MSG=Enter commit message (leave blank for auto message): 
if "%COMMIT_MSG%"=="" (
    set "COMMIT_MSG=Update SimpliSQL files"
)

echo.
echo [3/4] Committing...
git commit -m "%COMMIT_MSG%"
if errorlevel 1 (
    echo [INFO] Nothing to commit or commit failed.
    echo       Continuing to push in case branch is ahead.
)

echo.
echo [4/4] Pushing to origin/%BRANCH% ...
git push origin %BRANCH%
if errorlevel 1 (
    echo [ERROR] git push failed. Check remote/credentials/network.
    pause
    exit /b 1
)

echo.
echo [SUCCESS] Push completed.
echo ============================================================
pause
