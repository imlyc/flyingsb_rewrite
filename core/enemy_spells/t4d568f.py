"""模板 FUN_004d568f (4 招 回复己方: 17/72/191 高回生術, 140 使用指輝棒), reverse_engineering/enemy_spells_decomp.txt.
= 玩家 美娜 大恢復 (core.mina_skills._spawn_bigheal, 已实录校准); 光点 think 照抄改结算.

dispatcher: 渐暗 → 施法 seq → -100: 每目标: (+4 & 0x100 才) 挂接受姿 655aa8[目标朝向], 清 0x10000;
  FUN_004d554c 4 个 ds_mag03 光点 (seq 6561a4, 绕目标 rx 32 ry 24 mode 0x32, 相位 rand&0x3ff<<6 起每个 +0x4000, 末个标 0x40000);
  +0x78 计数; 全部目标后 0xc9.
  光点 think FUN_004d529a: z 每 t +1 螺旋上升 (角速 +0x20 到 0x1000), 偶数 t 撒上升粒子 FUN_004d4819; z>96 → 半径每 t -1;
  收到 0 → 末个 -200; 再半径 +10,+20.. 外扩 (每 t 撒粒子), >599 → 末个 -250 自毁.
  -200: 首目标 0xca; 目标回待机 (|= 0x10000) + 回血白字, +0x7a.  (无羽毛)
  -250: +0x78--.  0x1e: 计数归零 + 飘字完 → 0x28 渐亮.
近似: 接受姿只给玩家方单位挂 (exe 看单位 +4 & 0x100).
"""
from __future__ import annotations

from core.enemy_spells.base import Spell, fx, FP, _pos, _rand, _sfx, _set_z, _c3211, _motion, _getz
from core import jet_skills as J
from core.jet_skills import MAG_SEQ
from core.enemy_spells.t4d4ee0 import hold_pose, heal_settle


def _dot_think(e, eng) -> None:
    """FUN_004d529a (= mina_skills._bigheal_think, 结算换成 Spell)."""
    ud = e.user_data
    if 'bigheal' not in ud:
        return
    sp: BigHeal = ud['spell']
    st = ud['state']
    if st == 0:
        _set_z(e, _getz(e) + FP)
        ud['spd'] = min(ud['spd'] + 0x20, 0x1000)
        ud['py'] = (ud['py'] + ud['spd']) & 0xffff
        ud['px'] = ud['py']
        _c3211(e)
        if ud['age'] % 2 == 0:
            J._spawn_rise(sp.battle, e)
        if _getz(e) > 0x600000:
            ud['state'] = 10
    elif st == 10:
        ud['py'] = (ud['py'] + ud['spd']) & 0xffff
        ud['px'] = ud['py']
        ud['rx'] = ud['ry']
        ud['ry'] -= 1
        _c3211(e)
        if ud['rx'] < 1:
            if ud['lead']:
                if ud['first']:
                    _sfx(sp.battle, 0xca)
                heal_settle(sp, ud['target'], feathers=False)
            ud['rz'] = 0
            ud['state'] = 20
    else:
        ud['rz'] += 10
        ud['ry'] += ud['rz']
        ud['rx'] = ud['ry']
        _c3211(e)
        J._spawn_rise(sp.battle, e)
        if ud['rx'] > 599:
            if ud['lead']:
                sp.on_lead_done()
            eng.destroy(e)
            return
    ud['age'] += 1


class BigHeal(Spell):
    def on_cast_impact(self) -> None:
        b = self.battle
        for i, t in enumerate(self.targets):
            hold_pose(self, t)
            cx, cy = _pos(t)
            phi = ((_rand(b) & 0x3ff) << 16) >> 10
            for k in range(4):
                e = fx(b, _dot_think, cx, cy, 0, MAG_SEQ, bigheal=True, spell=self, target=t, state=0, age=0,
                       spd=0x400, lead=(k == 3), first=(i == 0),
                       **_motion(m=0x32, tx=cx, ty=cy, rx=0x20, ry=0x18, px=phi, py=phi))
                _c3211(e)
                phi = (phi + 0x4000) & 0xffff
            self.live += 1
        _sfx(b, 0xc9)
        if not self.targets:
            self.finish()

    def on_lead_done(self) -> None:
        self.live -= 1
        if self.live <= 0:
            self.finish()


TEMPLATES = {0x4d568f: BigHeal}
