from .simulation import MetabolicSim, MetabolicConfig


def main() -> None:
    sim = MetabolicSim(
        MetabolicConfig(steps=250, n_organisms=80, seed=1998, verbose_every=25)
    )
    print(f"EVOLVE IV | initial conserved: {sim.conserved()}")
    sim.run()
    print(f"EVOLVE IV | final conserved:   {sim.conserved()}")
    last = sim.history[-1]
    print(
        f"{last.n_alive} alive, producers={last.n_producers}, "
        f"recyclers={last.n_recyclers}, "
        f"cross-type contact={last.niche_index:.2f}"
    )


if __name__ == "__main__":
    main()
