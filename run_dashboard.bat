@echo off
echo ==========================================
echo   Nifty Market Intelligence Dashboard
echo ==========================================
echo.

REM --- Process Cleanup ---
echo [0/4] Stopping existing processes...
for /f "tokens=5" %%a in ('netstat -aon ^| findstr :8501') do taskkill /f /pid %%a 2>nul

REM --- Anaconda Detection & Activation ---
set "CONDA_ACTIVATE="
for %%P in (
    "D:\anaconda3\Scripts\activate.bat"
    "D:\miniconda3\Scripts\activate.bat"
    "%USERPROFILE%\anaconda3\Scripts\activate.bat"
    "%USERPROFILE%\miniconda3\Scripts\activate.bat"
    "C:\ProgramData\anaconda3\Scripts\activate.bat"
    "C:\ProgramData\miniconda3\Scripts\activate.bat"
    "%USERPROFILE%\AppData\Local\Continuum\anaconda3\Scripts\activate.bat"
) do (
    if exist %%P (
        set "CONDA_ACTIVATE=%%P"
        goto :FOUND_CONDA
    )
)

:FOUND_CONDA
if defined CONDA_ACTIVATE (
    echo [0/2] Activating Anaconda environment...
    call %CONDA_ACTIVATE%
) else (
    echo [!] Anaconda not found in common paths. Proceeding with system environment...
)

echo [1/4] Fixing dependencies...
python fix_library.py
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo ERROR: Dependency fix failed.
    pause
    exit /b %ERRORLEVEL%
)

echo [2/4] Updating Market Data...
python data_manager.py
if %ERRORLEVEL% NEQ 0 (
    echo.
    echo ERROR: Data update failed. Check your internet connection or python installation.
    pause
    exit /b %ERRORLEVEL%
)
echo.
echo [3/4] Launching Stocko Live Data Collector (background)...
start /b python collector_service.py > collector.log 2>&1

echo [4/4] Launching Streamlit Dashboard...
streamlit run app.py
pause
