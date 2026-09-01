"""Language policies for the EVOLVE IV world.

The IV physics (metabolites, construction, conservation) stay in
evolve4. This file is only the variation operator:

* a short English policy is the heritable object
* compile_traits reads role / taste / construct out of the text at birth
* interpret_iv_policy maps policy + local percept onto an Intent
  (where to stand, whether to dig, how rich before fission)
* an LLM, when present, is asked only at birth to rewrite the
  child's policy. The interpreter never calls a model.

The model is a mutator, not a judge.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional


DEFAULT_IV_POLICIES = [
    "I am a producer. Eat nutrient, leave waste. Seek a recycler neighbour. "
    "Raise the ground; I prefer alkali. Reproduce at 14 stored.",
    "I am a recycler. Eat waste, leave nutrient. Stay next to a producer. "
    "Lower the ground; I prefer acid. Reproduce only when rich.",
    "Producer. Harvest nutrient where I stand. Never construct. "
    "Move only if this place is empty. Reproduce early.",
    "Recycler. Forage toward waste. Dig the ground down. "
    "Partner with the opposite type. Reproduce slowly.",
    "Producer who builds what I like. Raise alkali patches and stay on them. "
    "Seek waste-makers next door. Reproduce at 16.",
    "Recycler. Leave the ground alone. Follow nutrient-makers. "
    "If starving, move. Reproduce as soon as possible.",
    "I eat nutrient and make waste. Acidify the soil. Prefer low ground. "
    "Do not chase partners. Reproduce when uncrowded.",
    "I eat waste and make nutrient. Build the ground up. Prefer high ground. "
    "Stay if a producer is beside me, otherwise seek. Reproduce at 12.",
]


@dataclass
class Intent:
    """What the policy asks the body to do this step.

    Physics still does metabolism, conversion, death, and conservation.
    The policy may only choose a neighbouring cell, withhold construction,
    and shift the reproduction threshold.
    """

    position: Optional[int] = None
    construct: bool = True
    repro_threshold: Optional[int] = None


def _has(text: str, *needles: str) -> bool:
    return any(n in text for n in needles)


def compile_traits(policy: str, parent=None) -> tuple[bool, int, int]:
    """Read conversion, taste, and construct out of the policy text.

    Unmentioned traits inherit from the parent (or stay as already set).
    """
    text = (policy or "").lower()
    producer = getattr(parent, "producer", True)
    taste = getattr(parent, "taste", 1)
    construct = getattr(parent, "construct", 0)

    if _has(text, "recycler", "decompos", "eat waste", "eat w ", "make nutrient"):
        producer = False
    elif _has(text, "producer", "photosynth", "eat nutrient", "eat n ", "make waste"):
        producer = True

    if _has(text, "alkali", "high ground", "prefer high", "prefer plus", "prefer +", "dry"):
        taste = 1
    elif _has(text, "acid", "low ground", "prefer low", "prefer minus", "prefer -", "wet"):
        taste = -1

    if _has(text, "never construct", "leave the ground", "do not build", "don't build"):
        construct = 0
    elif _has(text, "raise", "alkaliz", "build up", "push +", "push up"):
        construct = 1
    elif _has(text, "lower", "acidif", "dig", "push -", "push down"):
        construct = -1

    return producer, taste, construct


def interpret_iv_policy(policy: str, percept: dict) -> Intent:
    """Deterministic compiler: policy text + percept → Intent."""
    text = (policy or "").lower()
    here = int(percept.get("position", 0))
    left = int(percept.get("left", here))
    right = int(percept.get("right", here))
    stock_here = int(percept.get("stock_here", 0))
    stock_left = int(percept.get("stock_left", 0))
    stock_right = int(percept.get("stock_right", 0))
    stored = int(percept.get("stored", 0))
    base_threshold = int(percept.get("repro_threshold", 14))
    crowded = bool(percept.get("crowded", False))
    opp_left = bool(percept.get("opposite_left", False))
    opp_right = bool(percept.get("opposite_right", False))
    n_opposite = int(percept.get("n_opposite", 0))

    intent = Intent(position=None, construct=True, repro_threshold=base_threshold)

    if _has(text, "never construct", "leave the ground", "do not build", "don't build"):
        intent.construct = False
    elif _has(text, "stop building") and int(percept.get("condition_here", 0)) != 0:
        intent.construct = False

    if _has(text, "reproduce early", "as soon as"):
        intent.repro_threshold = max(8, base_threshold - 4)
    elif _has(text, "reproduce slowly", "only when rich"):
        intent.repro_threshold = base_threshold + 6
    elif _has(text, "uncrowded") and crowded:
        intent.repro_threshold = base_threshold + 20
    elif "reproduce at" in text:
        for token in text.split("reproduce at", 1)[1].replace(".", " ").split():
            if token.isdigit():
                intent.repro_threshold = max(8, min(30, int(token)))
                break

    wants_partner = _has(text, "partner", "neighbour", "neighbor", "next to", "beside")
    wants_seek = _has(text, "seek", "move", "forage", "follow", "chase")
    stay_put = _has(text, "stay", "where i stand", "never move")

    if stay_put and stock_here > 0:
        return intent

    should_move = stock_here == 0 or (wants_partner and n_opposite == 0)
    if should_move and (wants_seek or wants_partner or stock_here == 0):
        scores = {
            here: stock_here,
            left: stock_left + (4 if wants_partner and opp_left else 0),
            right: stock_right + (4 if wants_partner and opp_right else 0),
        }
        intent.position = max(scores, key=scores.get)

    return intent


def heuristic_mutate_iv_policy(policy: str, ctx: dict) -> str:
    """Offline stand-in for an LLM rewrite of a child's policy."""
    extras = [
        " Seek a recycler neighbour.",
        " Seek a producer neighbour.",
        " Raise the ground.",
        " Lower the ground.",
        " Leave the ground alone.",
        " Reproduce early.",
        " Reproduce only when rich.",
        " If starving, move.",
        " Stay if the opposite type is beside me.",
        " Prefer alkali.",
        " Prefer acid.",
    ]
    roll = float(ctx.get("roll", 0.5))
    text = (policy or DEFAULT_IV_POLICIES[0]).strip()
    extra = extras[int(roll * 100) % len(extras)]
    if roll > 0.88:
        child = extra.strip()
    elif roll > 0.80 and "." in text:
        head, _sep, _tail = text.rpartition(".")
        child = ((head.strip() + "." if head.strip() else text) + extra).strip()
    elif roll < 0.40:
        child = (text + extra).strip()
    else:
        child = text
    if len(child) > 280:
        sentences = [s.strip() for s in child.split(".") if s.strip()]
        child = ". ".join(sentences[-3:]) + "."
    return child


LLMMutator = Callable[[str, dict], str]


def make_llm_mutator(complete: Callable[[str], str]) -> LLMMutator:
    """Wrap any `prompt → text` callable as an IV policy mutator.

    `complete` is your API. We only send the parent policy and a
    one-line local summary. The child policy must stay short and
    mention a role (producer/recycler) so compile_traits can read it.
    """

    def mutate(policy: str, ctx: dict) -> str:
        role = "producer" if ctx.get("producer") else "recycler"
        prompt = (
            "Rewrite this artificial-ecosystem policy for a child organism. "
            "Keep it under 40 words. Mention producer or recycler, "
            "whether to raise/lower/leave the ground, and when to reproduce. "
            f"Parent role: {role}. Parent policy:\n{policy}"
        )
        out = (complete(prompt) or "").strip().splitlines()[0].strip()
        return out[:280] if out else heuristic_mutate_iv_policy(policy, ctx)

    return mutate
