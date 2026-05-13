"""FloatText 生命周期 phases: pre → rise → hold → flash → done.

不渲染 (draw 需要 pygame surface + 字体), 只测时序状态机.
"""

from scenes.battle.float_text import FloatText


# 各阶段 tick 数 (40ms/tick): rise=10, hold=32, flash=32
RISE = FloatText.RISE_TICKS
HOLD = FloatText.HOLD_TICKS
FLASH = FloatText.FLASH_TICKS
TICK = FloatText.TICK_MS
DRIP = FloatText.DRIP_PERIOD_TICKS    # 2 = 80ms per digit


def _ft(damage=42, started_at=0, miss=False):
    return FloatText(damage, remaining_hp=10, world_x=100, world_y=100,
                     started_at=started_at, miss=miss)


def test_digit_count_for_damage():
    """42 → 2 digits; 100 → 3 digits; 0 → 1 digit ('0' itself, max(0, dmg))."""
    assert _ft(42)._n == 2
    assert _ft(100)._n == 3
    assert _ft(0)._n == 1
    assert _ft(-5)._n == 1               # negative clamps to 0


def test_miss_has_4_frames():
    """MISS = M/I/S/S, 4 frames."""
    assert _ft(miss=True)._n == 4


def test_pre_phase_before_started():
    """now < started → 'pre' phase, life_ticks = -1."""
    ft = _ft(damage=7, started_at=1000)
    _, phase, _ = ft._digit_state(0, now_ms=500)
    assert phase == 'pre'


def test_rise_to_hold_to_flash_to_done_transitions():
    """digit 0 走完整生命周期."""
    ft = _ft(damage=7, started_at=0)
    # rise: 0 ~ RISE-1 ticks
    _, phase, _ = ft._digit_state(0, now_ms=0)
    assert phase == 'rise'
    _, phase, _ = ft._digit_state(0, now_ms=(RISE - 1) * TICK)
    assert phase == 'rise'
    # hold: RISE ~ RISE+HOLD-1
    _, phase, _ = ft._digit_state(0, now_ms=RISE * TICK)
    assert phase == 'hold'
    # flash: +HOLD
    _, phase, _ = ft._digit_state(0, now_ms=(RISE + HOLD) * TICK)
    assert phase == 'flash'
    # done: +FLASH
    _, phase, _ = ft._digit_state(0, now_ms=(RISE + HOLD + FLASH) * TICK)
    assert phase == 'done'


def test_drip_offset_per_digit():
    """digit i 比 digit 0 晚 i * DRIP_PERIOD * TICK = 80ms · i 出生."""
    ft = _ft(damage=42, started_at=0)
    # at now=0, digit 0 is 'rise', digit 1 still 'pre' (offset 80ms 还没到)
    _, p0, _ = ft._digit_state(0, now_ms=0)
    _, p1, _ = ft._digit_state(1, now_ms=0)
    assert p0 == 'rise'
    assert p1 == 'pre'
    # at now=80ms (= drip period), digit 1 启动
    _, p1, _ = ft._digit_state(1, now_ms=DRIP * TICK)
    assert p1 == 'rise'


def test_alive_uses_last_digit():
    """alive 看最后一位是否 done. 多位数字最后一位最晚生命周期结束."""
    ft = _ft(damage=42, started_at=0)
    n = ft._n
    total_ms_for_last = (
        (n - 1) * DRIP * TICK            # last digit 出生时间
        + (RISE + HOLD + FLASH) * TICK   # 走完完整生命
    )
    assert ft.alive(now_ms=total_ms_for_last - 1)
    assert not ft.alive(now_ms=total_ms_for_last)


def test_flash_started_at():
    """flash_started_at 看第一位 (最早进 flash 的) 是否已 flash."""
    ft = _ft(damage=42, started_at=0)
    flash_start_ms = (RISE + HOLD) * TICK
    assert not ft.flash_started_at(now_ms=flash_start_ms - 1)
    assert ft.flash_started_at(now_ms=flash_start_ms)
    assert ft.flash_started_at(now_ms=flash_start_ms + 99999)   # done 也算


def test_miss_digit_frames_use_miss_table():
    """miss=True 用 SBTLFONT_MISS_FRAMES, 不走数字编码."""
    from core.sprites.loaders import SBTLFONT_MISS_FRAMES
    ft = _ft(miss=True)
    assert ft._frames == list(SBTLFONT_MISS_FRAMES)


def test_damage_digit_frames_offset_by_base():
    """damage=70 → digits '7','0' → frames [BASE+7, BASE+0]."""
    from core.sprites.loaders import SBTLFONT_DAMAGE_BASE_FRAME as BASE
    ft = _ft(damage=70)
    assert ft._frames == [BASE + 7, BASE + 0]
