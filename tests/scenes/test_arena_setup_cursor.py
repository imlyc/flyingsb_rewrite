"""竞技场选人: 末行不满时, 倒数第二行任意列按 ↓ 都能到末行 (正下方没角色 → 落到末行最后一个)."""
import os

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
import pygame  # noqa: E402


def test_down_into_short_last_row():
    pygame.init()
    surf = pygame.display.set_mode((800, 600))
    from core.audio_manager import AudioManager
    from scenes.arena.setup_scene import ArenaSetupScene, COLS
    s = ArenaSetupScene(surf, AudioManager())
    s.on_enter()
    s.side, s.region = 1, 0
    n = len(s._cur_list())
    last_row = (n - 1) // COLS
    assert n % COLS != 0, "名册末行应不满 (本测试前提)"
    for col in range(COLS):
        s.idx = (last_row - 1) * COLS + col
        s._move_cursor(0, 1)
        exp = last_row * COLS + col
        assert s.idx == (exp if exp < n else n - 1)
    s.idx = n - 1
    s._move_cursor(0, 1)                       # 已在末行: 不动
    assert s.idx == n - 1
