@echo off
call .venv\Scripts\activate.bat

if not exist cert.pem (
    echo Generating SSL certificate...
    python generate_cert.py
)

uvicorn app:app --host 0.0.0.0 --port 8000 --ssl-keyfile cert.key --ssl-certfile cert.pem
