@echo off

:: This script compiles translation files.
:: It assumes you have the QGIS environment (and thus pylupdate6, lrelease) in your PATH.
:: Run this from the OSGeo4W Shell.

echo.
echo Creating/updating translation source file (i18n/de.ts)...
if not exist i18n mkdir i18n
setlocal enabledelayedexpansion
set "PY_FILES="
for /f "delims=" %%i in ('dir /s /b *.py ^| findstr /V /I /C:"__pycache__" /C:"\.git" /C:"\.venv" /C:"release.py"') do (
    set "PY_FILES=!PY_FILES! "%%i""
)
pylupdate6 -noobsolete -verbose !PY_FILES! -ts i18n/de.ts
endlocal

echo.
echo Compiling translation file (i18n/de.qm)...
echo NOTE: This will only work if you have already translated i18n/de.ts using Qt Linguist.
lrelease i18n/de.ts

echo.
echo Compilation finished.