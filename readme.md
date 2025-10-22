# RedTeam Backend — Quickstart

## Purpose
RedTeam backend — simulate different types of attacks (prompt injection, PII leakage, misinformation, etc.), orchestrate attack runs against different targets (Azure OpenAI, local RAG, Ollama LLMs), and store execution artifacts/results.

## Prepare a simple Python venv & install requirements

create venv (uses system python3)
python3 -m venv .venv

activate venv
source .venv/bin/activate
windows (PowerShell):
.venv\Scripts\Activate.ps1
windows (cmd.exe):
.venv\Scripts\activate.bat

upgrade pip and install deps
python -m pip install --upgrade pip
pip install -r requirements.txt


Put secrets (API keys, DB URLs) in a .env file and do not commit it. Add .env to .gitignore.

## Install Ollama & pull models

Install Ollama following the official installer for your platform, then pull the models used for local tests.

verify ollama installed
ollama --version

run the 4B model locally
ollama run jaahas/qwen3-abliterated:4b

run the 0.6B model locally
ollama run huihui_ai/qwen3-abliterated:0.6b


ollama list shows installed models. Make sure you have enough disk & memory for the 4B model.

3 — Start the FastAPI app (development)
from repo root, ensure venv is active
uvicorn app:app --reload --host 0.0.0.0 --port 8000


Adjust the import path if your app entrypoint is app.main:app or similar.

## Example input object (attack probe)

Use this JSON as the request body when creating/launching a probe in the backend (copy exactly):

{
  "vulnerability_type": "pii_leakage",
  "vulnerability_subtype": "direct_disclosure",
  "attack_method": "prompt_injection",
  "probe_metadata": {
    "launched_from": "vulnerability_catalog",
    "launched_at": "2025-10-12T17:28:02.049Z",
    "total_targets": 1,
    "total_attacks": 6
  },
  "id": "9188f783-6bb7-4663-86b6-ce39b48390b2",
  "project_id": "efee9664-27e8-4ff3-9197-3ca8361b7521",
  "target_id": "18b75cdb-73d2-4580-bdd4-c5dc5a20af8f",
  "vulnerability_catalog_id": "9ca480bc-ae92-4ab6-a439-d177ff24e1b0",
  "status": "pending",
  "started_at": null,
  "completed_at": null,
  "execution_duration_ms": null,
  "result_data": null,
  "severity_score": null,
  "success_indicator": null,
  "confidence_score": null,
  "error_message": null,
  "created_at": "2025-10-12T17:28:02.498076Z",
  "updated_at": "2025-10-12T17:28:02.498076Z",
  "target_name": "AZURE_OPENAI"/ or "CUSTOM_QA or "OLLAMA"
  "target_description": "",
  "target_endpoint_url": "https://azure####.openai.azure.com/",
  "target_auth_method": "put the key for azureopenia trial",
  "target_endpoint_type": "OAI",
  "target_input_field": "question",
  "target_output_field": "answer",
  "target_endpoint_config": {
    "headers": {
      "Content-Type": "application/json"
    },
    "timeout": 30,
    "verify_ssl": true
  },
  "target_additional_params": {},
  "target_labels": {
    "environment": "production",
    "model": "gpt-4",
    "api_version": for azure openai
  }
}

