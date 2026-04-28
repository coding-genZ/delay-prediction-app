@echo off
title Shipment Delay Prediction App
echo ========================================
echo   Starting Shipment Delay Prediction
echo ========================================
echo.

cd /d "%~dp0"

echo Installing dependencies...
call venv\Scripts\activate.bat
pip install -r requirements.txt --quiet

echo.
echo Starting FastAPI backend...
start "FastAPI Backend" cmd /k "cd /d "%~dp0\src" && call ..\venv\Scripts\activate.bat && uvicorn api:app --port 8000"

echo Waiting for backend to start...
timeout /t 5 /nobreak >nul

echo Starting Streamlit frontend...
start "Streamlit Frontend" cmd /k "cd /d "%~dp0\src" && call ..\venv\Scripts\activate.bat && streamlit run app.py"

timeout /t 3 /nobreak >nul

echo.
echo Opening browser...
start http://localhost:8501

echo.
echo ========================================
echo   App is running!
echo   Frontend: http://localhost:8501
echo   Backend:  http://localhost:8000
echo   Close this window to stop.
echo ========================================
pause
