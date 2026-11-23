"""Algoritmo genético (sección 4 de la ERS).

- Cromosoma: permutación de genes (ID_Pieza, Estado_Rotación) + decodificador
  constructivo (BLF / guillotina recursiva, ver packing.py).
- Aptitud (minimizar):
      F = w1 * sum_j(merma_j / A_hoja_j)
        + w2 * sum_i(P_i * dT_i) / sum_i(P_i)
        - w3 * sum_k(A_retazo_k) / sum_j(A_hoja_j)
        + w4 * (sum_j(A_hoja_j) / sum(A_piezas) - 1)     (consumo de material)
        + penalización por piezas sin colocar (falta de inventario)
- Selección por torneo determinístico (k=3) con elitismo (5 %).
- Cruce OX o PMX. Mutación swap, inversión y alternancia de rotación.
- Parada por G_max, estancamiento o T_max.
"""
from __future__ import annotations

import math
import random
import time
from dataclasses import dataclass, field

from .packing import PackParams, Piece, SheetUnit, decode

UNPLACED_PENALTY = 1000.0


@dataclass
class GAParams:
    population: int = 60
    generations: int = 300  # G_max
    stagnation: int = 60  # X generaciones sin mejora
    time_limit: float = 20.0  # T_max (segundos)
    elite_frac: float = 0.05
    tournament_k: int = 3
    crossover: str = "OX"  # "OX" | "PMX"
    crossover_rate: float = 0.9
    mutation_rate: float = 0.3
    seed: int | None = None


@dataclass
class FitnessParams:
    w1: float = 1.0  # merma
    w2: float = 0.5  # desplazamiento en la cola
    w3: float = 0.3  # bonificación de retazos
    w4: float = 1.0  # consumo de material (ver doc/DECISIONES.md)
    window: int = 2  # ventana de tolerancia (posiciones) de RN-04
    urgent_weight: float = 3.0  # P_i de una orden urgente (normal = 1)


@dataclass
class Evaluation:
    fitness: float
    layouts: list
    unplaced: list
    displacement: dict  # order_id -> dT_i
    terms: dict


@dataclass
class GAResult:
    best: Evaluation
    chromosome: tuple
    generations: int
    elapsed: float
    history: list = field(default_factory=list)
    stop_reason: str = ""


class GeneticOptimizer:
    def __init__(self, pieces: list[Piece], stock: list[SheetUnit], pack: PackParams,
                 fit: FitnessParams, ga: GAParams, priorities: dict[int, float]):
        self.pieces = pieces
        self.stock = stock
        self.pack = pack
        self.fit = fit
        self.ga = ga
        self.priorities = priorities  # order_id -> P_i
        self.rng = random.Random(ga.seed)
        self.cache: dict[tuple, Evaluation] = {}
        # posición de cada orden dentro del subproblema
        ranks = sorted({(p.order_rank, p.order_id) for p in pieces})
        self.order_q = {oid: i for i, (_, oid) in enumerate(ranks)}
        self.total_piece_area = sum(p.w * p.h for p in pieces) or 1.0
        n = len(self.order_q)
        self.disp_norm = max(1.0, sum(priorities.get(o, 1.0) for o in self.order_q))

    # ------------------------------------------------------------------ aptitud
    def evaluate(self, chrom: tuple) -> Evaluation:
        ev = self.cache.get(chrom)
        if ev is not None:
            return ev
        layouts, unplaced = decode(chrom, self.pieces, self.stock, self.pack)
        t1 = sum(l.scrap_area / l.area for l in layouts)
        total_area = sum(l.area for l in layouts) or 1.0
        t3 = sum(l.offcut_area for l in layouts) / total_area
        disp = self._displacement(layouts, unplaced)
        t2 = sum(self.priorities.get(o, 1.0) * d for o, d in disp.items()) / self.disp_norm
        miss = sum(self.pieces[i].w * self.pieces[i].h for i in unplaced) / self.total_piece_area
        t4 = total_area / self.total_piece_area - 1.0 if layouts else 0.0
        f = (self.fit.w1 * t1 + self.fit.w2 * t2 - self.fit.w3 * t3 + self.fit.w4 * t4
             + UNPLACED_PENALTY * miss)
        ev = Evaluation(f, layouts, unplaced, disp,
                        {"merma": t1, "cola": t2, "retazos": t3, "consumo": t4, "faltante": miss})
        self.cache[chrom] = ev
        return ev

    def _displacement(self, layouts, unplaced) -> dict[int, int]:
        """dT_i: cuántas posiciones se atrasa la orden i respecto a la cola,
        más allá de la ventana de tolerancia. La "terminación" de una orden es
        el índice de la última hoja (en secuencia de corte) que la contiene."""
        done: dict[int, int] = {}
        for j, l in enumerate(layouts):
            for pl in l.placements:
                oid = self.pieces[pl.piece].order_id
                done[oid] = max(done.get(oid, -1), j)
        late = len(layouts)
        for i in unplaced:
            done[self.pieces[i].order_id] = late
        seq = sorted(self.order_q, key=lambda o: (done.get(o, late), self.order_q[o]))
        return {o: max(0, r - self.order_q[o] - self.fit.window) for r, o in enumerate(seq)}

    # --------------------------------------------------------------- población
    def _seed_population(self) -> list[tuple]:
        P = self.pieces
        idx = list(range(len(P)))
        rot_ok = self.pack.allow_rotation

        def lay_long(i):  # rota para dejar el lado largo sobre X
            return rot_ok and P[i].h > P[i].w

        orders = [
            sorted(idx, key=lambda i: (P[i].order_rank, -P[i].w * P[i].h)),
            sorted(idx, key=lambda i: -P[i].w * P[i].h),
            sorted(idx, key=lambda i: -max(P[i].w, P[i].h)),
            sorted(idx, key=lambda i: (-P[i].h, -P[i].w)),
            sorted(idx, key=lambda i: (-P[i].w, -P[i].h)),
        ]
        pop = []
        for o in orders:
            pop.append(tuple((i, False) for i in o))
            if rot_ok:
                pop.append(tuple((i, lay_long(i)) for i in o))
        while len(pop) < self.ga.population:
            o = idx[:]
            self.rng.shuffle(o)
            pop.append(tuple((i, rot_ok and self.rng.random() < 0.5) for i in o))
        return pop[: self.ga.population]

    # -------------------------------------------------------------- operadores
    def _tournament(self, pop, fits):
        k = min(self.ga.tournament_k, len(pop))
        cand = self.rng.sample(range(len(pop)), k)
        return pop[min(cand, key=lambda c: fits[c])]

    def _crossover(self, a: tuple, b: tuple) -> tuple:
        n = len(a)
        if n < 2:
            return a
        i, j = sorted(self.rng.sample(range(n), 2))
        if self.ga.crossover.upper() == "PMX":
            return _pmx(a, b, i, j)
        return _ox(a, b, i, j)

    def _mutate(self, c: tuple) -> tuple:
        c = list(c)
        n = len(c)
        if n == 0:
            return tuple(c)
        ops = ["swap", "inversion"] + (["rotation"] if self.pack.allow_rotation else [])
        op = self.rng.choice(ops)
        if op == "rotation":
            k = self.rng.randrange(n)
            c[k] = (c[k][0], not c[k][1])
        elif n >= 2:
            i, j = sorted(self.rng.sample(range(n), 2))
            if op == "swap":
                c[i], c[j] = c[j], c[i]
            else:
                c[i:j + 1] = reversed(c[i:j + 1])
        return tuple(c)

    # ------------------------------------------------------------------- ciclo
    def run(self) -> GAResult:
        t0 = time.monotonic()
        g = self.ga
        pop = self._seed_population()
        fits = [self.evaluate(c).fitness for c in pop]
        best_i = min(range(len(pop)), key=lambda i: fits[i])
        best, best_f = pop[best_i], fits[best_i]
        history = [best_f]
        stale = 0
        n_elite = max(1, math.ceil(g.elite_frac * g.population))
        gen = 0
        reason = "G_max alcanzado"
        if len(self.pieces) <= 1:
            reason = "Problema trivial"
        else:
            while gen < g.generations:
                if time.monotonic() - t0 >= g.time_limit:
                    reason = "T_max alcanzado"
                    break
                if stale >= g.stagnation:
                    reason = "Estancamiento"
                    break
                gen += 1
                order = sorted(range(len(pop)), key=lambda i: fits[i])
                new = [pop[i] for i in order[:n_elite]]
                while len(new) < g.population:
                    a = self._tournament(pop, fits)
                    if self.rng.random() < g.crossover_rate:
                        b = self._tournament(pop, fits)
                        child = self._crossover(a, b)
                    else:
                        child = a
                    if self.rng.random() < g.mutation_rate:
                        child = self._mutate(child)
                    new.append(child)
                pop = new
                fits = [self.evaluate(c).fitness for c in pop]
                i = min(range(len(pop)), key=lambda i: fits[i])
                if fits[i] < best_f - 1e-12:
                    best, best_f, stale = pop[i], fits[i], 0
                else:
                    stale += 1
                history.append(best_f)
        return GAResult(self.evaluate(best), best, gen, time.monotonic() - t0, history, reason)


def _ox(a: tuple, b: tuple, i: int, j: int) -> tuple:
    """Order Crossover: conserva el segmento [i, j] de `a` y completa con el
    orden relativo de `b`. Cada gen arrastra su estado de rotación."""
    n = len(a)
    seg = a[i:j + 1]
    taken = {g[0] for g in seg}
    rest = [g for g in b[j + 1:] + b[:j + 1] if g[0] not in taken]
    child = [None] * n
    child[i:j + 1] = seg
    pos = (j + 1) % n
    for g in rest:
        child[pos] = g
        pos = (pos + 1) % n
    return tuple(child)


def _pmx(a: tuple, b: tuple, i: int, j: int) -> tuple:
    """Partially Mapped Crossover sobre los IDs de pieza."""
    n = len(a)
    child = [None] * n
    child[i:j + 1] = a[i:j + 1]
    in_seg = {a[k][0]: k for k in range(i, j + 1)}
    pos_b = {b[k][0]: k for k in range(n)}
    for k in range(i, j + 1):
        g = b[k]
        if g[0] in in_seg:
            continue
        p = k
        while i <= p <= j:
            p = pos_b[a[p][0]]
        child[p] = g
    for k in range(n):
        if child[k] is None:
            child[k] = b[k]
    return tuple(child)
