@echo off
echo Installing dependencies...
pip install -r requirements.txt
echo.
echo Starting Proposal Insight Engine...
echo Open http://localhost:8000 in your browser.
echo.
uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
