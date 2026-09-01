"""Two-phase discrete-event loop matching Conrad & Pattee (1970).

Phase 1 – interaction: each living organism reads local abiotic state and
          neighbours, then executes the next genetically gated routine.
Phase 2 – accounting: chips move, reproduction is resolved, the dead decay
          into the matter pool, a fraction of the pool rains back onto places.

No fitness function is supplied. Selection is the bookkeeping of chips.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Dict, List, Optional

import numpy as np

from .organism import Organism, mutate, random_genome, recombine
from .world import World


@dataclass
class SimulationConfig:
    n_places: int = 48
    total_chips: int = 4000
    n_organisms: int = 80
    max_organisms: int = 320
    steps: int = 400
    seed: int = 1970
    recombination_rate: float = 0.25
    pool_rain_fraction: float = 0.15
    cooperate_gift: int = 3
    collect_amount: int = 4
    verbose_every: int = 50
    abiotic_flip_prob: float = 0.0
    match_bonus: bool = True


@dataclass
class StepStats:
    step: int
    n_alive: int
    mean_age: float
    mean_genome_len: float
    mean_stored: float
    chips_places: int
    chips_bodies: int
    chips_pool: int
    births: int
    deaths: int
    cooperations: int
    action_hist: Dict[str, int]
    n_lineages: int
    match_ratio: float
    match_weighted: float
    collect_attempts: int
    collect_hits: int
    shannon_diversity: float
    unused_frac: float
    abiotic_flips: int


class Simulation:
    def __init__(self, config: Optional[SimulationConfig] = None):
        self.cfg = config or SimulationConfig()
        self.rng = np.random.default_rng(self.cfg.seed)
        self.world = World(
            n_places=self.cfg.n_places,
            total_chips=self.cfg.total_chips,
            seed=self.cfg.seed,
        )
        self.organisms: List[Organism] = []
        self._next_id = 0
        self.history: List[StepStats] = []
        self._seed_population()
        if self.conserved_chips() != self.cfg.total_chips:
            raise RuntimeError(
                f"seed conservation broken: {self.conserved_chips()} != {self.cfg.total_chips}"
            )

    def _new_id(self) -> int:
        self._next_id += 1
        return self._next_id

    def _seed_population(self) -> None:
        starting_store = 6
        for _ in range(self.cfg.n_organisms):
            pos = int(self.rng.integers(0, self.world.n_places))
            taken = self.world.take_chips(pos, starting_store)
            if taken < starting_store:
                need = starting_store - taken
                give = min(need, self.world.matter_pool)
                self.world.matter_pool -= give
                taken += give
            org = Organism(
                genome=random_genome(self.rng, length=int(self.rng.integers(8, 16))),
                position=pos,
                stored_chips=taken,
                territory=int(self.rng.integers(0, 3)),
                organism_id=self._new_id(),
            )
            self.organisms.append(org)

    def conserved_chips(self) -> int:
        bodies = sum(o.stored_chips for o in self.organisms if o.alive)
        return self.world.chip_count_on_places() + self.world.matter_pool + bodies

    def _input_state(self, org: Organism, occupants: Dict[int, List[Organism]]) -> int:
        view = self.world.local_view(org.position, org.territory)
        abiotic = sum(view["states"]) % 4
        n_neighbors = sum(
            max(0, len(occupants.get(i, [])) - (1 if i == org.position else 0))
            for i in view["indices"]
        )
        crowded = 1 if n_neighbors > 0 else 0
        rich = 1 if view["total_chips"] > 4 else 0
        return (abiotic + 2 * crowded + 4 * rich) % 8

    def step(self) -> StepStats:
        cfg = self.cfg
        living = [o for o in self.organisms if o.alive]
        occupants: Dict[int, List[Organism]] = {}
        for o in living:
            occupants.setdefault(o.position, []).append(o)

        births = 0
        deaths = 0
        cooperations = 0
        match_hits = 0
        match_obs = 0
        collect_attempts = 0
        collect_hits = 0
        action_hist = {
            "collect": 0,
            "forage": 0,
            "cooperate": 0,
            "repair": 0,
            "reproduce": 0,
            "wait": 0,
        }
        newborns: List[Organism] = []

        def harvest(org: Organism, place_idx: int) -> int:
            nonlocal collect_attempts, collect_hits
            collect_attempts += 1
            base = cfg.collect_amount
            matched = self.world.places[place_idx].state == org.preferred_state
            if cfg.match_bonus and matched:
                base += 2
            got = self.world.take_chips(place_idx, base)
            if got > 0:
                collect_hits += 1
            return got

        order = self.rng.permutation(len(living))
        for idx in order:
            org = living[int(idx)]
            if not org.alive:
                continue

            cost = org.metabolic_cost()
            if org.stored_chips < cost:
                self.world.decay_to_pool(org.stored_chips)
                org.stored_chips = 0
                org.alive = False
                deaths += 1
                continue
            org.stored_chips -= cost
            self.world.decay_to_pool(cost)

            inp = self._input_state(org, occupants)
            action = org.next_action(inp)
            name = ("collect", "forage", "cooperate", "repair", "reproduce", "wait")[action]
            action_hist[name] += 1

            here_state = self.world.places[org.position].state
            match_obs += 1
            if org.preferred_state == here_state:
                match_hits += 1

            if action == 0:
                got = harvest(org, org.position)
                org.stored_chips += got
                org.chips_collected += got
            elif action == 1:
                spots = self.world.neighbor_indices(org.position, org.territory)
                richest = max(
                    spots,
                    key=lambda i: self.world.places[i].chips
                    + (4 if self.world.places[i].state == org.preferred_state else 0),
                )
                got = harvest(org, richest)
                org.stored_chips += got
                org.chips_collected += got
                org.position = richest
            elif action == 2:
                neighbors = [
                    n
                    for i in self.world.neighbor_indices(org.position, org.territory)
                    for n in occupants.get(i, [])
                    if n.alive and n.organism_id != org.organism_id
                ]
                if neighbors and org.stored_chips > cfg.cooperate_gift + 2:
                    partner = neighbors[int(self.rng.integers(0, len(neighbors)))]
                    gift = min(cfg.cooperate_gift, org.stored_chips - 2)
                    org.stored_chips -= gift
                    partner.stored_chips += gift
                    org.chips_donated += gift
                    cooperations += 1
            elif action == 3:
                if org.stored_chips >= 2:
                    org.stored_chips -= 2
                    self.world.decay_to_pool(2)
                    org.age = max(0, org.age - 4)
            elif action == 4:
                if (
                    org.stored_chips >= org.reproduction_threshold()
                    and len(living) + len(newborns) < cfg.max_organisms
                ):
                    partner = None
                    if self.rng.random() < cfg.recombination_rate:
                        local = [
                            n
                            for i in self.world.neighbor_indices(org.position, max(1, org.territory))
                            for n in occupants.get(i, [])
                            if n.alive and n.organism_id != org.organism_id
                        ]
                        if local:
                            partner = local[int(self.rng.integers(0, len(local)))]
                    if partner is not None:
                        child_genome = recombine(org.genome, partner.genome, self.rng)
                    else:
                        child_genome = list(org.genome)
                    child_genome = mutate(child_genome, self.rng, org.amenability)
                    dowry = org.stored_chips // 2
                    org.stored_chips -= dowry
                    shift = (org.genome[0] % (org.territory + 2)) - 1
                    child_pos = (org.position + int(shift)) % self.world.n_places
                    child = Organism(
                        genome=child_genome,
                        position=child_pos,
                        stored_chips=dowry,
                        territory=max(0, min(4, org.territory + int(self.rng.integers(-1, 2)))),
                        parent_id=org.organism_id,
                        organism_id=self._new_id(),
                    )
                    newborns.append(child)
                    org.reproductions += 1
                    births += 1

            org.age += 1
            if self.rng.random() < org.wear():
                self.world.decay_to_pool(org.stored_chips)
                org.stored_chips = 0
                org.alive = False
                deaths += 1

        self.organisms.extend(newborns)
        if len(self.organisms) > cfg.max_organisms * 2:
            self.organisms = [o for o in self.organisms if o.alive]

        self.world.rain_from_pool(self.rng, cfg.pool_rain_fraction)
        abiotic_flips = self.world.perturb_abiotic(self.rng, cfg.abiotic_flip_prob)

        alive = [o for o in self.organisms if o.alive]
        sigs = {o.genotype_signature() for o in alive}
        if alive:
            counts = np.array(list(Counter(o.genotype_signature() for o in alive).values()), dtype=float)
            probs = counts / counts.sum()
            shannon = float(-(probs * np.log2(np.clip(probs, 1e-12, 1.0))).sum())
            unused = float(np.mean([o.unused_program_fraction() for o in alive]))
            stored = float(sum(o.stored_chips for o in alive))
            if stored > 0:
                matched_store = sum(
                    o.stored_chips
                    for o in alive
                    if self.world.places[o.position].state == o.preferred_state
                )
                match_weighted = matched_store / stored
            else:
                match_weighted = 0.0
        else:
            shannon = 0.0
            unused = 0.0
            match_weighted = 0.0
        stats = StepStats(
            step=len(self.history),
            n_alive=len(alive),
            mean_age=float(np.mean([o.age for o in alive])) if alive else 0.0,
            mean_genome_len=float(np.mean([len(o.genome) for o in alive])) if alive else 0.0,
            mean_stored=float(np.mean([o.stored_chips for o in alive])) if alive else 0.0,
            chips_places=self.world.chip_count_on_places(),
            chips_bodies=sum(o.stored_chips for o in alive),
            chips_pool=self.world.matter_pool,
            births=births,
            deaths=deaths,
            cooperations=cooperations,
            action_hist=action_hist,
            n_lineages=len(sigs),
            match_ratio=(match_hits / match_obs) if match_obs else 0.0,
            match_weighted=match_weighted,
            collect_attempts=collect_attempts,
            collect_hits=collect_hits,
            shannon_diversity=shannon,
            unused_frac=unused,
            abiotic_flips=abiotic_flips,
        )
        self.history.append(stats)
        return stats

    def run(self) -> List[StepStats]:
        for t in range(self.cfg.steps):
            stats = self.step()
            if self.cfg.verbose_every and t % self.cfg.verbose_every == 0:
                print(
                    f"t={stats.step:4d}  N={stats.n_alive:4d}  "
                    f"lineages={stats.n_lineages:3d}  "
                    f"H={stats.shannon_diversity:.2f}  "
                    f"match={stats.match_ratio:.2f}  "
                    f"chips[place/body/pool]="
                    f"{stats.chips_places}/{stats.chips_bodies}/{stats.chips_pool}  "
                    f"conserved={stats.chips_places + stats.chips_bodies + stats.chips_pool}  "
                    f"flips={stats.abiotic_flips}"
                )
        return self.history
