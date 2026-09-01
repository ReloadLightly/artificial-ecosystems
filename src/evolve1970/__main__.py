"""CLI: python -m evolve1970"""

from .simulation import Simulation, SimulationConfig


def main() -> None:
    sim = Simulation(
        SimulationConfig(
            steps=300,
            n_organisms=80,
            n_places=48,
            total_chips=4000,
            seed=1970,
            verbose_every=25,
        )
    )
    print(f"Initial conserved chips: {sim.conserved_chips()}")
    sim.run()
    print(f"Final conserved chips:   {sim.conserved_chips()}")
    if sim.history:
        last = sim.history[-1]
        print(
            f"Ended with {last.n_alive} organisms, "
            f"{last.n_lineages} distinct short genotypes, "
            f"mean genome length {last.mean_genome_len:.1f}."
        )


if __name__ == "__main__":
    main()
