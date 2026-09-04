"""EVOLVE IV-inspired metabolite and construction physics.

This compact model is informed by Brewster and Conrad's 1998–1999 EVOLVE IV
work but is not a recovered or source-faithful implementation. Every place
holds nutrient, waste, and a non-material signed condition. Nutrient, waste,
and matter stored in living bodies are conserved; the condition can be changed
locally and relaxes toward zero. A raw cross-type contact statistic is exposed
for diagnostics, but it is density-sensitive and is not evidence of niche
formation without appropriate null models and interventions.

The optional typed controller changes local intent and heritable traits through
an explicit boundary. It never owns matter accounting, scheduling, mortality,
or conservation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List

import numpy as np

from .control import IVController, IVIntent, IVPercept, IVTraits, MovementMode
from .randomness import EcologyRandomStreams


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
    capacity_blocked_births: int
    capacity_gate_occupancy_peak: int


class MetabolicSim:
    def __init__(
        self,
        config: MetabolicConfig | None = None,
        *,
        controller: IVController | None = None,
        random_streams: EcologyRandomStreams | None = None,
    ):
        self.cfg = config or MetabolicConfig()
        self.controller = controller
        if random_streams is None:
            # This single-generator path is a regression contract. All named
            # handles alias it so routing calls below cannot change the legacy
            # controller-free draw order.
            self.rng = np.random.default_rng(self.cfg.seed)
            self.random_streams = EcologyRandomStreams.legacy(self.rng)
        else:
            if not isinstance(random_streams, EcologyRandomStreams):
                raise TypeError("random_streams must be EcologyRandomStreams or None")
            self.random_streams = random_streams
            # Compatibility handle: in split mode ``rng`` denotes only the
            # initialization stream. Replay evidence should use state_dict().
            self.rng = random_streams.initialization
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
        rng = self.random_streams.initialization
        for i in range(self.cfg.n_organisms):
            pos = int(rng.integers(0, self.cfg.n_places))
            producer = bool(i % 2 == 0)
            taste = 1 if rng.random() < 0.5 else -1
            construct = int(rng.integers(-1, 2))  # -1, 0, 1
            if self.controller is None:
                # Keep the controller-free initialization path literal: its
                # fixed-seed trajectory is a regression contract.
                taken = self._take(pos, producer, start)
                self.bugs.append(
                    Bug(
                        position=pos,
                        stored=max(1, taken),
                        producer=producer,
                        taste=taste,
                        construct=construct,
                        genome_tag=int(rng.integers(0, 16)),
                        bug_id=self._id(),
                    )
                )
                continue

            genome_tag = int(rng.integers(0, 16))
            bug_id = self._id()
            traits = self.controller.initial_traits(
                bug_id,
                i,
                IVTraits(
                    producer=producer,
                    taste=taste,
                    construct=construct,
                ),
            )
            if not isinstance(traits, IVTraits):
                raise TypeError("controller.initial_traits must return IVTraits")
            taken = self._take(pos, traits.producer, start)
            self.bugs.append(
                Bug(
                    position=pos,
                    # Unlike the legacy seed path, controller mode must not
                    # mint a unit when its chosen metabolite pile is empty.
                    stored=taken,
                    producer=traits.producer,
                    taste=traits.taste,
                    construct=traits.construct,
                    genome_tag=genome_tag,
                    bug_id=bug_id,
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
            if (
                self.random_streams.condition_decay.random()
                < self.cfg.condition_decay
            ):
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

    def _stock_for(self, b: Bug, position: int) -> int:
        place = self.places[position]
        return place.nutrient if b.producer else place.waste

    def _controller_percept(self, b: Bug, living: List[Bug]) -> IVPercept:
        left = (b.position - 1) % self.cfg.n_places
        right = (b.position + 1) % self.cfg.n_places
        local_others = [
            other
            for other in living
            if other.alive
            and other.bug_id != b.bug_id
            and other.position in (left, b.position, right)
        ]
        return IVPercept(
            bug_id=b.bug_id,
            step=len(self.history),
            position=b.position,
            left=left,
            right=right,
            stock_here=self._stock_for(b, b.position),
            stock_left=self._stock_for(b, left),
            stock_right=self._stock_for(b, right),
            condition_here=self.places[b.position].condition,
            stored=b.stored,
            repro_threshold=self.cfg.repro_threshold,
            crowded=any(other.position == b.position for other in local_others),
            opposite_left=any(
                other.position == left and other.producer != b.producer
                for other in local_others
            ),
            opposite_right=any(
                other.position == right and other.producer != b.producer
                for other in local_others
            ),
            n_opposite=sum(
                other.producer != b.producer for other in local_others
            ),
        )

    def _controller_intent(self, b: Bug, living: List[Bug]) -> IVIntent:
        if self.controller is None:
            return IVIntent()
        percept = self._controller_percept(b, living)
        intent = self.controller.decide(percept)
        if not isinstance(intent, IVIntent):
            raise TypeError("controller.decide must return IVIntent")
        if intent.movement is MovementMode.TARGET:
            reachable = {percept.left, percept.position, percept.right}
            if intent.target_position not in reachable:
                raise ValueError(
                    "controller target must be the current, left, or right place"
                )
        return intent

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
        capacity_blocked_births = 0
        capacity_gate_occupancy_peak = len(living)
        newborns: List[Bug] = []
        order = self.random_streams.scheduling.permutation(len(living))
        for idx in order:
            b = living[int(idx)]
            if not b.alive:
                continue
            intent = (
                self._controller_intent(b, living)
                if self.controller is not None
                else None
            )
            if b.stored < 1:
                b.alive = False
                deaths += 1
                continue
            b.stored -= 1
            self._excrete(b.position, b.producer, 1)

            if intent is not None and intent.movement is MovementMode.TARGET:
                # Reachability was checked before maintenance changed matter.
                b.position = int(intent.target_position)

            want = cfg.harvest + self._yield_bonus(b)
            want = max(1, want)
            got = self._take(b.position, b.producer, want)
            default_movement = (
                intent is None or intent.movement is MovementMode.DEFAULT
            )
            if got == 0 and default_movement:
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

            if intent is None or intent.construct:
                self._construct(b)

            repro_threshold = (
                cfg.repro_threshold
                if intent is None or intent.repro_threshold is None
                else intent.repro_threshold
            )
            reproduction_ready = (
                (intent is None or intent.reproduce)
                and b.stored >= repro_threshold
            )
            capacity_gate_occupancy = len(living) + len(newborns)
            capacity_gate_occupancy_peak = max(
                capacity_gate_occupancy_peak,
                capacity_gate_occupancy,
            )
            if (
                reproduction_ready
                and len(living) + len(newborns) >= cfg.max_organisms
            ):
                capacity_blocked_births += 1
            if (
                reproduction_ready
                and len(living) + len(newborns) < cfg.max_organisms
            ):
                child_prod = b.producer
                child_taste = b.taste
                child_construct = b.construct
                tag = b.genome_tag
                legacy_mutation_roll = self.random_streams.reproduction.random()
                if self.controller is None and legacy_mutation_roll < cfg.mut_prob:
                    flip = int(self.random_streams.reproduction.integers(0, 3))
                    if flip == 0:
                        child_prod = not child_prod
                    elif flip == 1:
                        child_taste = -child_taste
                    else:
                        child_construct = int(
                            self.random_streams.reproduction.integers(-1, 2)
                        )
                    tag = (
                        tag + int(self.random_streams.reproduction.integers(1, 4))
                    ) % 16
                child_id = self._next + 1
                if self.controller is not None:
                    prepare_birth = getattr(self.controller, "prepare_birth", None)
                    if prepare_birth is not None:
                        if not callable(prepare_birth):
                            raise TypeError("controller.prepare_birth must be callable")
                        prepare_birth(
                            b.bug_id,
                            child_id,
                            tuple(other.bug_id for other in living if other.alive),
                        )
                    traits = self.controller.offspring_traits(
                        b.bug_id,
                        child_id,
                        IVTraits(
                            producer=child_prod,
                            taste=child_taste,
                            construct=child_construct,
                        ),
                    )
                    if not isinstance(traits, IVTraits):
                        raise TypeError(
                            "controller.offspring_traits must return IVTraits"
                        )
                    child_prod = traits.producer
                    child_taste = traits.taste
                    child_construct = traits.construct
                dowry = b.stored // 2
                b.stored -= dowry
                shift = (
                    1 if self.random_streams.reproduction.random() < 0.5 else -1
                )
                assigned_id = self._id()
                if assigned_id != child_id:
                    raise RuntimeError("controller child ID reservation drifted")
                newborns.append(
                    Bug(
                        position=(b.position + shift) % cfg.n_places,
                        stored=dowry,
                        producer=child_prod,
                        taste=child_taste,
                        construct=child_construct,
                        genome_tag=tag,
                        parent=b.bug_id,
                        bug_id=assigned_id,
                    )
                )
                births += 1
                capacity_gate_occupancy_peak = max(
                    capacity_gate_occupancy_peak,
                    len(living) + len(newborns),
                )

            b.age += 1
            if self.random_streams.mortality.random() < min(
                0.08, 0.002 + 0.0012 * b.age
            ):
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
            capacity_blocked_births=capacity_blocked_births,
            capacity_gate_occupancy_peak=capacity_gate_occupancy_peak,
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
                    f"cross-contact={row.niche_index:.2f}  "
                    f"c-match={row.construct_match:.2f}  "
                    f"c-var={row.condition_var:.2f}"
                )
        return self.history
