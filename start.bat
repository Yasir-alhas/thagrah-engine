@echo off
cd /d "%~dp0"
if not exist .venv (python -m venv .venv && .venv\Scripts\pip install -r requirements.txt)
start "" http://127.0.0.1:8100/demo
.venv\Scripts\python -m uvicorn thagrah_engine.api:app --host 127.0.0.1 --port 8100
