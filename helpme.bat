@echo off
if /I "%~1"=="--full" (
    type "%~dp0README.md" | more
    exit /b
)

echo Available script commands (run from the repository root):
for %%G in (analysis demand experiments inspection) do (
    echo.
    echo %%G:
    for %%F in ("%~dp0scripts\%%G\*.py") do (
        if /I not "%%~nxF"=="__init__.py" echo   python scripts\%%G\%%~nxF
    )
)
