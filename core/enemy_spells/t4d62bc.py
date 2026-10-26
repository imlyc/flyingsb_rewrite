"""模板 FUN_004d62bc (2 招 回复己方: 36 使用伊巴魯諾, 40 使出超回生術), reverse_engineering/enemy_spells_decomp.txt.
= 玩家 乐神杰特 回復優卡 / 美娜 超回復 (core.jet_skills._spawn_yuka, 已实录校准); 控制体照抄改结算, 光圈复用 J._yuka_rings.

dispatcher: 渐暗 → 施法 seq → -100: 每目标一个控制体 FUN_004d6299 (think FUN_004d5f4b), +0x78 计数.
  控制体: case 0 (+4 & 0x100 才) 挂接受姿 655aa8, 清 0x10000; 目标 flags 0x41 z 弹簧 (目标 z+48, vz +1px) → case 10 升到 z>0x2fffff:
          az 0x1999, 首目标 0xc9 → case 0x14 5t 每 t 8 个 ds_mag03 光圈 (FUN_004d5cd5) → 0x19 (停一拍) → 0x1e 120t 弹簧浮动 →
          目标 z 0, vz -1px, az 0, DAT_0086a768=1 (光圈散) + -200 + -250 (首目标 0xca) → 0x28 落到 z<0 → 目标回待机, 自毁.
  -200: 回血白字 (+0x7a).  -250: +0x78--.  0x1e: 计数归零 + 飘字完 → 0x28 渐亮.
近似: 接受姿只给玩家方单位挂 (exe 看单位 +4 & 0x100); 目标落地后 z 归 0 (exe 停在 -0.99px 到回合结束).
"""
from __future__ import annotations

from core.enemy_spells.base import Spell, FP, _sfx
from core import jet_skills as J
from core.enemy_spells.t4d4ee0 import hold_pose


def _ctrl_think(e, eng) -> None:
    """FUN_004d5f4b (= jet_skills._yuka_think, 结算换成 Spell)."""
    ud = e.user_data
    if 'yuka' not in ud:
        return
    sp: Yuka = ud['spell']
    b, t = sp.battle, ud['target']
    st = ud['state']
    age = ud['age']
    ent = t.entity
    if st == 0:
        hold_pose(sp, t)
        ud.update(tz=48 * FP, vz=FP, az=0, uz=0, state=10)
    elif st == 10:
        ud['vz'] += ud['az'] if ud['uz'] < ud['tz'] else -ud['az']
        ud['uz'] += ud['vz']
        if ud['uz'] > 0x2fffff:
            ud.update(az=0x1999, n=0, until=age + 5, state=20)
            if ud['first']:
                _sfx(b, 0xc9)
    elif st == 20:
        J._yuka_rings(b, t, ud['n'], 5, ud)
        ud['n'] += 1
        ud['vz'] += ud['az'] if ud['uz'] < ud['tz'] else -ud['az']
        ud['uz'] += ud['vz']
        if age == ud['until']:
            ud.update(until=age + 0x78, state=25)
    elif st == 25:
        ud['state'] = 30
    elif st == 30:
        ud['vz'] += ud['az'] if ud['uz'] < ud['tz'] else -ud['az']
        ud['uz'] += ud['vz']
        if age == ud['until']:
            ud.update(tz=0, vz=-FP, az=0, state=40)
            ud['release'] = True                            # DAT_0086a768 = 1
            sp.settle(t)                                    # -200 白字 (接受姿保持到落地)
            if ud['first']:
                _sfx(b, 0xca)
    else:
        ud['uz'] += ud['vz']
        if ud['uz'] < 0:
            if ent is not None:
                ent.z = 0
            J._release_pose(t)
            sp.on_ctrl_done()                               # -250 计数 (等落地再收尾)
            eng.destroy(e)
            return
    if ent is not None:
        ent.z = -ud['uz']
    ud['age'] += 1


class Yuka(Spell):
    def on_cast_impact(self) -> None:
        for i, t in enumerate(self.targets):
            e = self.battle.engine.spawn(think_fn=_ctrl_think)
            e.flags = 0x800 | 0x10000
            e.user_data.update(kind='enemy_yuka', projectile=True, yuka=True, battle=self.battle, spell=self,
                               target=t, state=0, age=0, first=(i == 0))
            self.live += 1
        if not self.targets:
            self.finish()

    def on_ctrl_done(self) -> None:
        self.live -= 1
        if self.live <= 0:
            self.finish()


TEMPLATES = {0x4d62bc: Yuka}
