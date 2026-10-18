"""无头跑序章场景, 每隔若干 tick 截一张图 (调试演出用, 不需要开窗口).

跑法: cd rewrite && venv/bin/python -m tools.prologue_shots [输出目录] [--every 100] [--max 20000] [--from 0]
"""
from __future__ import annotations

import os
import sys
import time
from pathlib import Path

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import pygame  # noqa: E402


def main(argv: list[str]) -> int:
    out = Path(argv[0]) if argv and not argv[0].startswith("-") else Path("/tmp/prologue_shots")
    every = int(argv[argv.index("--every") + 1]) if "--every" in argv else 100
    maxt = int(argv[argv.index("--max") + 1]) if "--max" in argv else 20000
    start = int(argv[argv.index("--from") + 1]) if "--from" in argv else 0
    out.mkdir(parents=True, exist_ok=True)
    pygame.init()
    surface = pygame.display.set_mode((800, 600))
    from scenes.prologue import PrologueScene
    sc = PrologueScene(surface, start_event=start)
    sc.on_enter()
    t0 = time.time()
    n = 0
    while not sc.done and n < maxt:
        sc.step()
        n += 1
        if n % every == 0:
            sc.draw()
            pygame.image.save(surface, str(out / f"t{n:05d}.png"))
    print(f"{n} ticks in {time.time() - t0:.1f}s, done={sc.done}, events={sc.runner.history if sc.runner else None}")
    for ln in sc.log_lines[-30:]:
        print("  ", ln)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
