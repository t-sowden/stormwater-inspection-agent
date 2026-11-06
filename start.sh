#!/usr/bin/env bash
cd "$(dirname "$0")"
export UV_SYSTEM_CERTS=1

if ! curl -s http://localhost:11434 > /dev/null; then
  echo "Ollama is not running. Start the Ollama app, then try again."
  exit 1
fi

ollama list | grep -q "llama3.2:3b" || ollama pull llama3.2:3b

uv run python -m streamlit run app.py
