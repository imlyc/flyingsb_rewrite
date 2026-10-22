"""飘字数字实体 (core.battle.float_digits) 按 exe FUN_004d0488/4d0330/4d074e/4d06b0 的状态机与时序."""
import random

from core.anim_engine.engine import Engine
from core.battle import float_digits as fd


class _Unit:
    def __init__(self, x=3, y=4):
        self.x, self.y = x, y


class _Battle:
    def __init__(self):
        self.engine = Engine()
        self.rng = random.Random(1)
        self.float_pending = 0
        self.float_events = []


def _digits(b):
    return [e for e in b.engine.entities if (e.flags & 0x800) and e.user_data.get('digit')]


def _run(b, n):
    for _ in range(n):
        b.engine.tick()


def test_damage_digits_drip_every_2_ticks_and_positions():
    b = _Battle(); u = _Unit()
    fd.spawn_float(b, u, 1234)
    assert b.float_pending == 1
    born = {}
    for t in range(1, 12):
        b.engine.tick()
        for e in _digits(b):
            born.setdefault(e.id, t)
    assert sorted(born.values()) == [1, 3, 5, 7]           # 奇数 tick 一位
    ds = sorted(_digits(b), key=lambda e: e.x)
    assert [e.frame_idx for e in ds] == [14, 15, 16, 17]   # 红行 '1'..'4' = 字符-0x23
    cx = (3 * 64 + 32) << 16
    assert [(e.x - cx) >> 16 for e in ds] == [-20, -10, 0, 10]
    assert all(not (e.flags & 0x800) or not e.user_data.get('spawner') for e in b.engine.entities)


def test_damage_digit_state_machine_timing():
    b = _Battle(); u = _Unit()
    fd.spawn_float(b, u, 7)                                 # 1 位: tick 1 生成
    _run(b, 1)
    d = _digits(b)[0]
    assert (-d.z) >> 16 == 42                               # 出生即走一步: 428+16-1.5-400 = 42.5 (实录首帧 z=442)
    hist = []
    for _ in range(100):
        b.engine.tick()
        if d.flags & 0x800:
            hist.append(d.state_code)
    st = {s: hist.count(s) for s in set(hist)}
    # 实录 dump 0×20 1×10 2×32 3×32 (含出生帧); 这里从出生后一 tick 起数 → 0 少 1
    assert st[0] == 19 and st[1] == 10 and st[2] == 32 and st[3] == 32
    assert len(hist) == 93
    # 末位落定 (state 2) → float_pending 归零 + settled; 首位进闪烁 → flash
    assert b.float_pending == 0
    assert ('settled', u) in b.float_events and ('flash', u) in b.float_events
    assert b.float_events.index(('settled', u)) < b.float_events.index(('flash', u))


def test_damage_digit_peak_height():
    b = _Battle(); u = _Unit()
    fd.spawn_float(b, u, 5)
    _run(b, 1)
    d = _digits(b)[0]
    peak = 0
    for _ in range(30):
        b.engine.tick(); peak = max(peak, (-d.z) >> 16)
    assert 100 <= peak <= 106                               # 实录 z 428→505 ⇒ 敌 y 上方 ~105px


def test_miss_frames():
    b = _Battle(); u = _Unit()
    fd.spawn_float(b, u, None)
    _run(b, 8)
    assert sorted(e.frame_idx for e in _digits(b)) == [23, 24, 25, 25]


def test_heal_digits_spawn_together_and_descend():
    b = _Battle(); u = _Unit()
    fd.spawn_float(b, u, 60, heal=True)
    hs = [e for e in b.engine.entities if e.user_data.get('heal_digit')]
    assert [e.frame_idx for e in hs] == [6, 0]              # 白行 '6','0' = 字符-0x30
    assert (-hs[0].z) >> 16 == 83                           # 出生即走一步: 487.5 - 404 (实录首帧 z=487)
    st0 = 0
    for _ in range(100):
        b.engine.tick()
        if hs[-1].flags & 0x800 and hs[-1].state_code == 0:
            st0 += 1
    assert st0 == 55                                        # 实录 state 0 共 56 帧 (含出生帧): 0.5px/t 488→460
    assert not (hs[-1].flags & 0x800)                       # <448 消失 (再 24t)
    assert b.float_pending == 0 and ('settled', u) in b.float_events
