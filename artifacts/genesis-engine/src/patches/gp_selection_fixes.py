"""
patches/gp_selection_fixes.py

Drop-in replacements for genetic_strategy_engine.py selection operators.

Fixes:
1. Lexicographic tournament selection (Sharpe-first, not fitness-first)
2. Diversity preservation via catastrophic re-seeding
3. Niche penalty for overrepresented clones
4. Elitism by Sharpe, not raw fitness

Applied to the existing GeneticStrategyEngine to prevent the "26-copy clone"
problem seen in generations 13–18 of the audit log.
"""

import random
import logging
from typing import List, Dict, Callable, Optional, Tuple
from collections import Counter
from dataclasses import dataclass
import numpy as np

logger = logging.getLogger("gp_selection")


@dataclass
class Genome:
    """Minimal genome interface expected by these selectors."""
    id: str
    generation: int
    fitness: float
    sharpe: float
    n_ops: int
    source: str
    lineage_id: str
    metadata: Dict = None

    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}


class LexicographicSelector:
    """
    Tournament selection with lexicographic ranking.

    Ranking criteria (in order):
    1. Sharpe ratio (must be > 0 to be considered viable)
    2. Fitness (capped, risk-adjusted)
    3. Complexity penalty (prefer simpler strategies)
    4. Diversity boost (prefer underrepresented lineages)

    Prevents the "fitness explosion" clone from dominating because a strategy
    with fitness=11M but Sharpe=-5.88 will never win a tournament.
    """

    MIN_VIABLE_SHARPE: float = 0.0

    def __init__(self, tournament_size: int = 3):
        self.tournament_size = tournament_size

    def select(self, population: List[Genome]) -> Genome:
        """Select one parent via k-way lexicographic tournament."""
        k = min(self.tournament_size, len(population))
        contestants = random.sample(population, k)

        valid = [
            c for c in contestants
            if c.metadata.get("valid", True) and c.sharpe >= self.MIN_VIABLE_SHARPE
        ]

        if not valid:
            contestants.sort(key=lambda g: g.sharpe, reverse=True)
            return contestants[0]

        valid.sort(key=lambda g: (g.sharpe, g.fitness, -g.n_ops), reverse=True)

        if len(valid) >= 2:
            sharpe_gap = abs(valid[0].sharpe - valid[1].sharpe)
            if sharpe_gap < 0.2:
                lineage_counts = Counter(g.lineage_id for g in population)
                if lineage_counts[valid[1].lineage_id] < lineage_counts[valid[0].lineage_id]:
                    return valid[1]

        return valid[0]

    def select_pair(self, population: List[Genome]) -> Tuple[Genome, Genome]:
        p1 = self.select(population)
        pool = [g for g in population if g.id != p1.id]
        if not pool:
            return p1, p1
        p2 = self.select(pool)
        return p1, p2


class DiversityPreserver:
    """
    Maintains population diversity across generations.

    Strategies:
    1. Catastrophic re-seeding: inject random genomes when diversity drops
    2. Niche penalty: reduce fitness of overrepresented expression patterns
    3. Clone detection: track and penalize exact duplicates
    """

    DIVERSITY_THRESHOLD: float = 0.85
    RESEED_FRACTION: float = 0.15
    NICHE_PENALTY_MAX: float = 0.50

    def __init__(self, random_genome_factory: Callable):
        """
        Args:
            random_genome_factory: Returns a new random Genome.
        """
        self.random_genome_factory = random_genome_factory

    def apply_niche_penalty(self, population: List[Genome]) -> List[Genome]:
        """Reduce fitness of overrepresented expression patterns."""
        source_counts = Counter(g.source for g in population)
        n = len(population)

        for g in population:
            crowding = source_counts[g.source] / n
            penalty = crowding * self.NICHE_PENALTY_MAX
            g.fitness *= (1.0 - penalty)
            g.metadata["niche_penalty"] = penalty

        return population

    def check_and_reseed(
        self,
        population: List[Genome],
        generation: int,
    ) -> Tuple[List[Genome], bool]:
        unique = len(set(g.source for g in population))
        diversity = unique / len(population) if population else 0

        should_reseed = (diversity < self.DIVERSITY_THRESHOLD) or (
            generation > 0 and generation % 5 == 0
        )

        if not should_reseed:
            return population, False

        n_seed = max(1, int(len(population) * self.RESEED_FRACTION))
        population.sort(key=lambda g: (g.sharpe, g.fitness), reverse=True)
        survivors = population[: len(population) - n_seed]
        seeds = [self.random_genome_factory() for _ in range(n_seed)]
        new_pop = survivors + seeds

        logger.info(
            f"[Diversity] Gen {generation}: Reseeded {n_seed} genomes "
            f"(diversity was {diversity:.1%})"
        )
        return new_pop, True

    def get_diversity_report(self, population: List[Genome]) -> Dict:
        if not population:
            return {"diversity": 0, "unique": 0, "total": 0, "top_clones": []}

        source_counts = Counter(g.source for g in population)
        unique = len(source_counts)
        total = len(population)

        return {
            "diversity": unique / total,
            "unique": unique,
            "total": total,
            "top_clones": [
                {"source": src[:60] + "...", "count": count, "pct": count / total}
                for src, count in source_counts.most_common(5)
            ],
            "lineages": len(set(g.lineage_id for g in population)),
        }


class SharpeFirstElitism:
    """
    Elitism that preserves top performers by Sharpe, not raw fitness.

    Ensures that numerically unstable strategies with astronomical fitness
    but poor Sharpe are never preserved across generations.
    """

    def __init__(self, elite_fraction: float = 0.05):
        self.elite_fraction = elite_fraction

    def select_elite(self, population: List[Genome]) -> List[Genome]:
        n_elite = max(1, int(len(population) * self.elite_fraction))
        sorted_pop = sorted(
            population,
            key=lambda g: (g.sharpe, g.fitness),
            reverse=True,
        )
        elite = sorted_pop[:n_elite]
        logger.debug(
            f"[Elite] Top {n_elite}: "
            f"sharpe_range=[{elite[-1].sharpe:.2f}, {elite[0].sharpe:.2f}], "
            f"fitness_range=[{elite[-1].fitness:.2f}, {elite[0].fitness:.2f}]"
        )
        return elite


# ---------------------------------------------------------------------------
# Integration Helper: Full Generation Step
# ---------------------------------------------------------------------------

def evolve_generation(
    population: List[Genome],
    generation: int,
    selector: LexicographicSelector,
    diversity_preserver: DiversityPreserver,
    elitism: SharpeFirstElitism,
    crossover_fn: Callable,
    mutate_fn: Callable,
    evaluate_fn: Callable,
) -> List[Genome]:
    """
    Execute one full generation step with all safety mechanisms.
    Drop-in replacement for the existing generational loop.
    """
    population = diversity_preserver.apply_niche_penalty(population)
    population, did_reseed = diversity_preserver.check_and_reseed(population, generation)

    for g in population:
        if "evaluated" not in g.metadata:
            result = evaluate_fn(g)
            g.fitness = result["fitness"]
            g.sharpe = result["sharpe"]
            g.metadata["valid"] = result["valid"]
            g.metadata["evaluated"] = True

    elite = elitism.select_elite(population)
    offspring = []
    target_size = len(population)

    while len(offspring) < target_size - len(elite):
        p1, p2 = selector.select_pair(population)
        child = crossover_fn(p1, p2)
        child.generation = generation + 1
        child.lineage_id = p1.lineage_id
        child = mutate_fn(child)
        offspring.append(child)

    new_population = elite + offspring

    report = diversity_preserver.get_diversity_report(new_population)
    logger.info(
        f"[Gen {generation}] Diversity={report['diversity']:.1%} | "
        f"Unique={report['unique']}/{report['total']} | "
        f"Lineages={report['lineages']} | "
        f"Reseeded={did_reseed}"
    )

    return new_population
