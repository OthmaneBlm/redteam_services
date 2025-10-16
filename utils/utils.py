
from typing import Optional, List, Callable, Any, Dict
from uuid import UUID
from datetime import datetime
from utils.logger import setup_logging
from services.models import AttackExecution, engine, create_db_and_tables

# Azure OpenAI SDK (async client)
from openai import AsyncAzureOpenAI

# DeepTeam imports
from deepteam import red_team
from deepteam.vulnerabilities import Bias, PIILeakage, Competition, Misinformation, PromptLeakage
from deepteam.attacks.single_turn import ROT13, PromptInjection, Roleplay


logger = setup_logging()  


# ---------------------------
# Attack/vulnerability mapping
# ---------------------------
def get_attack_class(attack_type: Optional[str], weight: int = 1):
    attack_map = {
        "rot 13": ROT13,
        "prompt injection": PromptInjection,
        "role play": Roleplay,
    }

    if not attack_type:
        return None

    attack_type_lower = attack_type.lower()
    cls = attack_map.get(attack_type_lower)
    if cls:
        logger.debug("Mapped attack_type=%s to class=%s with weight=%d", attack_type, cls.__name__, weight)
        return cls(weight=weight)
    logger.warning("No mapping for attack_type=%s", attack_type)
    return None


def get_vulnerability_class(vulnerability_type: Optional[str], category: Optional[str] = None):
    if not vulnerability_type:
        return None

    vt = vulnerability_type.lower()
    if vt == "bias":
        if category:
            logger.debug("Using Bias vulnerability (category=%s)", category)
            return Bias(types=[category])#types=["race", "gender", "religion"]
        
        return Bias()
    if vt == "prompt leakage":
        if category:
            logger.debug("Using pormpt leakage vulnerability (category=%s)", category)
            return PromptLeakage(types=[category])#types=["secrets_and_credentials", "guard_exposure"]
        
        return PromptLeakage()
    if vt == "pii leakage":
        if category:
            logger.debug("Using pii leakage vulnerability (category=%s)", category)
            return PIILeakage(types=[category])
        
        return PIILeakage()
    if vt == "competition":
        if category:
            logger.debug("Using competition vulnerability (category=%s)", category)
            return Competition(types=[category])#["discreditation", "competitor_mention"]
        
        return Competition()
    if vt == "misinformation":
        if category:
            logger.debug("Using misinformation vulnerability (category=%s)", category)
            return Misinformation(types=[category])#["factual_errors", "unsupported_claims"]
        
        return Misinformation()
    logger.warning("No mapping for vulnerability_type=%s", vulnerability_type)
    return None

