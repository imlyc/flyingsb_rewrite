"""把 Python 战斗数值层的数据表 + 黄金对照样本导出给 Unity 工程 (flyingsb-unity, FlyingSb.Domain.Tactics).

  python3 -m tools.export_unity_tactics <unity 工程根>
    → Assets/FlyingSb/Resources/Tactics/TacticsData.json        (运行数据: 技能/敌招/敌人/角色/道具/普攻表)
    → Assets/FlyingSb/Tests/EditMode/Golden/tactics_golden.json (同种子下 Python 公式的输入输出, C# 测试逐项比对)

黄金样本: 用固定 random.Random 种子随机生成场景 (角色/等级/装备/敌人/站位/朝向/状态), 每个用例记录
调用前的单位快照 + rng 种子 + 返回值 + 调用后被改动的字段 + rng 状态. 随机数是 core.exe_rng (= C# BattleRng).
"""
from __future__ import annotations

import json
import random
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core import character_data as CD  # noqa: E402
from core import normal_attack as NA  # noqa: E402
from core.battle import energy, formulas as F, settlement, status  # noqa: E402
from core.battle.setup import PLAYER_UNIT_CLASS, make_enemy_by_type, unit_from_character  # noqa: E402
from core.battle.tactics import TacticsBattle  # noqa: E402
from core.enemy_move_data import MOVES  # noqa: E402
from core.enemy_moves import heal_amount as enemy_heal_amount, move as enemy_move, resolve_status, status_chance  # noqa: E402
from core.exe_rng import ExeRng  # noqa: E402
from core.items import is_equippable, item_slot_mask  # noqa: E402
from core.normal_attack_data import ATTACK_ENTRIES, WEAPON_ATTACK  # noqa: E402
from core.skill_table import SKILL_TABLE  # noqa: E402
from core.skills import CHARACTER_SKILL_POOL  # noqa: E402
from core.skill_patterns_data import ACTION_TEMPLATES, PATTERN_SET1, PATTERN_SET2, SKILL_TEMPLATE  # noqa: E402
from core.battle import ai_exe  # noqa: E402
from core import hit_effect_seq  # noqa: E402
from core.reaction_seq import DODGE_SEQ, HIT_SEQ  # noqa: E402

PLAYERS = list(CD.NAME_TO_RECORD)
UNIT_FIELDS = ('name', 'level', 'max_hp', 'hp', 'max_mp', 'mp', 'sg', 'attack', 'defence', 'agile', 'move', 'is_player',
               'x', 'y', 'luck', 'magic_atk', 'evade', 'speed', 'action_value', 'exp_reward', 'money_reward',
               'drop_item', 'drop_rate', 'enemy_type', 'unit_class', 'wisdom', 'type_flags', 'status_bits',
               'attack_normal', 'attack_melee')


# ---------------- 数据表 ----------------
def export_data() -> dict:
    from core import items as IT
    from scenes.arena.roster import ENEMY_ROSTER as ARENA_ROSTER
    chars = json.loads((ROOT / 'assets/characters_table.json').read_text(encoding='utf-8'))
    items = json.loads((ROOT / 'assets/items_table.json').read_text(encoding='utf-8'))['items']
    return {
        'skills': {str(k): list(v) for k, v in SKILL_TABLE.items()},
        'name_hit_style': {n: __import__('core.hit_effect_seq', fromlist=['x'])._resolve_first_spawn_style(n, None)
                           for n in ('孙悟空', '美娜', '乐神杰特', '紫河', '三藏法师', '猪八戒', '蒙面人', '破无', '捕山', '沙悟净')},
        'skill_names': {str(k): v for k, v in __import__('core.skills', fromlist=['SKILLS']).SKILLS.items()},
        'skill_descs': {str(k): d for k in __import__('core.skills', fromlist=['SKILLS']).SKILLS
                        if (d := __import__('core.skills', fromlist=['get_skill_desc']).get_skill_desc(k))},
        'consumables': {str(i): [IT.get_item_name(i), *IT.item_effect(i)] for i in sorted(IT.ITEMS)
                        if IT.get_item_category(i) is IT.ItemCategory.CONSUMABLE},   # 战斗道具菜单 (scene._draw_item_menu)
        'arena_enemy_roster': [int(k[1:]) for k in ARENA_ROSTER if k.startswith('#')],   # scenes.arena.roster.ENEMY_ROSTER
        'enemy_moves': [list(m[:7]) + [m[7], int(m[8][4:], 16) if m[8] else -1] for m in MOVES],   # name power flags mp_cost p4 template fn kind called(模板函数地址)
        'enemies': json.loads((ROOT / 'assets/enemy_table.json').read_text(encoding='utf-8'))['enemies'],
        'characters': chars['characters'],
        'growth_rows': chars['growth_rows'],
        'exp_table': chars['exp_table'],
        'skill_learn': {k: v['learn'] for k, v in
                        json.loads((ROOT / 'assets/skill_learn.json').read_text(encoding='utf-8'))['records'].items()},
        'skill_pools': CHARACTER_SKILL_POOL,
        'story_skills': CD.STORY_LEARNED,
        'record_names': CD.RECORD_NAME,
        'name_to_record': CD.NAME_TO_RECORD,
        'items': {k: {'val': int(v.get('val', 0) or 0), 'slot': int(v.get('slot', 0) or 0), 'type': int(v.get('type', 0) or 0),
                      'stats': {s: int(n) for s, n in (v.get('stats') or {}).items() if n}} for k, v in items.items()},
        'attack_entries': [[e[0], e[1], e[2], e[4]] for e in ATTACK_ENTRIES],   # group flags template kind
        'weapon_attack': {str(k): list(v) for k, v in WEAPON_ATTACK.items()},
        'char_group': NA.CHAR_GROUP,
        'ranged_melee': NA.RANGED_MELEE,
        'energy_type': energy.ENERGY_TYPE,
        'unit_class': PLAYER_UNIT_CLASS,
        'action_templates': [list(t) for t in ACTION_TEMPLATES],
        'pattern_set1': [[list(r) for r in g] for g in PATTERN_SET1],
        'pattern_set2': [[list(r) for r in g] for g in PATTERN_SET2],
        'skill_template': {str(k): v for k, v in SKILL_TEMPLATE.items()},
        'ai_template_flags': list(ai_exe.TEMPLATE_FLAGS),
        'seqs': export_seqs(),
        'attack_fx': [[e[6], list(e[7]) if e[7] else None, list(e[8]) if e[8] else None, e[5]] for e in ATTACK_ENTRIES],
        'move_seq': [[m[9], m[10]] for m in MOVES],              # 敌招 DOIT seq 表 / 命中特效
        'hit_fx': {k: [hit_effect_seq.ATLAS_KEY_TO_IDX[a], {d: list(v) for d, v in by.items()}, t]
                   for k, (a, by, t) in hit_effect_seq._STYLE_PRESETS.items()} | {
                   'SPARK': [hit_effect_seq.ATLAS_KEY_TO_IDX[hit_effect_seq.UNIVERSAL_SPARK_ATLAS],
                             {d: list(v) for d, v in hit_effect_seq.UNIVERSAL_SPARK_BY_DIR.items()},
                             hit_effect_seq.UNIVERSAL_SPARK_FRAME_TICKS]},
        'seq_meta': export_seq_meta(),
        'reaction': {'hit': [[list(st) for st in sq] for sq in HIT_SEQ], 'dodge': [[list(st) for st in sq] for sq in DODGE_SEQ]},
    }


_SEQ_OPS = {'fm', 'idle', 'fm_mode1', 'move', 'sound', 'impact', 'jump', 'end', 'exit', 'loop', 'raw'}


def _is_seq(v) -> bool:
    return isinstance(v, list) and bool(v) and all(isinstance(t, tuple) and t and isinstance(t[0], str) and t[0] in _SEQ_OPS
                                                   for t in v)


def spell_seq_tables() -> dict:
    """core/enemy_spells 各模块的 seq 常量 (演出 C# 版按名取, 免手抄): sp/<模块>.<名> 单段, sp/<模块>.<名>/<i> 按朝向等下标."""
    import importlib, pkgutil
    import core.enemy_spells as P
    out = {}
    for info in sorted(pkgutil.iter_modules(P.__path__), key=lambda i: i.name):
        mod = importlib.import_module(f'core.enemy_spells.{info.name}')
        for k, v in sorted(vars(mod).items()):
            if k.startswith('_') and not k.startswith('_HOP'):
                continue
            if _is_seq(v):
                out[f'sp/{info.name}.{k}'] = v
            elif isinstance(v, (list, tuple)) and v and all(_is_seq(x) for x in v):
                for i, x in enumerate(v):
                    out[f'sp/{info.name}.{k}/{i}'] = x
    from core.enemy_spells import m133                      # 运行时拼出的 seq (首遍跳帧的摇扇)
    for d in range(4):
        out[f'sp/m133.fan_seq/{d}'] = m133.fan_seq(d)
    return out


def _all_seq_tuples() -> dict:
    from core.enemy_move_data import SEQ_TABLES as EM_SEQ
    from core.normal_attack_data import SEQ_TABLES as NA_SEQ
    out = {}
    for pre, tables in (('na', NA_SEQ), ('em', EM_SEQ)):
        for k, dirs in tables.items():
            for d, sq in enumerate(dirs):
                out[f'{pre}/{k}/{d}'] = sq
    out.update(spell_seq_tables())
    out.update(skill_seq_tables())
    out.update(ranged_seq_tables())
    return out


def ranged_seq_tables() -> dict:
    """远程普攻 (core.ranged_attack): ra/<表>/<方向> = 信号重映射后的施法 / 重挂 seq (-100/-150/-110/-105 → RA_*),
    na1/<地址> = normal_attack_data.SEQS 单条 seq (火爆 / 冒烟 / 火球)."""
    from core import ranged_attack as RA
    from core.normal_attack_data import SEQ_TABLES as NA_SEQ, SEQS as NA_SEQS1
    tables = set(RA.CAST_TABLE.values()) | set(RA.RECAST_TABLE.values()) | {a for k, a in RA.KINDS.values() if k == 'pig_hitscan'}
    out = {}
    for t in sorted(tables):
        for d, sq in enumerate(NA_SEQ[t]):
            out[f'ra/{t}/{d}'] = RA._remap(sq)
    for addr, sq in NA_SEQS1.items():
        out[f'na1/{addr}'] = sq
    return out


PLAYER_SKILL_MODULES = ('skill_seq', 'sam_skills', 'pig_skills', 'pao_skills', 'bosan_skills', 'jet_skills', 'mina_skills',
                        'jah_skills', 'projectile', 'son_transform', 'fenshen_seqs', 'ranged_attack')


def skill_seq_tables() -> dict:
    """玩家技能: sk/<sid>/<方向> = core.skill_seq.SKILL_SEQS (施法 seq), sk/extra/<sid> = SKILL_IMPACT_EXTRA;
    ps/<模块>.<名>[/i] = 技能模块里的 seq 常量 (C# 版按名取)."""
    import importlib
    from core.skill_seq import SKILL_SEQS, SKILL_IMPACT_EXTRA
    out = {}
    for sid, dirs in SKILL_SEQS.items():
        for d, sq in enumerate(dirs):
            out[f'sk/{sid}/{d}'] = list(sq)
    for sid, sq in SKILL_IMPACT_EXTRA.items():
        out[f'sk/extra/{sid}'] = sq
    for name in PLAYER_SKILL_MODULES:
        mod = importlib.import_module(f'core.{name}')
        for k, v in sorted(vars(mod).items()):
            if isinstance(v, tuple) and _is_seq(list(v)):
                v = list(v)
            if _is_seq(v):
                out[f'ps/{name}.{k}'] = v
            elif isinstance(v, tuple) and v and all(isinstance(x, bytes) for x in v):     # 原始 exe 字节码 (fenshen_seqs)
                for i, x in enumerate(v):
                    out[f'ps/{name}.{k}/{i}'] = x
            elif isinstance(v, (list, tuple)) and v and all(_is_seq(list(x)) if isinstance(x, (list, tuple)) else False for x in v):
                for i, x in enumerate(v):
                    out[f'ps/{name}.{k}/{i}'] = list(x)
            elif isinstance(v, dict) and v and all(_is_seq(x) for x in v.values()):
                for kk, x in v.items():
                    out[f'ps/{name}.{k}/{kk}'] = x
    return out


def export_seqs() -> dict:
    """动画 seq 预编码成字节码 (hex): na/<表>/<方向> 普攻, em/<表>/<方向> 敌招 DOIT, sp/... 敌招演出模块常量."""
    from core.anim_engine.bytecode import tuple_to_bytecode
    return {k: (sq.hex() if isinstance(sq, bytes) else tuple_to_bytecode(sq).hex()) for k, sq in _all_seq_tuples().items()}


def export_seq_meta() -> dict:
    """每段 seq 的 IMPACT 数 (tuple 里 'impact' 或 jump -100) 与首个帧 op 前的 move tick 和 (exe 仍显示待机姿)."""
    out = {}
    for key, sq in _all_seq_tuples().items():
        if isinstance(sq, bytes):
            continue
        impacts = sum(1 for t in sq if t[0] == 'impact' or (t[0] == 'jump' and t[1] == -100))
        lead = 0
        for t in sq:
            if t[0] in ('fm', 'idle', 'fm_mode1'):
                break
            if t[0] == 'move':
                lead += t[-1]
        hold = any(t[0] in ('fm', 'fm_mode1', 'idle') for t in sq)
        out[key] = [max(1, impacts), lead, int(hold)]
    return out


def trace_cases() -> list:
    """普攻逐 tick 跟踪 (tools.skill_trace --attack N): 每个 DOIT 普攻项 × 4 朝向, 敌人站正前方一格.
    朝下的存全文 (失败时可看差异), 其余只存 md5."""
    import contextlib, hashlib, io
    from tools import skill_trace
    names = {g: n for n, g in NA.CHAR_GROUP.items()}
    out = []
    from core import ranged_attack as RA
    for idx, e in enumerate(ATTACK_ENTRIES):
        ranged = RA.handles(idx)
        if not ranged and (e[4] != 'doit' or e[5] is None):
            continue
        name = names.get(e[0], '孙悟空') if idx < 88 or idx > 90 else '紫河'
        for facing, (fx, fy) in skill_trace.FACING.items():
            text = None
            for dist in (range(1, 7) if ranged else (1,)):        # 远程: 敌人放在第一个能打到的距离
                dx, dy = fx * dist, fy * dist
                argv = ['skill_trace', '0', '--attack', str(idx), '--caster', name, '--facing', facing,
                        '--enemy-dx', str(dx), '--enemy-dy', str(dy)]
                buf = io.StringIO()
                old = sys.argv
                sys.argv = argv
                try:
                    with contextlib.redirect_stdout(buf):
                        skill_trace.main()
                except AssertionError:
                    continue
                finally:
                    sys.argv = old
                text = buf.getvalue()
                break
            if text is None:
                print(f'attack {idx} {facing}: no distance hits', file=sys.stderr)
                continue
            out.append({'fn': 'trace', 'units': [], 'rng_after': 0, 'seed': 0,
                        'args': {'caster': name, 'attack': idx, 'facing': facing, 'dx': dx, 'dy': dy},
                        'result': text if facing == 'down' else hashlib.md5(text.encode()).hexdigest()})
    return out


def enemy_trace_cases(unity: Path | None = None) -> list:
    """敌招逐 tick 跟踪 (tools.enemy_trace; 对己方招 tools.enemy_trace_ally --self 自疗): 每招 × 4 朝向, 我方目标站施法者正前方一格;
    施法敌人 = 第一个招式表含该招的敌种 (没有则 0). DOIT 类朝下的存全文, 其余只存 md5 (控制对照文件大小);
    全文另写到 <unity>/LocalOnly/tactics-traces/ (git 忽略, 测试失败时定位差异行)."""
    import contextlib, hashlib, io
    from tools import enemy_trace, enemy_trace_ally, skill_trace
    from core.enemy_move_data import MOVES
    owner = {}
    for t in range(CD.enemy_count()):
        e = CD.enemy(t)
        for mv in (e or {}).get('moves', []) or []:
            owner.setdefault(mv, t)
    local = unity / 'LocalOnly' / 'tactics-traces' if unity else None
    if local:
        local.mkdir(parents=True, exist_ok=True)
    out = []
    for mid, m in enumerate(MOVES):
        etype = owner.get(mid, 0)
        ally = (m[2] & 3) == 1
        for facing, (dx, dy) in skill_trace.FACING.items():
            argv = ['enemy_trace', str(mid), '--type', str(etype), '--facing', facing, '--targets', f'{dx},{dy}']
            if ally:
                argv.append('--self')
            buf = io.StringIO()
            old = sys.argv
            sys.argv = argv
            try:
                with contextlib.redirect_stdout(buf):
                    (enemy_trace_ally if ally else enemy_trace).main()
            finally:
                sys.argv = old
            text = buf.getvalue()
            if local:
                (local / f'enemy_{mid}_{facing}.txt').write_text(text)
            full = m[7] in ('doit', 'doit+hook') and facing == 'down'
            out.append({'fn': 'enemy_trace', 'units': [], 'rng_after': 0, 'seed': 0,
                        'args': {'move': mid, 'type': etype, 'facing': facing, 'targets': f'{dx},{dy}', 'self': ally},
                        'result': text if full else hashlib.md5(text.encode()).hexdigest()})
    return out


SKILL_OWNER = [(0x00, 0x09, '孙悟空'), (0x0a, 0x13, '美娜'), (0x14, 0x18, '三藏法师'), (0x19, 0x1d, '猪八戒'),
               (0x1e, 0x1f, '沙悟净'), (0x20, 0x24, '蒙面人'), (0x25, 0x2e, '乐神杰特'), (0x2f, 0x33, '破无'),
               (0x34, 0x38, '捕山'), (0x39, 0x41, '紫河')]


def skill_owner(sid: int) -> str:
    return next(n for lo, hi, n in SKILL_OWNER if lo <= sid <= hi)


def _skill_trace_candidates(sid: int, facing: str) -> list:
    """skill_trace 参数候选 (相对施法者): 对友方技能先试队友在正前方 (光标放队友), 再试自身; 对敌技能敌人在正前方 1..6 格; 地雷光标放空格."""
    from tools import skill_trace
    from core.skill_seq import is_heal_skill
    from core.skill_table import skill_targets_allies
    fx, fy = skill_trace.FACING[facing]
    ally = is_heal_skill(sid) or skill_targets_allies(sid)
    enemies = [['--enemy-dx', str(fx * d), '--enemy-dy', str(fy * d)] for d in range(1, 7)]
    if sid == 0x35:
        return [['--enemy-dx', str(fx * 3), '--enemy-dy', str(fy * 3), '--cursor-dx', str(fx), '--cursor-dy', str(fy)]]
    if ally:
        far = ['--enemy-dx', str(fx * 3), '--enemy-dy', str(fy * 3)]
        return ([far + ['--ally-dx', str(fx), '--ally-dy', str(fy), '--cursor-dx', str(fx), '--cursor-dy', str(fy)],
                 far + ['--ally-dx', '0', '--ally-dy', '0', '--cursor-dx', '0', '--cursor-dy', '0']] + enemies)
    return enemies


def skill_trace_cases(unity: Path | None = None) -> list:
    """玩家技能逐 tick 跟踪 (tools.skill_trace): 每技能 × 4 朝向, 施法者 = 技能所属角色, 参数取第一个能放出的候选.
    结果只存 md5, 全文写到 <unity>/LocalOnly/tactics-traces/skill_<sid>_<朝向>.txt (git 忽略, 失败时定位差异行)."""
    import contextlib, hashlib, io
    from tools import skill_trace
    local = unity / 'LocalOnly' / 'tactics-traces' if unity else None
    if local:
        local.mkdir(parents=True, exist_ok=True)
    out = []
    # (sid, 变体): '' = 默认候选; 'ally' = 队友在正前方 (召喚精靈 走回血精灵分支)
    plan = [(sid, '') for sid in range(0x42)] + [(0x13, 'ally')]
    for sid, variant in plan:
        name = skill_owner(sid)
        for facing in skill_trace.FACING:
            text = None
            cands = _skill_trace_candidates(sid, facing)
            if variant == 'ally':
                fx, fy = skill_trace.FACING[facing]
                cands = [['--enemy-dx', str(fx * 3), '--enemy-dy', str(fy * 3), '--ally-dx', str(fx), '--ally-dy', str(fy),
                          '--cursor-dx', str(fx), '--cursor-dy', str(fy)]]
            for extra in cands:
                argv = ['skill_trace', f'{sid:x}', '--caster', name, '--facing', facing, '--sg', '16'] + extra
                buf = io.StringIO()
                old = sys.argv
                sys.argv = argv
                try:
                    with contextlib.redirect_stdout(buf):
                        skill_trace.main()
                except AssertionError:
                    continue
                finally:
                    sys.argv = old
                text = buf.getvalue()
                break
            if text is None:
                print(f'skill {sid:#x} {facing}: no candidate casts', file=sys.stderr)
                continue
            tag = facing + (f'_{variant}' if variant else '')
            if local:
                (local / f'skill_{sid}_{tag}.txt').write_text(text)
            out.append({'fn': 'skill_trace', 'units': [], 'rng_after': 0, 'seed': 0,
                        'args': {'skill': sid, 'caster': name, 'facing': tag, 'argv': argv[2:]},
                        'result': hashlib.md5(text.encode()).hexdigest()})
    return out


def engine_cases() -> list:
    """引擎对照: 每段 seq 单独挂在一个实体上逐 tick 推进, 记录实体状态 + 信号/音效/位移事件."""
    from core.anim_engine.engine import Engine
    out = []
    seqs = export_seqs()
    for name in sorted(seqs):
        eng = Engine()
        ev = []
        eng.on('signal', lambda e, sg: ev.append(['sig', sg]))
        eng.on('sound_play', lambda e, sd: ev.append(['snd', sd]))
        eng.on('sound_stop', lambda e, sd: ev.append(['stop', sd]))
        eng.on('move', lambda e, dx, dy, dz, t: ev.append(['mv', dx, dy, dz, t]))
        e = eng.spawn()
        eng.attach_seq(e, bytes.fromhex(seqs[name]))
        rows = []
        for t in range(120):
            rows.append([e.flags, e.x, e.y, e.z, e.atlas_slot, e.frame_idx, e.ticks, e.offset, eng.swing_sound, ev[:]])
            ev.clear()
            if not e.is_playing():
                break
            eng.tick()
        out.append({'fn': 'engine', 'units': [], 'args': {'seq': name}, 'result': rows, 'rng_after': 0, 'seed': 0})
    return out


# ---------------- 黄金样本 ----------------
def snap(u) -> dict:
    d = {k: getattr(u, k) for k in UNIT_FIELDS}
    d['facing'] = list(u.facing)
    d['equipment'] = list(u.equipment)
    d['status_turns'] = {str(k): v for k, v in u.status_turns.items()}
    d['known_skills'] = list(u.known_skills)
    d['enemy_moves'] = list(u.enemy_moves)
    d['move_weights'] = list(u.move_weights)
    d['zihe_transformed'] = bool(u.zihe and u.zihe.get('transformed'))
    return d


class Gen:
    def __init__(self, seed: int):
        self.r = random.Random(seed)
        self.equip_by_slot: dict[int, list[int]] = {}
        for i in range(400):
            if is_equippable(i):
                self.equip_by_slot.setdefault(item_slot_mask(i), []).append(i)
        self.all_equip = [i for v in self.equip_by_slot.values() for i in v]
        self.enemy_types = [t for t in range(CD.enemy_count()) if CD.enemy(t)]

    def character(self, name: str | None = None):
        name = name or self.r.choice(PLAYERS)
        ch = CD.make_character(name)
        lv = self.r.choice((1, 5, 12, 25, 40, 60, 99))
        for L in range(ch.Level + 1, lv + 1):
            CD.level_up(ch, name, L)
        for slot in ('Head', 'Body', 'Hand', 'Accessories1', 'Accessories2'):
            if self.r.random() < 0.6:
                setattr(ch, slot, self.r.choice(self.all_equip))
        if self.r.random() < 0.3:          # 关注装备: 脱皮盾 / 丝巾 / 血盾 / 黄金苹果 / 坏手表 / 那印克星 / 紫河套装
            setattr(ch, self.r.choice(('Accessories1', 'Accessories2')),
                    self.r.choice((0xfa, 0xfb, 0x145, 0xf4, 0xe1, 0x146, 0x15c, 0x129, 0x12a, 0x144)))
        ch.Agile = CD.agile_with_equipment(ch)
        ch.SG = self.r.choice((0, 3, 9, 16, 0xFFFFFFFF))
        ch.Unknow_1 = self.r.randrange(30)
        ch.CurrentHP = self.r.randint(1, ch.MaxHP)
        ch.CurrentMP = self.r.randint(0, ch.MaxMP)
        return name, ch

    def player(self):
        name, ch = self.character()
        u = unit_from_character(name, ch)
        self.place(u)
        return u

    def enemy(self):
        u = make_enemy_by_type(self.r.choice(self.enemy_types))
        self.place(u)
        if self.r.random() < 0.3:
            u.hp = self.r.randint(1, u.max_hp)
        return u

    def place(self, u):
        u.x, u.y = self.r.randint(0, 12), self.r.randint(0, 12)
        u.facing = self.r.choice(((0, -1), (0, 1), (-1, 0), (1, 0)))
        bits = 0
        for b in (0x100, 0x200, 0x400, 0x800, 0x1000, 0x2000, 0x4000, 0x8000, 0x10000, 0x20000, 0x80000):
            if self.r.random() < 0.06:
                bits |= b
                u.status_turns[b] = self.r.randint(0, 3)
        u.status_bits = bits
        if self.r.random() < 0.05:
            u.hp = 0

    def adjacent(self, att, dfn):
        """一半用例让守方站攻方正前方 (反击/方位分支)."""
        if self.r.random() < 0.5:
            dfn.x, dfn.y = att.x + att.facing[0], att.y + att.facing[1]


def rng(seed: int) -> SimpleNamespace:
    return SimpleNamespace(rng=ExeRng(seed), _log=lambda *_: None, players=[], enemies=[])


def golden(n: int = 400, unity: Path | None = None) -> dict:
    g = Gen(20261027)
    cases: list = []
    attack_skills = [s for s, v in SKILL_TABLE.items() if v[0] & 1 and not v[0] & 0x0f000000]
    heal_skills = [s for s, v in SKILL_TABLE.items() if v[0] & 0x40 and not v[0] & 1]
    for i in range(n):
        seed = g.r.randrange(1 << 31)
        p, e = g.player(), g.enemy()
        g.adjacent(p, e)
        pre = [snap(p), snap(e)]

        def add(fn, battle, units, args, result):
            cases.append({'fn': fn, 'units': pre if units is None else units, 'args': args, 'result': result,
                          'rng_after': battle.rng.state, 'seed': seed})

        def outcome(o):
            return [int(o.hit), int(o.crit), o.dmg, int(o.magic), o.reflect, o.dir, o.status_chance, o.roll]

        b = rng(seed)
        idx = g.r.choice([a for a in (p.attack_normal, p.attack_melee) if a is not None] or [0])
        fl = NA.entry(idx).flags
        fo = g.r.choice((8, 8, 8, 4, 6, 12))
        add('player_normal', b, None, {'entry_flags': fl, 'falloff': fo}, outcome(F.player_normal(b, p, e, fl, fo)))
        b = rng(seed)
        sid = g.r.choice(attack_skills)
        add('player_skill', b, None, {'sid': sid, 'falloff': fo}, outcome(F.player_skill(b, p, e, sid, fo)))
        b = rng(seed)
        mv = g.r.choice(e.enemy_moves + [None]) if e.enemy_moves else None
        o = F.enemy_attack(b, e, p, mv, fo)
        add('enemy_attack', b, [pre[1], pre[0]], {'move': -1 if mv is None else mv, 'falloff': fo}, outcome(o))
        b = rng(seed)
        cc = F.counter_check(e, p, o, F.enemy_move(mv)['flags'] if mv is not None else F.F_DEFAULT_ENEMY)
        add('counter_check', b, [pre[1], pre[0]], {'outcome': outcome(o),
                                                   'flags': F.enemy_move(mv)['flags'] if mv is not None else F.F_DEFAULT_ENEMY},
            int(cc))
        b = rng(seed)
        b._weapon27_idx = g.r.randrange(4)
        w0 = b._weapon27_idx
        dmg, crit = F.counter_damage(b, p, e)
        add('counter_damage', b, None, {'weapon27': w0}, [dmg, int(crit), b._weapon27_idx])
        b = rng(seed)
        dmg, crit = F.counter_damage(b, e, p)
        add('counter_damage', b, [pre[1], pre[0]], {'weapon27': 0}, [dmg, int(crit), 0])
        b = rng(seed)
        hs = g.r.choice(heal_skills)
        add('heal_amount', b, None, {'sid': hs, 'falloff': fo}, F.heal_amount(b, p, hs, fo))
        b = rng(seed)
        t = g.player()
        tpre = snap(t)
        revived, amt = F.skill_restore(b, p, t, hs, fo)
        add('skill_restore', b, [pre[0], tpre], {'sid': hs, 'falloff': fo}, [int(revived), amt, t.hp])
        b = rng(seed)
        ds = g.r.choice((0x3b, 0x3d))
        add('mp_drain', b, None, {'sid': ds, 'falloff': fo}, F.mp_drain(b, p, e, ds, fo))
        ss = g.r.choice((0x10, 0x25))
        add('seal_chance', rng(seed), None, {'sid': ss}, F.seal_chance(p, e, ss))
        add('dir_index', rng(seed), None, {}, F.dir_index(p, e))
        add('affinity', rng(seed), None, {}, F.affinity(p, e))
        # 敌招非伤害类
        m = enemy_move(g.r.randrange(len(MOVES)))
        add('status_chance', rng(seed), [pre[1], pre[0]], {'move': m.idx}, status_chance(e, p, m))
        b = rng(seed)
        p2 = g.player()
        p2pre = snap(p2)
        got = resolve_status(b, e, p2, m)
        add('resolve_status', b, [pre[1], p2pre], {'move': m.idx}, [got, p2.status_bits, {str(k): v for k, v in p2.status_turns.items()}])
        b = rng(seed)
        add('enemy_heal_amount', b, [pre[1]], {'move': m.idx, 'falloff': fo}, enemy_heal_amount(b, e, m, fo))
        # 普攻附带异常
        b = rng(seed)
        e2 = g.enemy()
        e2pre = snap(e2)
        p.pending_skill_id = g.r.choice((None, None, g.r.choice(list(SKILL_TABLE))))
        p.attack_cur = idx
        chance = g.r.choice((23, 10))
        got = NA.roll_status(b, p, e2, chance)
        add('roll_status', b, [pre[0], e2pre], {'skill': -1 if p.pending_skill_id is None else p.pending_skill_id,
                                                 'attack': idx, 'chance': chance}, [got or 0, e2.status_bits])
        p.pending_skill_id = None
        # 能量
        sk = g.r.choice(list(SKILL_TABLE))
        add('energy', rng(seed), None, {'sid': sk},
            [energy.energy_type(p), int(energy.uses_sg(p)), energy.mp_cost(p, sk), energy.sg_threshold(p, sk),
             int(energy.can_cast(p, sk))])
        q = g.player()
        qpre = snap(q)
        energy.pay(q, sk)
        add('energy_pay', rng(seed), [qpre], {'sid': sk}, [q.mp, q.sg])
        b = rng(seed)
        it = g.r.choice(energy.HP_ITEMS + energy.MP_ITEMS + energy.REVIVE_ITEMS + (energy.ITEM_SG_FULL,))
        q = g.player()
        qpre = snap(q)
        r = energy.battle_item(b, p, q, it, fo)
        add('battle_item', b, [pre[0], qpre], {'item': it, 'falloff': fo},
            [r.get('hp', -1), r.get('mp', -1), r.get('sg', -1), int(r.get('revived', False)), q.hp, q.mp, q.sg])
        # 普攻表
        name, ch = g.character()
        weapon = None if ch.Hand in (0xFFFFFFFF, -1) else ch.Hand
        acc = [a for a in (ch.Accessories1, ch.Accessories2) if a not in (0xFFFFFFFF, -1)]
        a1, a2 = NA.attack_ids(name, weapon, acc)
        add('attack_ids', rng(seed), [], {'name': name, 'weapon': -1 if weapon is None else weapon, 'acc': acc},
            [-1 if a1 is None else a1, -1 if a2 is None else a2])
        if i % 4 == 0:
            cases.extend(turn_case(g, seed))
            cases.extend(ai_case(g, seed))
            cases.extend(settle_case(g, seed))
            cases.extend(setup_case(g))
    cases.extend(engine_cases())
    cases.extend(trace_cases())
    cases.extend(enemy_trace_cases(unity))
    cases.extend(skill_trace_cases(unity))
    return {'cases': cases}


def turn_case(g: Gen, seed: int) -> list:
    """行动顺序: 起回合 (状态递减 → SG → 行动值) + 连续挑人 12 次 (= TacticsBattle._start_round/_pick_next)."""
    tb = object.__new__(TacticsBattle)
    tb.players = [g.player() for _ in range(g.r.randint(1, 3))]
    tb.enemies = [g.enemy() for _ in range(g.r.randint(1, 4))]
    tb.rng = ExeRng(seed)
    pre = [snap(u) for u in tb.players + tb.enemies]
    picks = []
    for _ in range(12):
        u = tb._pick_next()
        if u is None:
            status.round_tick(tb.players + tb.enemies)
            energy.round_start(tb)
            for x in tb.players + tb.enemies:
                if not x.is_player and not tb._can_act(x):
                    x.action_value = 0
                x.action_value += tb._action_gain(x)
            picks.append(-1)
            continue
        picks.append((tb.players + tb.enemies).index(u))
    post = [[u.action_value, u.sg, u.status_bits] for u in tb.players + tb.enemies]
    return [{'fn': 'turns', 'units': pre, 'args': {'players': len(tb.players)}, 'result': [picks, post],
             'rng_after': tb.rng.state, 'seed': seed}]


def ai_case(g: Gen, seed: int) -> list:
    """敌方 AI 连续两轮 (ai_exe.take_turn): 每次行动后记录站位/朝向/路径/待出招 + 跨调用残留的全局表."""
    from core.battle.data import BattleMap
    from core.battle.queries import BattleQueries
    tb = object.__new__(TacticsBattle)
    w, h = g.r.randint(10, 16), g.r.randint(8, 14)
    m = BattleMap(w, h)
    for _ in range(g.r.randint(0, 14)):
        m.obstacles.add((g.r.randrange(w), g.r.randrange(h)))
    tb.map = m
    tb.players = [g.player() for _ in range(g.r.randint(1, 4))]
    tb.enemies = [g.enemy() for _ in range(g.r.randint(1, 5))]
    special = [t for t in g.enemy_types if any(enemy_move(mv).category == 2 or mv == 2 for mv in CD.enemy(t).get('moves', [])
                                              if 0 <= mv < len(MOVES))]
    for _ in range(g.r.randint(0, 2)):          # 偏置: 带回复/召唤招的敌人 (覆盖 FUN_004b0532 / 召唤分支)
        u = make_enemy_by_type(g.r.choice(special))
        g.place(u)
        tb.enemies.append(u)
    taken = set()
    for u in tb.players + tb.enemies:
        while True:
            c = (g.r.randrange(w), g.r.randrange(h))
            if c not in taken and c not in m.obstacles:
                break
        taken.add(c)
        u.x, u.y = c
        if not u.is_player and g.r.random() < 0.4:
            u.hp = g.r.randint(1, u.max_hp)            # 受伤 → 回复招分支
        if not u.is_player and g.r.random() < 0.2:
            u.status_bits |= 0x400                      # 沉默
    tb.q = BattleQueries(m, tb.players, tb.enemies)
    tb.rng = ExeRng(seed)
    tb._log = lambda *_: None
    pre = [snap(u) for u in tb.players + tb.enemies]
    steps = []
    for _ in range(2):
        for e in tb.enemies:
            if not e.alive:
                continue
            for k in ('_pending_enemy_attack', '_pending_enemy_skill', '_pending_enemy_move', '_pending_enemy_cursor',
                      '_pending_damage_range', '_pending_damage_falloff'):
                setattr(tb, k, None)
            e.move_path, e.post_move_facing = [], None
            ai_exe.take_turn(tb, e)
            all_u = tb.players + tb.enemies
            pa = tb._pending_enemy_attack
            steps.append([
                [e.x, e.y, e.facing[0], e.facing[1]], [list(c) for c in e.move_path],
                None if e.post_move_facing is None else list(e.post_move_facing), getattr(e, 'summon_cd', 0),
                -1 if pa is None else all_u.index(pa), -1 if tb._pending_enemy_move is None else tb._pending_enemy_move,
                None if tb._pending_enemy_cursor is None else list(tb._pending_enemy_cursor),
                None if tb._pending_damage_range is None else sorted(list(c) for c in tb._pending_damage_range),
                None if tb._pending_damage_falloff is None else sorted([c[0], c[1], v] for c, v in tb._pending_damage_falloff.items()),
                [list(c) for c in tb._ai_stand], [list(x) for x in tb._ai_ent], tb.rng.state])
    return [{'fn': 'ai', 'units': pre, 'args': {'players': len(tb.players), 'w': w, 'h': h, 'obstacles': sorted(list(c) for c in m.obstacles)},
             'result': steps, 'rng_after': tb.rng.state, 'seed': seed}]


def settle_case(g: Gen, seed: int) -> list:
    b = SimpleNamespace(rng=ExeRng(seed), players=[], enemies=[g.enemy() for _ in range(g.r.randint(1, 5))],
                        level_ups=[], exp_receiver=None)
    for e in b.enemies:
        if g.r.random() < 0.5 and e.drop_item >= 0:
            e.drop_rate = g.r.choice((0, 300, 999, 1000))
    chars = []
    for _ in range(g.r.randint(1, 3)):
        name, ch = g.character()
        u = unit_from_character(name, ch)
        g.place(u)
        b.players.append(u)
        chars.append([ch.Level, ch.Exp, ch.nextExp])
    if g.r.random() < 0.3:
        b.exp_receiver = g.r.choice(b.players)
    pre = [snap(u) for u in b.players + b.enemies]
    recv = -1 if b.exp_receiver is None else b.players.index(b.exp_receiver)
    settlement.rewards(b)
    scale = g.r.choice((1, 1, 30, 400))
    b.exp_gained = b.exp_gained * scale                               # 放大经验, 覆盖升级分支
    settlement.distribute_exp(b)
    post = [[u.level, u.max_hp, u.max_mp, u.attack, u.defence, u.hp, u.mp, u.save_ref.Exp, u.save_ref.nextExp,
             list(u.known_skills)] for u in b.players]
    return [{'fn': 'settle', 'units': pre, 'args': {'players': len(b.players), 'receiver': recv, 'chars': chars,
                                                    'exp_scale': scale},
             'result': [b.exp_gained, b.money_gained, [list(d) for d in b.drops], post],
             'rng_after': b.rng.state, 'seed': seed}]


def setup_case(g: Gen) -> list:
    """建角色 (初始 + 升级到 L) + 装备 → 战斗单位; 敌人类型 → 战斗单位."""
    out = []
    name, ch = g.character()
    u = unit_from_character(name, ch)
    out.append({'fn': 'setup_player', 'units': [], 'result': snap(u), 'rng_after': 0, 'seed': 0,
                'args': {'name': name, 'level': ch.Level, 'equip': [ch.Head, ch.Body, ch.Hand, ch.Accessories1, ch.Accessories2],
                         'hp': ch.CurrentHP, 'mp': ch.CurrentMP, 'sg': ch.SG, 'action': ch.Unknow_1,
                         'save': {k: getattr(ch, k) for k in ('MaxHP', 'MaxMP', 'Exp', 'nextExp', 'Unknow_5', 'Unknow_6',
                                                               'Agile', 'Luck', 'Wisdom', 'Unknow_9', 'Attack', 'Defence')}}})
    t = g.r.choice(g.enemy_types)
    out.append({'fn': 'setup_enemy', 'units': [], 'args': {'type': t}, 'result': snap(make_enemy_by_type(t)),
                'rng_after': 0, 'seed': 0})
    return out


def intern_units(gold: dict) -> dict:
    """单位快照去重: cases[i].units 改成 units 池下标 (setup 用例的 result 照旧内联)."""
    pool, seen = [], {}
    for c in gold['cases']:
        ids = []
        for u in c['units']:
            k = json.dumps(u, sort_keys=True, ensure_ascii=False)
            if k not in seen:
                seen[k] = len(pool)
                pool.append(u)
            ids.append(seen[k])
        c['units'] = ids
    return {'units': pool, 'cases': gold['cases']}


def main(argv: list[str]) -> None:
    unity = Path(argv[1]) if len(argv) > 1 else ROOT.parent / 'flyingsb-unity'
    data_p = unity / 'Assets/FlyingSb/Resources/Tactics/TacticsData.json'
    gold_p = unity / 'Assets/FlyingSb/Tests/EditMode/Golden/tactics_golden.json'
    data_p.parent.mkdir(parents=True, exist_ok=True)
    gold_p.parent.mkdir(parents=True, exist_ok=True)
    data_p.write_text(json.dumps(export_data(), ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
    gold = intern_units(golden(240, unity))
    gold_p.write_text(json.dumps(gold, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
    print(f'{data_p} {data_p.stat().st_size}B\n{gold_p} {gold_p.stat().st_size}B, {len(gold["cases"])} cases')


if __name__ == '__main__':
    main(sys.argv)
