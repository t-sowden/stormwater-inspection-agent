@echo off
cd /d "%~dp0"
set UV_SYSTEM_CERTS=1

curl -s http://localhost:11434 >nul || (
  echo Ollama is not running. Start the Ollama app, then try again.
  pause
  exit /b
)

ollama list | findstr /C:"llama3.2:3b" >nul || ollama pull llama3.2:3b

uv run streamlit run app.py
pause
