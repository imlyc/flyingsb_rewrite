"""模板 FUN_004d859f (2 招: 66 使用冰雪暴, 157 用冰雪暴攻擊), reverse_engineering/enemy_spells_decomp.txt
(+ 4d8207 补反编译; 碎冰 4d6dc3 见 icedragon_decomp.txt). 无玩家对应, 照反编译.

dispatcher: 渐暗 → 施法 seq → -100: 每目标一个发射器 FUN_004d8562 (think FUN_004d845c), +0x78 计数.
  发射器: age 4 起每 8t 一块冰 (FUN_004d838f) 共 16 块 (第 16 块标 0x40000 = 末块); 再 32t → DAT_0086a76c = 1 (全体落下), 自毁.
  冰块 FUN_004d838f: 目标 (x-32+(rand&63), y-24+rand%48, z 130+(rand&1)), seq 656c74 (ds_ice 3,2,1,0,5,6,7,4 各 1t), 0xee;
       flags 0x41 (z 轴弹簧) 目标 z 128.
  冰块 think FUN_004d8207: state 0 等 seq 播完 → 换 eice 帧 656cc8[rand&7] (4..7, 24..27), az 0x2000 → state 10:
       每 t FUN_004c3211 (z 绕 128 弹簧小幅浮动); DAT_0086a76c → 目标 z 0, vz -(24+rand&7) px/t, az 0 → state 20:
       匀速下落, z<1 → FUN_004d6dc3 4 片碎冰 + -250; 末块再 -200 + 0xae; 自毁.
  -250: 受击 6557f0[目标朝向] + 655c10[6418dc[目标朝向]] 刺爆 + 655b18 红刺 (= Spell.hit fx='both').
  -200: 飘字, +0x78--.  0x1e: 计数归零 + 飘字/受击完 → 0x28 渐亮.
实录校准 (wine/captures/en66_t32_F5456.log, 2 目标): 发射器 (+24, 寿命 165, state 0×125 10×40)、冰块出生 (+29 起每 8 t)、
  seq 16 t → state 10 → 落下 state 20 5~6 t、刺爆 tick、飘字出生 (+194)、渐亮起点 (+231) 逐 tick 吻合 (无需改动).
  碎冰 (son_transform 17 tick 版) 此实录 3/4 出生即 think (寿命 17) — 与 en21 相反, 池序效应, 不模拟.
"""
from __future__ import annotations

from core.enemy_spells.base import Spell, fx, FP, _pos, _rand, _sfx, _c3211, _motion, _getz

DS_ICE, EICE = 232, 300
CHUNK_SEQ = [('fm', DS_ICE, f, 1) for f in (3, 2, 1, 0, 5, 6, 7, 4)] + [('exit',)]          # 656c74
CHUNK_FRAMES = (4, 5, 6, 7, 24, 25, 26, 27)                                                # 656cc8
SFX_SPAWN, SFX_LAST = 0xee, 0xae
N_CHUNKS, INTERVAL, FIRST, DROP_DELAY = 16, 8, 4, 0x20


def _chunk_think(e, eng) -> None:
    """FUN_004d8207."""
    ud = e.user_data
    if 'chunk' not in ud:
        return
    sp: IceStorm = ud['spell']
    b = sp.battle
    st = ud['st']
    if st == 0:
        if not e.is_playing():
            e.seq = b''
            e.flags &= ~0x20000
            e.atlas_slot, e.frame_idx = EICE, CHUNK_FRAMES[_rand(b) & 7]
            ud['az'] = 0x2000
            ud['st'] = e.state_code = 10
    elif st == 10:
        _c3211(e)
        if sp.drop:
            ud['tz'] = 0
            ud['vz'] = -((_rand(b) & 7) * FP + 0x180000)
            ud['az'] = 0
            ud['st'] = e.state_code = 20
    else:
        _c3211(e)
        if _getz(e) < 1:
            from core.son_transform import _spawn_ice_shatter
            _spawn_ice_shatter(b, e.x, e.y, big=False)
            sp.on_chunk_land(ud['victim'], ud['last'])
            eng.destroy(e)


def _launcher_think(e, eng) -> None:
    """FUN_004d845c."""
    ud = e.user_data
    if 'launcher' not in ud:
        return
    sp: IceStorm = ud['spell']
    b, v = sp.battle, ud['victim']
    if ud['age'] == ud['next']:
        if ud['st'] == 0:
            ud['n'] += 1
            last = ud['n'] > 0xf
            vx, vy = _pos(v)
            x = vx - 0x200000 + (_rand(b) & 63) * FP
            y = vy - 0x180000 + (_rand(b) % 0x30) * FP
            z = 0x820000 + (_rand(b) & 1) * FP
            fx(b, _chunk_think, x, y, z, CHUNK_SEQ, chunk=True, spell=sp, victim=v, last=last, st=0,
               **_motion(m=0x41, tz=0x800000))
            _sfx(b, SFX_SPAWN)
            sp.live += 1                    # (近似: exe 不等未落地的冰块, 这里等全部落地再收尾)
            ud['next'] += INTERVAL
            if last:
                ud['next'] += DROP_DELAY
                ud['st'] = e.state_code = 10
        else:
            sp.drop = True                  # DAT_0086a76c = 1
            eng.destroy(e)
            return
    ud['age'] += 1


class IceStorm(Spell):
    def on_cast_impact(self) -> None:
        self.drop = False                   # case -1: DAT_0086a76c = 0
        for v in self.targets:
            e = self.battle.engine.spawn(think_fn=_launcher_think)
            e.flags = 0x800 | 0x10000
            e.user_data.update(kind='enemy_ice_storm', projectile=True, launcher=True, spell=self, victim=v,
                               age=0, next=FIRST, n=0, st=0)
            self.live += 1
        if not self.targets:
            self.finish()

    def on_chunk_land(self, v, last: bool) -> None:
        self.live -= 1
        self.hit(v, fx='both')              # -250
        if last:
            self.live -= 1
            self.settle(v)                  # -200
            _sfx(self.battle, SFX_LAST)
        if self.live <= 0:
            self.finish()


TEMPLATES = {0x4d859f: IceStorm}
