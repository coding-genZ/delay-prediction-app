#!/bin/bash
echo "========================================"
echo "  Starting Shipment Delay Prediction"
echo "========================================"
echo

cd "$(dirname "$0")"

echo "Installing dependencies..."
source venv/bin/activate
pip install -r requirements.txt --quiet

echo
echo "Starting FastAPI backend..."
cd src
uvicorn api:app --port 8000 &
BACKEND_PID=$!

echo "Waiting for backend to start..."
sleep 5

echo "Starting Streamlit frontend..."
streamlit run app.py &
cd ..
FRONTEND_PID=$!

sleep 3

echo
echo "Opening browser..."
if [[ "$OSTYPE" == "darwin"* ]]; then
    open http://localhost:8501
else
    xdg-open http://localhost:8501 2>/dev/null || echo "Open http://localhost:8501 in your browser"
fi

echo
echo "========================================"
echo "  App is running!"
echo "  Frontend: http://localhost:8501"
echo "  Backend:  http://localhost:8000"
echo "  Press Ctrl+C to stop."
echo "========================================"

trap "kill $BACKEND_PID $FRONTEND_PID 2>/dev/null; exit" INT TERM
wait
