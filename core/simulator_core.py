# core/simulator_core.py
import asyncio
import inspect
import json
import time
import os
import logging
from datetime import datetime
from enum import Enum
from uuid import UUID
from deepteam.red_teamer import RedTeamer
from services.custom_evaluator import AttackEvaluator, AttackSimulator
from utils.utils import get_attack_class, get_vulnerability_class

logger = logging.getLogger(__name__)


class PayloadEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, Enum):
            return obj.value
        if isinstance(obj, UUID):
            return str(obj)
        if isinstance(obj, datetime):
            return obj.isoformat()
        return super().default(obj)


def create_model_callback(payload):
    """Return the correct provider callback based on endpoint type."""
    from services.providers import AzureProvider, RAGProvider, OllamaProvider

    if payload.target_endpoint_type == "CUSTOM_QA":
        return RAGProvider(payload).generate
    if payload.target_endpoint_type == "AZURE_OPENAI":
        return AzureProvider(payload).generate
    return OllamaProvider(payload).generate


def run_simulation(payload):
    """
    Run a simulation using the payload configuration.
    - Updates payload fields (status, result_data, timestamps, etc.)
    - Writes the updated payload as JSON to ./attack_results/{id}.json
    - Returns the updated payload (NOT committed to DB)
    """
    start_time = time.perf_counter()

    payload.status = "running"
    payload.updated_at = datetime.utcnow()

    try:
        model_callback_ = create_model_callback(payload)
        probe_meta = payload.probe_metadata or {}

        vulnerability = get_vulnerability_class(
            getattr(payload, "vulnerability_type", None),
            getattr(payload, "vulnerability_subtype", None),
        )
        attack = get_attack_class(
            getattr(payload, "attack_method", None),
            getattr(payload, "number_of_attacks", 1)
        )

        rt = RedTeamer(
            simulator_model=AttackSimulator(),
            evaluation_model=AttackEvaluator(),
            max_concurrent=1,
        )

        attacks = [attack] if attack else []
        vulns = [vulnerability] if vulnerability else []
        attacks_per_vuln = int(probe_meta.get("total_attacks", getattr(payload, "number_of_attacks", 1) or 1))

        maybe = rt.red_team(
            attacks=attacks,
            vulnerabilities=vulns,
            model_callback=model_callback_,
            attacks_per_vulnerability_type=attacks_per_vuln,
            ignore_errors=True,
        )

        result_obj = asyncio.run(maybe) if inspect.isawaitable(maybe) else maybe
        result_dict = result_obj.model_dump(by_alias=True)

        payload.result_data = json.dumps(result_dict, indent=2, cls=PayloadEncoder)
        payload.status = "completed"
        payload.completed_at = datetime.utcnow()
        payload.execution_duration_ms = int((time.perf_counter() - start_time) * 1000)
        payload.updated_at = datetime.utcnow()

    except Exception as e:
        logger.exception(f"Simulation failed for payload {payload.id}: {e}")
        payload.status = "error"
        payload.error_message = str(e)
        payload.updated_at = datetime.utcnow()

    # --- Write payload snapshot to disk ---
    try:
        os.makedirs("./attack_results", exist_ok=True)
        out_path = f"./attack_results/{payload.id}.json"
        with open(out_path, "w") as f:
            json.dump(payload.model_dump(), f, indent=2, cls=PayloadEncoder)
        logger.info(f"Payload snapshot written to {out_path}")
    except Exception as e:
        logger.warning(f"Could not write payload snapshot: {e}")

    return payload
