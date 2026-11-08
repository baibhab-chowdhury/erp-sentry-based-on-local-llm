@echo off
echo ========================================================
echo   Launching ERP-Sentry Dashboard (iRM Enterprise AI Demo)
echo ========================================================
echo.
echo Checking Ollama service status...
curl -s http://127.0.0.1:11434/api/tags >nul 2>&1
if %errorlevel% neq 0 (
    echo [WARNING] Ollama is not detected at http://127.0.0.1:11434
    echo Please make sure Ollama is running: 'ollama serve'
    echo Starting dashboard in offline analysis mode...
) else (
    echo [OK] Ollama is connected and ready!
)
echo.
echo Starting Streamlit on http://localhost:8501 ...
python -m streamlit run app/dashboard.py
pause
