"""
Safety and abuse-prevention layer for NEXUS.
Keyword-based classifier with local safety log — no API calls required.
"""
import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

SAFETY_LOG_PATH = Path(__file__).parent.parent / "data" / "safety_log.jsonl"


@dataclass
class SafetyResult:
    safe: bool
    category: Optional[str] = None
    is_self_harm: bool = False
    message: str = ""


# Each rule: (category_name, substring_triggers, is_self_harm)
# Triggers are matched as substrings of the lowercased input.
_QUERY_RULES: list[tuple[str, list[str], bool]] = [
    ("self_harm", [
        "how to kill myself",
        "how to commit suicide",
        "ways to die by",
        "suicide methods",
        "self harm methods",
        "how to hurt myself",
        "how to cut myself",
        "want to end my life",
        "painless ways to die",
        "ways to commit suicide",
        "how to hang myself",
        "how to overdose on",
        "best way to die",
        "methods of suicide",
        "self harm ideas",
        "ways to self harm",
        "how to end it all",
    ], True),
    ("violence", [
        "how to kill someone",
        "how to murder someone",
        "how to poison someone",
        "how to strangle someone",
        "how to attack someone",
        "how to hurt someone physically",
        "how to assault someone",
        "how to beat someone up",
        "how to stab someone",
    ], False),
    ("weapons", [
        "how to make a bomb",
        "build a bomb",
        "pipe bomb instructions",
        "homemade explosive",
        "how to make a gun untraceable",
        "3d print a gun",
        "convert to full auto",
        "ghost gun tutorial",
        "make napalm",
        "ricin synthesis",
        "thermite instructions",
        "improvised explosive device",
        "make a silencer illegally",
        "manufacture a firearm illegally",
    ], False),
    ("malware", [
        "write a virus",
        "create malware",
        "ransomware code",
        "keylogger code",
        "how to write ransomware",
        "spyware creation",
        "make a trojan horse virus",
        "botnet setup tutorial",
        "how to make a keylogger",
        "remote access trojan tutorial",
        "rat malware tutorial",
        "write a worm virus",
        "malware that steals",
        "payload generation tutorial",
    ], False),
    ("hacking", [
        "how to hack into someone",
        "how to hack someone",
        "how to steal passwords illegally",
        "credential harvesting tutorial",
        "phishing kit tutorial",
        "how to hack someone's account",
        "steal someone's login",
        "how to break into someone's computer",
        "account takeover tutorial",
        "how to crack passwords illegally",
        "unauthorized access tutorial",
        "how to bypass 2fa illegally",
        "how to hack an account",
    ], False),
    ("fraud_scam", [
        "how to scam people",
        "create a phishing site",
        "run a scam operation",
        "how to defraud someone",
        "carding tutorial",
        "credit card fraud tutorial",
        "wire fraud tutorial",
        "advance fee fraud",
        "romance scam how to",
        "identity theft tutorial",
        "how to fake identity illegally",
        "how to commit insurance fraud",
    ], False),
    ("drugs", [
        "how to synthesize meth",
        "cook meth",
        "synthesize fentanyl",
        "how to make heroin",
        "manufacture illegal drugs",
        "how to make mdma illegally",
        "drug synthesis tutorial",
        "clandestine drug lab",
        "how to make drugs",
    ], False),
    ("stalking", [
        "how to stalk someone",
        "track someone without them knowing",
        "spy on my partner secretly",
        "install spyware on partner's phone",
        "how to follow someone secretly",
        "monitor someone's phone without consent",
        "how to track my girlfriend secretly",
        "how to track my boyfriend secretly",
        "secretly monitor someone",
    ], False),
    ("evasion", [
        "how to evade police",
        "evade law enforcement tutorial",
        "how to destroy evidence of a crime",
        "how to evade arrest",
        "how to avoid being caught by police",
        "flee from law enforcement",
    ], False),
    ("illegal", [
        "how to launder money",
        "money laundering tutorial",
        "how to traffic humans",
        "child exploitation material",
        "buy illegal weapons online",
        "buy illegal drugs online",
        "how to commit tax fraud",
    ], False),
]

# Lighter rules for ingested content — only the most clearly harmful signals.
_CONTENT_RULES: list[tuple[str, list[str], bool]] = [
    ("self_harm",  ["suicide guide", "how to die guide", "self-harm instructions"], True),
    ("weapons",    ["bomb making guide", "explosives synthesis guide", "weapon construction guide"], False),
    ("malware",    ["malware source code", "ransomware kit download", "rat source code"], False),
    ("drugs",      ["drug synthesis guide", "cook meth tutorial", "drug manufacturing tutorial"], False),
    ("fraud_scam", ["phishing kit download", "carding tutorial", "scam template download"], False),
]

_SAFE_REFUSAL = (
    "I can't help with that, but I can help with safer alternatives. "
    "NEXUS is designed to support learning, research, and building — "
    "let me know if there's something constructive I can assist with."
)

_SELF_HARM_REFUSAL = (
    "I care about your wellbeing, and I'm not able to provide information on that.\n\n"
    "If you're going through something difficult, please reach out to someone who can help:\n\n"
    "• **988 Suicide & Crisis Lifeline** — call or text **988** (US, available 24/7)\n"
    "• **Crisis Text Line** — text **HOME** to **741741** (US)\n"
    "• **International resources** — https://www.iasp.info/resources/Crisis_Centres/\n\n"
    "You don't have to go through this alone. Help is available right now."
)


def classify_query(text: str) -> SafetyResult:
    """Classify a user query as safe or harmful. Fast substring matching, no API calls."""
    if not text or not text.strip():
        return SafetyResult(safe=True)
    lowered = text.lower()
    for category, triggers, is_self_harm in _QUERY_RULES:
        for trigger in triggers:
            if trigger in lowered:
                msg = _SELF_HARM_REFUSAL if is_self_harm else _SAFE_REFUSAL
                return SafetyResult(safe=False, category=category, is_self_harm=is_self_harm, message=msg)
    return SafetyResult(safe=True)


def classify_content(title: str, url: str, content: str = "") -> SafetyResult:
    """
    Classify ingested content by title and URL.
    Conservative — only flags clear-cut cases to avoid false positives on legitimate research.
    """
    combined = f"{title} {url}".lower()
    for category, triggers, is_self_harm in _CONTENT_RULES:
        for trigger in triggers:
            if trigger in combined:
                return SafetyResult(
                    safe=False,
                    category=category,
                    is_self_harm=is_self_harm,
                    message="This content has been flagged as potentially harmful.",
                )
    return SafetyResult(safe=True)


def log_blocked(text: str, category: str, action: str, is_self_harm: bool = False) -> None:
    """Append a blocked-request record to the local JSONL safety log."""
    try:
        SAFETY_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        # Never log the full text of self-harm queries — redact to protect privacy.
        logged_text = "[redacted — self-harm query]" if is_self_harm else text[:200]
        entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "category":  category,
            "action":    action,
            "text":      logged_text,
        }
        with SAFETY_LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception as e:
        logger.warning(f"Safety log write failed: {e}")
