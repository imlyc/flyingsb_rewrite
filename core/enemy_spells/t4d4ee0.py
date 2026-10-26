"""模板 FUN_004d4ee0 (3 招 回复己方: 95/220/226 使用小回生術), reverse_engineering/enemy_spells_decomp.txt.
= 玩家 乐神杰特 恢復樂章 / 美娜 小回復 (core.jet_skills._spawn_heal_pillars, 已实录校准); 光柱 think 照抄改结算, 粒子/羽毛复用.

dispatcher: 渐暗 → 施法 seq → -100: 每目标: (+4 & 0x100 才) 挂接受姿 655aa8[目标朝向], 清 0x10000;
  FUN_004d4d93 3 道 ds_mag03 光柱 (绕目标 rx 32 ry 24, 相位 rand&0x3ff<<6 起每道 +0x5555, 0xc9); +0x78 计数.
  光柱 think FUN_004d4acf: z 每 t +1 螺旋上升 (角速 +0x20 到 0x1000), 偶数 t 撒上升粒子 (FUN_004d4819); z>96 → 半径每 t -1;
  收到 0 → 首道 (0x40000) -200 (0xca); 再半径 +10,+20.. 外扩, >599 → 首道 -250 自毁.
  -200: 目标回待机 (|= 0x10000) + 回血白字 (FUN_004d074e) + 32 片羽毛 (FUN_004d498c), +0x7a.
  -250: +0x78--.  0x1e: 计数归零 + 飘字完 → 0x28 渐亮.
近似: 接受姿只给玩家方单位挂 (exe 看单位 +4 & 0x100, 同 core.mina_skills 大恢復的处理).
实录校准 (wine/captures/en95_t58_F5542.log, 施法者自疗): 光柱 (+20, 寿命 133, state 0×97 10×25 20×11)、上升粒子
  (+23 起每 2 t, 出生当 tick 即 think — +21 那批出生即落地自毁, 实录看不到)、羽毛 (出生即 think)、白字 (+142)、
  渐亮起点 (+199 = 末位白字 -20 的下一 tick) 吻合. 粒子/羽毛按实录出生即 think (exe 池序: 下标在光柱之后).
"""
from __future__ import annotations

from core.enemy_spells.base import Spell, fx, FP, _pos, _rand, _sfx, _set_z
from core import jet_skills as J
from core.jet_skills import MAG_SEQ, FEATHER_SEQS, HEAL_POSE_SEQS


def spawn_rise(b, src) -> None:
    """FUN_004d4819 (= jet_skills._spawn_rise), 实录 (en95/en17): 粒子出生当 tick 即 think."""
    vx = 0x4000 // ((_rand(b) & 3) + 1)
    vy = 0x4000 // ((_rand(b) & 3) + 1)
    e = fx(b, J._rise_think, src.x, src.y, src.user_data['ez'], FEATHER_SEQS[_rand(b) & 3], rise=True,
           vx=vx, vy=vy, vz=-2 * FP, az=0, age=0)
    J._rise_think(e, b.engine)


class HealFinish:
    """回复类收尾 (混入 Spell 子类前): 实录 en17/en95/en36 末位白字 -20 的下一 tick 就渐亮 (白字与 exe 同 tick 落定,
    不需要框架为红字多等的那 1 tick); 施法者自疗时 -200 已回待机, 收尾不再显示施法末帧."""

    def _finish_tick(self) -> None:
        if self._fade is None and not self.busy():
            self._quiet = max(self._quiet, 1)
        super()._finish_tick()

    def _end(self) -> None:
        super()._end()
        c = self.caster
        if c in self.targets and c.entity is not None:
            c.entity.user_data.pop('hold_until_tick', None)


def hold_pose(sp: Spell, t) -> None:
    """-100: 接受姿 655aa8[朝向] (保持到 -200)."""
    if t.is_player and t.alive:
        J._hold_pose(sp.battle, t, HEAL_POSE_SEQS)


def heal_settle(sp: Spell, t, feathers: bool) -> None:
    """-200: 回待机 + 白字 (Spell.settle 类别 2) (+ FUN_004d498c 32 片羽毛)."""
    J._release_pose(t)
    sp.settle(t)
    if not feathers:
        return
    b = sp.battle
    x, y = _pos(t)
    for _ in range(32):
        vx = ((_rand(b) & 31) - 16) * FP >> 4
        vy = ((_rand(b) & 31) - 16) * FP >> 4
        vz = ((_rand(b) & 63) * FP) >> 4
        e = fx(b, J._feather_think, x, y, 128 * FP, FEATHER_SEQS[_rand(b) & 3], feather=True, vx=vx, vy=vy,
               vz=vz, az=0x8000, age=0)
        J._feather_think(e, b.engine)            # 实录 en95: 羽毛出生当 tick 即 think (首帧 z≠128)


def _pillar_think(e, eng) -> None:
    """FUN_004d4acf (= jet_skills._pillar_think, 结算换成 Spell)."""
    ud = e.user_data
    if 'pillar' not in ud:
        return
    sp: HealPillars = ud['spell']
    st = ud['state']
    if st == 0:
        _set_z(e, ud['ez'] + FP)
        ud['spd'] = min(ud['spd'] + 0x20, 0x1000)
        ud['phi'] = (ud['phi'] + ud['spd']) & 0xffff
        J._orbit(e)
        if ud['age'] % 2 == 0:
            spawn_rise(sp.battle, e)
        if ud['ez'] > 0x600000:
            ud['state'] = e.state_code = 10
    elif st == 10:
        ud['phi'] = (ud['phi'] + ud['spd']) & 0xffff
        ud['rx'] = ud['ry']
        ud['ry'] -= 1
        J._orbit(e)
        if ud['rx'] < 1:
            if ud.get('lead'):
                heal_settle(sp, ud['target'], feathers=True)
                _sfx(sp.battle, 0xca)
            ud['grow'] = 0
            ud['state'] = e.state_code = 20
    else:
        ud['grow'] += 10
        ud['ry'] += ud['grow']
        ud['rx'] = ud['ry']
        J._orbit(e)
        if ud['rx'] > 599:
            if ud.get('lead'):
                sp.on_lead_done()               # -250
            eng.destroy(e)
            return
    ud['age'] += 1


class HealPillars(HealFinish, Spell):
    def on_cast_impact(self) -> None:
        b = self.battle
        for t in self.targets:
            hold_pose(self, t)
            cx, cy = _pos(t)
            phi = ((_rand(b) & 0x3ff) << 16) >> 10
            for k in range(3):
                e = fx(b, _pillar_think, cx, cy, 0, MAG_SEQ, pillar=True, spell=self, target=t,
                       cx=cx, cy=cy, rx=0x20, ry=0x18, phi=phi & 0xffff, spd=0x400, state=0, age=0, lead=(k == 2))
                J._orbit(e)
                phi += 0x5555
            _sfx(b, 0xc9)
            self.live += 1
        if not self.targets:
            self.finish()

    def on_lead_done(self) -> None:
        self.live -= 1
        if self.live <= 0:
            self.finish()


TEMPLATES = {0x4d4ee0: HealPillars}
