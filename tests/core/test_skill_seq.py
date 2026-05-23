"""技能 seq 数据 + 接通 attack_seq_for / begin_attack 验证."""

from core.attack_seq import attack_seq_for
from core.skill_seq import (
    SKILL_SEQS,
    SKILL_VERTICAL_SLASH,
    has_skill_seq,
    skill_cost,
    skill_seq_for,
)


def test_vertical_slash_4_dirs_each_uses_atlas_19():
    """exe dump: 垂直斬 4 方向都用 atlas 19 (= cdit1_g0); UP 用 frames 0-11 等."""
    assert len(SKILL_VERTICAL_SLASH) == 4
    for dir_idx, seq in enumerate(SKILL_VERTICAL_SLASH):
        fm_ops = [t for t in seq if t[0] == 'fm']
        for op in fm_ops:
            assert op[1] == 19, f"dir {dir_idx} expected atlas 19, got {op[1]}"


def test_vertical_slash_has_init_impact_end_signals():
    """每方向都有 -1000 init + -100 IMPACT + -110 END 信号."""
    for seq in SKILL_VERTICAL_SLASH:
        kinds = [t[0] for t in seq]
        assert 'jump' in kinds        # -1000 init
        assert 'impact' in kinds      # -100
        assert 'end' in kinds         # -110


def test_skill_seqs_lookup():
    """skill_id 0x20 → 垂直斬; 未实现 skill_id → has_skill_seq False."""
    assert has_skill_seq(0x20) is True
    assert has_skill_seq(0x21) is False    # 赤雲波 暂未 dump
    assert 0x20 in SKILL_SEQS


def test_skill_seq_for_facing():
    """facing → seq 列表的方向索引."""
    seq_up = skill_seq_for(0x20, (0, -1))
    seq_rt = skill_seq_for(0x20, (1, 0))
    assert seq_up == SKILL_VERTICAL_SLASH[0]
    assert seq_rt == SKILL_VERTICAL_SLASH[3]


def test_attack_seq_for_routes_to_skill_when_skill_id_given():
    """带 skill_id → 走 skill_seq, 不带 → 走普攻."""
    seq_skill = attack_seq_for("蒙面人", (0, -1), skill_id=0x20)
    seq_atk = attack_seq_for("蒙面人", (0, -1), skill_id=None)
    assert seq_skill == SKILL_VERTICAL_SLASH[0]
    assert seq_skill != seq_atk


def test_unimplemented_skill_falls_back_to_normal_attack():
    """未 dump 的 skill_id 回落到角色普攻 seq (= 不崩, 视觉先 work)."""
    seq_skill = attack_seq_for("蒙面人", (0, -1), skill_id=0x21)   # 赤雲波 没 dump
    seq_atk = attack_seq_for("蒙面人", (0, -1), skill_id=None)
    assert seq_skill == seq_atk


def test_skill_bytecode_compiles():
    """skill seq 能编进 bytecode (= anim_engine 能跑)."""
    from core.anim_engine.bytecode import tuple_to_bytecode
    bc = tuple_to_bytecode(skill_seq_for(0x20, (1, 0)))
    assert len(bc) > 100   # 30+ ops × ≥4B
    # bytecode 末尾应是 SIGNAL -110 (end) = `0e 04 92 ff` (signed -110 = 0xff92)
    assert bc[-4] == 0x0e


def test_skill_cost():
    assert skill_cost(0x20) == 175
    assert skill_cost(0xFF) == 0


def test_infinite_blade_5_impacts_mid_atlas_switch():
    """無限刀 0x24: 4 方向各 5 段 IMPACT, atlas 20 (cdit1_g1) 主体 + 终结切 atlas 19 (cdit1_g0)."""
    from core.skill_seq import SKILL_INFINITE_BLADE
    assert len(SKILL_INFINITE_BLADE) == 4
    for dir_idx, seq in enumerate(SKILL_INFINITE_BLADE):
        impacts = [t for t in seq if t[0] == 'impact']
        assert len(impacts) == 5, f"dir {dir_idx} expected 5 IMPACTs, got {len(impacts)}"
        atlases = {t[1] for t in seq if t[0] == 'fm'}
        assert atlases == {19, 20}, f"dir {dir_idx} expected atlas 19+20, got {atlases}"


def test_vertical_slash_impact_extra():
    """垂直斬 IMPACT 时 dispatcher 额外 spawn 12 帧放电特效 (ds_mag28 + ds_mag13)."""
    from core.skill_seq import (
        SKILL_IMPACT_EXTRA, has_skill_impact_extra, skill_impact_extra_seq,
    )
    assert has_skill_impact_extra(0x20) is True
    assert has_skill_impact_extra(0x21) is False    # 赤雲波 暂未实现
    assert has_skill_impact_extra(None) is False
    seq = skill_impact_extra_seq(0x20)
    fm_ops = [t for t in seq if t[0] == 'fm']
    # 5 帧 atlas 231 + 7 帧 atlas 230 = 12 帧
    assert len(fm_ops) == 12
    atlases = {op[1] for op in fm_ops}
    assert atlases == {230, 231}       # mid-seq atlas 切换
    # 最末 EXIT
    assert seq[-1] == ('exit',)
    # bytecode 编码能跑
    from core.anim_engine.bytecode import tuple_to_bytecode
    bc = tuple_to_bytecode(seq)
    assert len(bc) > 100