"""原版 exe 的随机数 (MSVC CRT rand / srand), 2026-10-27.

seed = seed × 214013 + 2531011 (mod 2^32), rand() = (seed >> 16) & 0x7fff — 0..32767. exe 里到处是 `rand() % n`,
所以这里的 randrange / randint 也一律是 `rand() % 宽度` (含原版的取模偏差, n > 32768 时取不到大值).
接口兼容 random.Random 里我们用到的部分 (randrange / randint / random / choice / shuffle / sample / seed / getstate / setstate),
战斗 battle.rng 默认用它: 和 Unity 版 (BattleRng, 同一算法) 能用同一种子逐帧对照.
"""
from __future__ import annotations

import time
from typing import MutableSequence, Sequence, TypeVar

T = TypeVar("T")

RAND_MAX = 0x7FFF


class ExeRng:
    __slots__ = ("state",)

    def __init__(self, seed: int | None = None):
        self.state = 0
        self.seed(seed)

    def seed(self, seed: int | None = None) -> None:
        """= srand(seed). None → 当前时间 (exe 开局 srand(time(0)) 同理)."""
        if seed is None:
            seed = int(time.time() * 1000)
        self.state = int(seed) & 0xFFFFFFFF

    def rand(self) -> int:
        self.state = (self.state * 214013 + 2531011) & 0xFFFFFFFF
        return (self.state >> 16) & RAND_MAX

    # ---- random.Random 兼容 ----
    def randrange(self, start: int, stop: int | None = None, step: int = 1) -> int:
        if stop is None:
            start, stop = 0, start
        width = (stop - start + step - 1) // step if step > 0 else (start - stop - step - 1) // -step
        if width <= 0:
            raise ValueError(f"empty range for randrange({start}, {stop}, {step})")
        return start + step * (self.rand() % width)

    def randint(self, a: int, b: int) -> int:
        return self.randrange(a, b + 1)

    def random(self) -> float:
        return self.rand() / (RAND_MAX + 1)

    def choice(self, seq: Sequence[T]) -> T:
        if not seq:
            raise IndexError("cannot choose from an empty sequence")
        return seq[self.rand() % len(seq)]

    def shuffle(self, x: MutableSequence) -> None:
        for i in range(len(x) - 1, 0, -1):
            j = self.rand() % (i + 1)
            x[i], x[j] = x[j], x[i]

    def sample(self, population: Sequence[T], k: int) -> list[T]:
        pool = list(population)
        if not 0 <= k <= len(pool):
            raise ValueError("sample larger than population")
        out = []
        for _ in range(k):
            out.append(pool.pop(self.rand() % len(pool)))
        return out

    def getstate(self) -> int:
        return self.state

    def setstate(self, state: int) -> None:
        self.state = int(state) & 0xFFFFFFFF
