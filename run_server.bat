@echo off
cd /d %~dp0
python -c "from dotenv import load_dotenv; load_dotenv(); import os; print('[RITA] SEARXNG_URL=' + (os.getenv('SEARXNG_URL') or 'ABSENT'))"
python -m uvicorn server.main:app --host 127.0.0.1 --port 8000 --log-level info
pause
