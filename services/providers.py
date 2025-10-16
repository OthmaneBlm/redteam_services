
# app/services/simulate_attacks.py
from typing import Optional, List, Callable, Any, Dict
from uuid import UUID
from datetime import datetime
import asyncio
import os
import time
import inspect
import os
import time
import aiohttp


# your models module - adjust path if needed (app.models or models)
from services.models import AttackExecution, engine, create_db_and_tables

# Azure OpenAI SDK (async client)
from openai import AsyncAzureOpenAI

# DeepTeam imports

from deepteam.vulnerabilities import Bias
from deepteam.attacks.single_turn import ROT13, Leetspeak, Base64
from services.custom_evaluator import *

# SQLAlchemy helpers
from sqlalchemy import func
from utils.logger import setup_logging

logger = setup_logging()
# ---------------------------
# Azure provider wrapper
# ---------------------------
class AzureProvider:
    """
    Azure OpenAI provider that exposes `async def generate(prompt: str) -> str`
    which deepteam expects as an async model_callback.
    """
    def __init__(self, payload: 'AttackExecution'):
        self.deployment = payload.target_name
        self.endpoint = payload.target_endpoint_url
        self.api_version = payload.target_labels.get("api_version") or os.getenv("AZURE_OPENAI_API_VERSION")
        # prefer target.api_key then env var
        self.api_key = getattr(payload, "targte_api_key") or os.getenv("AZURE_OPENAI_API_KEY")

        if not self.api_key:
            raise RuntimeError(f"Azure API key not found for target {getattr(payload, 'name', '<unknown>')}")

        self._client = None
        logger.debug("AzureProvider created for target=%s deployment=%s", getattr(payload, "name", None), self.deployment)

    def _ensure_client(self):
        """Lazily initialize the Azure OpenAI client."""
        if self._client is None:
            logger.debug("Initializing AsyncAzureOpenAI client for endpoint=%s", self.endpoint)
            
            self._client = AsyncAzureOpenAI(
                api_key=self.api_key,
                azure_endpoint=self.endpoint,
                api_version=self.api_version
            )

    async def generate(self, prompt: str) -> str:
        """
        Async model callback: accepts prompt (string) and returns model output (string).
        """
        self._ensure_client()
        start = time.perf_counter()
        logger.debug("AzureProvider.generate called (deployment=%s) prompt_len=%d", self.deployment, len(prompt))

        try:
            resp = await self._client.chat.completions.create(
                model=self.deployment,
                messages=[{"role": "user", "content": prompt}],
                max_tokens=800,
                temperature=0.7
            )
            content = resp.choices[0].message.content
            dt = time.perf_counter() - start
            logger.debug("Azure response received in %.3fs (deployment=%s) resp_len=%d", dt, self.deployment, len(content or ""))
            return content

        except Exception as e:
            return f"ERROR: {str(e)}"
        

class RAGProvider:
    """
    Local or remote RAG provider that exposes `async def generate(prompt: str) -> str`
    following the same structure as AzureProvider.
    """

    def __init__(self, payload: AttackExecution):
        self.endpoint = payload.target_endpoint_url # adjust if needed
        self.collection_name = "hr"
        self.input_name = payload.target_input_field
        self.output_name = payload.target_output_field

        # static configuration for now
        self.top_k = 5
        self.max_answer_tokens = 400
        self.temperature = 0

        self._session = None

        logger.debug(
            "RAGProvider created for target=%s collection=%s endpoint=%s",
            getattr(payload, "name", None),
            self.collection_name,
            self.endpoint,
        )

    def _ensure_session(self):
        """Lazily initialize aiohttp session."""
        if self._session is None:
            self._session = aiohttp.ClientSession()
            logger.debug("Initialized aiohttp session for RAGProvider")

    async def generate(self, prompt: str) -> str:
        """
        Async model callback: accepts prompt (string) and returns model output (string).
        """
        self._ensure_session()
        start = time.perf_counter()
        logger.debug(
            "RAGProvider.generate called (collection=%s) prompt_len=%d",
            self.collection_name,
            len(prompt),
        )

        body = {
            self.input_name: prompt,
            "collection_name": self.collection_name,
            "top_k": self.top_k,
            "max_answer_tokens": self.max_answer_tokens,
            "temperature": self.temperature,
        }
        

        try:
            async with self._session.post(self.endpoint, json=body) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    logger.error("RAG API returned status %s: %s", resp.status, text)
                    return f"ERROR: RAG API returned {resp.status}: {text}"

                data = await resp.json()
                dt = time.perf_counter() - start
                logger.debug(
                    "RAG response received in %.3fs (collection=%s)",
                    dt,
                    self.collection_name,
                )

                # Adjust key based on your RAG API response schema
                answer = data.get(self.output_name) or data.get("response") or str(data)
                return answer

        except Exception as e:
            logger.exception("Error calling RAG API")
            return f"ERROR: {str(e)}"

    async def close(self):
        """Gracefully close the aiohttp session when done."""
        if self._session is not None:
            await self._session.close()
            self._session = None
            logger.debug("RAGProvider aiohttp session closed")

class OllamaProvider:
    def __init__(self, payload: AttackExecution):
        self.api_url = payload.target_endpoint_url # adjust if needed
        self.model_name = payload.target_name
        

    def generate(self, prompt: str) -> str:
        logger.info(f"Sending prompt to Ollama: {prompt}")
        payload = {
            "model":self.model_name, 
            "messages": [{"role": "user", "content": prompt}]
        }

        try:
            response = requests.post(self.api_url, json=payload, stream=True)
        except requests.RequestException as e:
            logger.error(f"Request to Ollama failed: {e}")
            raise

        assistant_content = ""

        if response.status_code == 200:
            logger.info("Streaming response from Ollama...")
            for line in response.iter_lines(decode_unicode=True):
                if line:
                    try:
                        data = json.loads(line)
                        logger.debug(f"Received chunk: {data}")
                        if "message" in data and data["message"]["role"] == "assistant":
                            content = data["message"]["content"]
                            assistant_content += content
                            
                            logger.debug(f"Received chunk: {content}")
                    except json.JSONDecodeError:
                        logger.warning(f"Failed to parse line: {line}")
        else:
            logger.error(f"Ollama API returned error: {response.status_code} {response.text}")
            raise RuntimeError(f"Ollama API error: {response.status_code} {response.text}")
        no_thinking_response =extract_json_string(assistant_content)
        logger.info(f"Completed response: {no_thinking_response}")
        return no_thinking_response

    async def a_generate(self, prompt: str) -> str:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.generate, prompt)