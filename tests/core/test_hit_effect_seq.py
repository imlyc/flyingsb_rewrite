"""hit_effect_seq — 普攻 IMPACT spawn 2 个 effect: ATK_C 长椭圆 / 紫色 starburst + 小红刺爆."""

from core.hit_effect_seq import (
    ATK_C_OVAL_BY_DIR,
    CLAW_BY_DIR,
    UNIVERSAL_SPARK_BY_DIR,
    UNIVERSAL_STARBURST_FRAMES,
    facing_to_dir,
    pick_hit_effects,
)


def test_facing_to_dir():
    assert facing_to_dir((1, 0)) == "RT"
    assert facing_to_dir((-1, 0)) == "LF"
    assert facing_to_dir((0, 1)) == "DN"
    assert facing_to_dir((0, -1)) == "UP"


def test_universal_spark_4_dirs():
    assert set(UNIVERSAL_SPARK_BY_DIR.keys()) == {"UP", "DN", "LF", "RT"}
    for d, frames in UNIVERSAL_SPARK_BY_DIR.items():
        assert len(frames) == 3


def test_atk_c_oval_lf_rt_reuse_up_dn():
    # exe 表里 LF/RT 直接复用 UP/DN frames, 不是 dump bug
    assert ATK_C_OVAL_BY_DIR["LF"] == ATK_C_OVAL_BY_DIR["UP"]
    assert ATK_C_OVAL_BY_DIR["RT"] == ATK_C_OVAL_BY_DIR["DN"]


def test_starburst_is_2_frames():
    # fm_ET00 frame 14, 15 (4 ticks/帧 × 2 帧 = 320ms 总)
    assert UNIVERSAL_STARBURST_FRAMES == [14, 15]


def test_atk_a_picks_starburst_and_spark():
    # 孙悟空 form 1 = ATK_A, 朝右
    specs = pick_hit_effects("孙悟空", None, (1, 0))
    assert len(specs) == 2
    # 1st: starburst (jittered)
    assert specs[0].atlas_key == "et00"
    assert specs[0].frames == [14, 15]
    assert specs[0].frame_ticks == 4
    assert specs[0].jittered is True
    # 2nd: 小红刺爆 RT (= ef010 frames 3,4,5)
    assert specs[1].atlas_key == "ef010"
    assert specs[1].frames == [3, 4, 5]
    assert specs[1].frame_ticks == 2
    assert specs[1].jittered is False


def test_atk_b_also_picks_starburst():
    # 美娜 = ATK_B
    specs = pick_hit_effects("美娜", None, (0, -1))
    assert specs[0].atlas_key == "et00"
    assert specs[0].frames == [14, 15]


def test_atk_c_picks_oval_and_spark():
    # 蒙面人 form 1 = ATK_C, 朝下
    specs = pick_hit_effects("蒙面人", 1, (0, 1))
    assert len(specs) == 2
    # 1st: 长椭圆 DN = ef010 frames 24,25,26
    assert specs[0].atlas_key == "ef010"
    assert specs[0].frames == [24, 25, 26]
    assert specs[0].frame_ticks == 2
    assert specs[0].jittered is True
    # 2nd: 小红刺爆 DN = ef010 frames 15,16,17
    assert specs[1].atlas_key == "ef010"
    assert specs[1].frames == [15, 16, 17]


def test_claw_lf_rt_reuse_up_dn():
    # 抓痕表跟椭圆表同模式
    assert CLAW_BY_DIR["LF"] == CLAW_BY_DIR["UP"]
    assert CLAW_BY_DIR["RT"] == CLAW_BY_DIR["DN"]


def test_skeleton_picks_oval():
    # exe: cskel_g0 → OVAL (= 跟蒙面人同款)
    specs = pick_hit_effects("骷髅", None, (1, 0))
    assert specs[0].atlas_key == "ef010"
    assert specs[0].frames == ATK_C_OVAL_BY_DIR["RT"]


def test_crow_picks_claw():
    # exe: ccrow_g1 (双啄, 我们用的形态) → CLAW
    specs = pick_hit_effects("乌鸦怪", None, (0, -1))
    assert specs[0].atlas_key == "ef010"
    assert specs[0].frames == CLAW_BY_DIR["UP"]
    assert specs[0].frames == [43, 44, 42]


def test_ghou_picks_starburst():
    # exe: cghou_g0 → STARBURST (G1 才用 CLAW, 但我们用 G0)
    specs = pick_hit_effects("黄色怪", None, (1, 0))
    assert specs[0].atlas_key == "et00"


def test_atlas_table_some_entries():
    # 确保关键 exe-derived 映射不被回归改掉
    from core.hit_effect_seq import ATLAS_HIT_FX
    assert ATLAS_HIT_FX["cskel_g0"] == "OVAL"
    assert ATLAS_HIT_FX["ccrow_g0"] == "OVAL"      # 单啄
    assert ATLAS_HIT_FX["ccrow_g1"] == "CLAW"      # 双啄
    assert ATLAS_HIT_FX["cghou_g1"] == "CLAW"
    # 没明确列的: cghou_g0 (= 走默认 STARBURST), 不在表里
    assert "cghou_g0" not in ATLAS_HIT_FX


def test_unknown_enemy_picks_starburst():
    specs = pick_hit_effects("某种新敌人", None, (1, 0))
    assert specs[0].atlas_key == "et00"


# ---- end-to-end: spec → bytecode → anim_engine entity ----

def test_spec_to_bytecode_fm_then_exit():
    """3 帧 FM (10B each) + EXIT (2B) = 32B."""
    from core.hit_effect_seq import HitEffectSpec
    spec = HitEffectSpec("ef010", [12, 13, 14], frame_ticks=2, jittered=False)
    bc = spec.to_bytecode()
    assert len(bc) == 3 * 10 + 2
    assert bc[0] == 0x04 and bc[1] == 0x0a       # 1st op = FM size 10
    assert bc[30] == 0x00 and bc[31] == 0x02     # 末尾 = EXIT size 2


def test_spec_runs_through_engine():
    """bytecode 挂到 engine, tick 累加, 帧推进, 最终 EXIT 落 playing flag."""
    from core.anim_engine.engine import Engine
    from core.hit_effect_seq import HitEffectSpec

    eng = Engine()
    e = eng.spawn()
    e.user_data['kind'] = 'hit_effect'
    e.user_data['atlas_key'] = 'ef010'
    spec = HitEffectSpec("ef010", [12, 13, 14], frame_ticks=2, jittered=False)
    eng.attach_seq(e, spec.to_bytecode())

    # attach_seq 跑到第一个阻塞 FM op (frame 12, ticks=2)
    assert e.is_playing()
    assert e.atlas_slot == 216    # ef010 全局 idx
    assert e.frame_idx == 12
    assert e.ticks == 2

    # 跑足够多 tick 让 3 帧依次显示 + EXIT 触发. tick 数因 dispatch-don't-decrement-same-tick
    # 规则会比 (ticks * frames) 多一些, 不死磕精确数, 验证语义即可.
    frames_seen = []
    for _ in range(15):
        eng.tick()
        frames_seen.append(e.frame_idx if e.is_playing() else None)

    assert 12 in frames_seen
    assert 13 in frames_seen
    assert 14 in frames_seen
    # EXIT 后 playing flag 落下
    assert frames_seen[-1] is None
    # 帧顺序: 12 全在 13 前, 13 全在 14 前
    last_12 = max(i for i, f in enumerate(frames_seen) if f == 12)
    first_13 = min(i for i, f in enumerate(frames_seen) if f == 13)
    last_13 = max(i for i, f in enumerate(frames_seen) if f == 13)
    first_14 = min(i for i, f in enumerate(frames_seen) if f == 14)
    assert last_12 < first_13 < last_13 < first_14


def test_unknown_name_picks_starburst():
    specs = pick_hit_effects("不存在", None, (0, 1))
    assert specs[0].atlas_key == "et00"
