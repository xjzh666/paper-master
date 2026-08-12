@echo off
REM paper-master Web 版启动脚本（Windows 双击运行）
start "" wsl -e bash -c "cd /home/xiejiezhen/paper-master && source .venv/bin/activate && uvicorn paper_reader.server:app --host 127.0.0.1 --port 8000"
timeout /t 4 /nobreak >nul
start "" http://localhost:8000
