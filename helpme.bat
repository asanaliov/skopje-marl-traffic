@echo off
if /I "%~1"=="--full" (
    type "%~dp0scripts.md" | more
    exit /b
)

echo Available script commands (run from the repository root):
for %%G in (analysis demand environment_inspection experiments network_inspection setup sumo_visualization) do (
    echo.
    echo %%G:
    for %%F in ("%~dp0scripts\%%G\*.py") do (
        if /I not "%%~nxF"=="__init__.py" echo   python scripts\%%G\%%~nxF
    )
)
