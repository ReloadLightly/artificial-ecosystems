"""Modern overlay: organisms whose *strategy text* can be written by an LLM.

The physics of chips, places, death, and conservation stay identical to the
1970 reconstruction. What changes is the controller:

* Classic: a decoded genome is a cyclic program of six primitive routines.
* Modern: each lineage carries a short natural-language policy. A deterministic
  interpreter maps that policy + local percept onto the same six routines.
  An LLM (optional) is used only at birth to rewrite the child's policy,
  so model calls stay sparse and the loop remains a closed material world.

This is the 2026 analog of Conrad's claim that we should not impose a fitness
function. The LLM is a *variation operator*, not a judge.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

# The six Conrad primitives. Policies must compile down to these.
PRIMITIVES = ("collect", "forage", "cooperate", "repair", "reproduce", "wait")


DEFAULT_POLICIES = [
    "If the current place has chips, collect. If rich neighbours exist, forage. "
    "If storing more than 20 chips, reproduce. Otherwise wait.",
    "Prefer forage over collect. Donate to a neighbour if I hold more than twice "
    "what they hold. Repair when age is high. Reproduce at 18 chips.",
    "Stay put and collect. Never donate. Reproduce as soon as possible. Ignore age.",
    "Cooperate first whenever a neighbour is present. Forage only if alone. "
    "Repair often. Reproduce slowly.",
    "If crowded, forage away. If poor, wait. If rich and uncrowded, collect then reproduce.",
]


def interpret_policy(policy: str, percept: dict) -> str:
    """Tiny deterministic compiler from policy text + percept → primitive.

    This is deliberately dumb and keyword-based so the simulation does not
    depend on an API. An LLM can still *write* richer policies; they are
    executed by this same interpreter.
    """
    text = policy.lower()
    chips_here = percept.get("chips_here", 0)
    local_chips = percept.get("local_chips", 0)
    stored = percept.get("stored", 0)
    age = percept.get("age", 0)
    n_neighbors = percept.get("n_neighbors", 0)
    threshold = percept.get("repro_threshold", 16)

    prefers_coop = "cooperat" in text or "donat" in text or "share" in text
    prefers_forage = "forage" in text or "explor" in text or "move" in text
    greedy = "never donate" in text or ("ignore" in text and "neighbour" in text)
    cautious = "repair" in text or "age" in text

    if prefers_coop and n_neighbors > 0 and stored > 6 and not greedy:
        return "cooperate"
    if cautious and age > 12 and stored > 4:
        return "repair"
    if stored >= threshold and "reproduc" in text:
        return "reproduce"
    if prefers_forage and local_chips > chips_here:
        return "forage"
    if chips_here > 0 and "collect" in text:
        return "collect"
    if stored >= threshold:
        return "reproduce"
    if chips_here > 0:
        return "collect"
    if local_chips > 0:
        return "forage"
    return "wait"


LLMMutator = Callable[[str, dict], str]


def heuristic_mutate_policy(policy: str, rng_roll: float) -> str:
    """Offline stand-in for an LLM rewrite of a child's policy."""
    extras = [
        " Repair when age exceeds ten.",
        " Donate only if storing more than 15 chips.",
        " Prefer the richest place in the territory.",
        " Reproduce only when uncrowded.",
        " Never wait if chips are visible.",
        " If starving, forage immediately.",
    ]
    if rng_roll < 0.35:
        return policy + extras[int(rng_roll * 100) % len(extras)]
    if rng_roll > 0.85:
        return extras[int(rng_roll * 100) % len(extras)].strip()
    return policy


@dataclass
class PolicyOrganismState:
    policy: str
    parent_policy: Optional[str] = None
