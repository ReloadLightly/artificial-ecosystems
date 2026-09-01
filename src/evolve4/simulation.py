"""EVOLVE IV reconstruction: metabolites + niche construction.

Brewster & Conrad (1998, LNCS 1447; 1999, CEC) built EVOLVE IV to
watch niche proliferation. Two published interactions:

    1. organisms exchange metabolites
    2. organisms modify the local environment to the benefit or
       detriment of whoever is standing next door

They reported that niche formation occurs. Source is lost; this is
the smallest closed world in which both sentences can be true.

Physics
-------
* every place holds two metabolite piles (nutrient N, waste W) and
  a signed *condition* (soil / pH / moisture — not matter)
* N + W + stored energy is conserved
* producer  : eats N, excretes W
* recycler  : eats W, excretes N
* conversion direction, taste, and construct are heritable
* harvest yield is boosted when local condition matches taste,
  cut when it opposes taste
* after acting, an organism adds its construct value to the place
  (clamped). Condition slowly relaxes toward 0.
* death returns stored energy as a mix to the local place
* no fitness function

A *metabolic niche* is spatial sorting: producers living next to
recyclers so each one's waste is the other's food.

A *constructed niche* is a patch whose condition has been pushed
away from 0 in a direction that some resident prefers.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List

import numpy as np


CONDITION_MIN = -3
CONDITION_MAX = 3


@dataclass
class Place:
    nutrient: int = 0
    waste: int = 0
    condition: int = 0  # not conserved; a state of the ground


@dataclass
class Bug:
    position: int
    stored: int
    producer: bool  # True: eats N, makes W. False: eats W, makes N.
    taste: int  # -1 or +1 — preferred sign of local condition
    construct: int  # -1, 0, +1 — how this bug pushes the ground
    genome_tag: int
    age: int = 0
    alive: bool = True
    parent: int | None = None
    bug_id: int = 0


@dataclass
class MetabolicConfig:
    n_places: int = 48
    total_units: int = 4000
    n_organisms: int = 80
    max_organisms: int = 280
    steps: int = 250
    seed: int = 1998
    harvest: int = 4
    convert_yield: int = 3  # stored energy per successful harvest
    excrete: int = 2  # metabolite returned of the other type
    repro_threshold: int = 14
    mut_prob: float = 0.08
    construction: bool = True
    condition_decay: float = 0.18  # chance a nonzero cell relaxes by 1
    verbose_every: int = 50


@dataclass
class StepRow:
    step: int
    n_alive: int
    n_producers: int
    n_recyclers: int
    nutrient: int
    waste: int
    stored: int
    niche_index: float
    construct_match: float
    condition_var: float
    condition_mean: float
    births: int
    deaths: int


class MetabolicSim:
    def __init__(self, config: MetabolicConfig | None = None):
        self.cfg = config or MetabolicConfig()
        self.rng = np.random.default_rng(self.cfg.seed)
        n = self.cfg.n_places
        half = self.cfg.total_units // 2
        base_n, extra_n = divmod(half, n)
        base_w, extra_w = divmod(self.cfg.total_units - half, n)
        self.places = [
            Place(
                nutrient=base_n + (1 if i < extra_n else 0),
                waste=base_w + (1 if i < extra_w else 0),
                condition=0,
            )
            for i in range(n)
        ]
        self.bugs: List[Bug] = []
        self._next = 0
        self.history: List[StepRow] = []
        self._seed()
        if self.conserved() != self.cfg.total_units:
            raise RuntimeError(f"seed conservation broken: {self.conserved()}")

    def _id(self) -> int:
        self._next += 1
        return self._next

    def _seed(self) -> None:
        start = 6
        for i in range(self.cfg.n_organisms):
            pos = int(self.rng.integers(0, self.cfg.n_places))
            producer = bool(i % 2 == 0)
            taste = 1 if self.rng.random() < 0.5 else -1
            construct = int(self.rng.integers(-1, 2))  # -1, 0, 1
            taken = self._take(pos, producer, start)
            self.bugs.append(
                Bug(
                    position=pos,
                    stored=max(1, taken),
                    producer=producer,
                    taste=taste,
                    construct=construct,
                    genome_tag=int(self.rng.integers(0, 16)),
                    bug_id=self._id(),
                )
            )

    def _take(self, pos: int, producer: bool, amount: int) -> int:
        pile = self.places[pos]
        if producer:
            got = min(amount, pile.nutrient)
            pile.nutrient -= got
        else:
            got = min(amount, pile.waste)
            pile.waste -= got
        return got

    def _excrete(self, pos: int, producer: bool, amount: int) -> None:
        if amount <= 0:
            return
        if producer:
            self.places[pos].waste += amount
        else:
            self.places[pos].nutrient += amount

    def conserved(self) -> int:
        on_floor = sum(p.nutrient + p.waste for p in self.places)
        in_bodies = sum(b.stored for b in self.bugs if b.alive)
        return on_floor + in_bodies

    def _yield_bonus(self, b: Bug) -> int:
        """Condition matching taste adds one harvested unit of yield."""
        if not self.cfg.construction:
            return 0
        c = self.places[b.position].condition
        if c == 0:
            return 0
        if (c > 0 and b.taste > 0) or (c < 0 and b.taste < 0):
            return 1
        return -1

    def _construct(self, b: Bug) -> None:
        if not self.cfg.construction or b.construct == 0:
            return
        p = self.places[b.position]
        p.condition = int(
            max(CONDITION_MIN, min(CONDITION_MAX, p.condition + b.construct))
        )

    def _relax_condition(self) -> None:
        if not self.cfg.construction:
            return
        for p in self.places:
            if p.condition == 0:
                continue
            if self.rng.random() < self.cfg.condition_decay:
                p.condition -= 1 if p.condition > 0 else -1

    def _niche(self, living: List[Bug]) -> float:
        if len(living) < 2:
            return 0.0
        by_pos: dict[int, List[Bug]] = {}
        for b in living:
            by_pos.setdefault(b.position, []).append(b)
        hits = 0
        obs = 0
        n = self.cfg.n_places
        for b in living:
            partners = []
            for d in (-1, 0, 1):
                partners.extend(
                    p
                    for p in by_pos.get((b.position + d) % n, [])
                    if p.bug_id != b.bug_id
                )
            if not partners:
                continue
            obs += 1
            if any(p.producer != b.producer for p in partners):
                hits += 1
        return hits / obs if obs else 0.0

    def _construct_match(self, living: List[Bug]) -> float:
        if not living:
            return 0.0
        scored = [b for b in living if b.construct != 0]
        if not scored:
            return 0.0
        return sum(1 for b in scored if b.construct == b.taste) / len(scored)

    def snapshot_ring(self) -> str:
        """One-line picture of the ring: P/R plus condition sign."""
        n = self.cfg.n_places
        cells = ["."] * n
        for b in self.bugs:
            if not b.alive:
                continue
            mark = "P" if b.producer else "R"
            cells[b.position] = mark
        cond = []
        for p in self.places:
            if p.condition > 0:
                cond.append("+")
            elif p.condition < 0:
                cond.append("-")
            else:
                cond.append(" ")
        return "".join(cells) + "\n" + "".join(cond)

    def step(self) -> StepRow:
        cfg = self.cfg
        living = [b for b in self.bugs if b.alive]
        births = 0
        deaths = 0
        newborns: List[Bug] = []
        order = self.rng.permutation(len(living))
        for idx in order:
            b = living[int(idx)]
            if not b.alive:
                continue
            if b.stored < 1:
                b.alive = False
                deaths += 1
                continue
            b.stored -= 1
            self._excrete(b.position, b.producer, 1)

            want = cfg.harvest + self._yield_bonus(b)
            want = max(1, want)
            got = self._take(b.position, b.producer, want)
            if got == 0:
                left = (b.position - 1) % cfg.n_places
                right = (b.position + 1) % cfg.n_places

                def stock(i: int) -> int:
                    p = self.places[i]
                    base = p.nutrient if b.producer else p.waste
                    if cfg.construction and p.condition != 0:
                        match = (p.condition > 0 and b.taste > 0) or (
                            p.condition < 0 and b.taste < 0
                        )
                        base += 2 if match else -1
                    return base

                target = max((left, b.position, right), key=stock)
                b.position = target
                got = self._take(b.position, b.producer, max(1, cfg.harvest))
            if got > 0:
                stored = min(cfg.convert_yield, got)
                excreted = min(cfg.excrete, got)
                leftover = got - stored - excreted
                if leftover < 0:
                    excreted += leftover
                    leftover = 0
                b.stored += stored
                if leftover > 0:
                    if b.producer:
                        self.places[b.position].nutrient += leftover
                    else:
                        self.places[b.position].waste += leftover
                if excreted > 0:
                    self._excrete(b.position, b.producer, excreted)

            self._construct(b)

            if (
                b.stored >= cfg.repro_threshold
                and len(living) + len(newborns) < cfg.max_organisms
            ):
                child_prod = b.producer
                child_taste = b.taste
                child_construct = b.construct
                tag = b.genome_tag
                if self.rng.random() < cfg.mut_prob:
                    flip = int(self.rng.integers(0, 3))
                    if flip == 0:
                        child_prod = not child_prod
                    elif flip == 1:
                        child_taste = -child_taste
                    else:
                        child_construct = int(self.rng.integers(-1, 2))
                    tag = (tag + int(self.rng.integers(1, 4))) % 16
                dowry = b.stored // 2
                b.stored -= dowry
                shift = 1 if self.rng.random() < 0.5 else -1
                newborns.append(
                    Bug(
                        position=(b.position + shift) % cfg.n_places,
                        stored=dowry,
                        producer=child_prod,
                        taste=child_taste,
                        construct=child_construct,
                        genome_tag=tag,
                        parent=b.bug_id,
                        bug_id=self._id(),
                    )
                )
                births += 1

            b.age += 1
            if self.rng.random() < min(0.08, 0.002 + 0.0012 * b.age):
                half = b.stored // 2
                self.places[b.position].nutrient += b.stored - half
                self.places[b.position].waste += half
                b.stored = 0
                b.alive = False
                deaths += 1

        self.bugs.extend(newborns)
        if len(self.bugs) > cfg.max_organisms * 2:
            self.bugs = [b for b in self.bugs if b.alive]

        self._relax_condition()

        alive = [b for b in self.bugs if b.alive]
        conds = [p.condition for p in self.places]
        row = StepRow(
            step=len(self.history),
            n_alive=len(alive),
            n_producers=sum(1 for b in alive if b.producer),
            n_recyclers=sum(1 for b in alive if not b.producer),
            nutrient=sum(p.nutrient for p in self.places),
            waste=sum(p.waste for p in self.places),
            stored=sum(b.stored for b in alive),
            niche_index=self._niche(alive),
            construct_match=self._construct_match(alive),
            condition_var=float(np.var(conds)),
            condition_mean=float(np.mean(conds)),
            births=births,
            deaths=deaths,
        )
        self.history.append(row)
        return row

    def run(self) -> List[StepRow]:
        for t in range(self.cfg.steps):
            row = self.step()
            if self.cfg.verbose_every and t % self.cfg.verbose_every == 0:
                print(
                    f"t={row.step:4d}  N={row.n_alive:4d}  "
                    f"P/R={row.n_producers}/{row.n_recyclers}  "
                    f"N/W/body={row.nutrient}/{row.waste}/{row.stored}  "
                    f"conserved={row.nutrient + row.waste + row.stored}  "
                    f"niche={row.niche_index:.2f}  "
                    f"c-match={row.construct_match:.2f}  "
                    f"c-var={row.condition_var:.2f}"
                )
        return self.history
