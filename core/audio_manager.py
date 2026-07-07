"""音频管理: 封装 pygame.mixer, 自动从 assets/audio/ 加载."""

from __future__ import annotations

from pathlib import Path

import pygame

ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets" / "audio"
SFX_DIR = Path(__file__).resolve().parent.parent / "assets" / "audio_extracted"

# solo 音效的爆发窗口 (ms): 段开头这段时间内的同 id 请求允许叠放 (= 段内密集),
# 窗口过后跳过, 直到本段全部播完才开下一段 (= 段间隔). 用户按原版听感校准:
# 青龙冰锥雨 (100 tick = 4s) = **5 段**, 每段内部密集叠放. 段周期 ≈ 窗口 + E005 时长(558ms)
# ≈ 800ms → 4s 正好 5 段.
SOLO_BURST_MS = 240


class AudioManager:
    def __init__(self, assets_dir: Path = ASSETS_DIR, sfx_dir: Path = SFX_DIR) -> None:
        if not pygame.mixer.get_init():
            pygame.mixer.init()
        # 默认 8 通道不够密集技能音 (如青龙冰锥雨每 2 tick/敌 一声 0xad) 叠放, 会互抢截断
        pygame.mixer.set_num_channels(32)
        self.assets_dir = assets_dir
        self.sfx_dir = sfx_dir
        self._sfx_cache: dict[str, pygame.mixer.Sound] = {}
        self._sfx_id_cache: dict[int, "pygame.mixer.Sound | None"] = {}
        self._solo_channels: dict[int, list] = {}      # id → 本段占用的 channels
        self._solo_seg_start: dict[int, int] = {}      # id → 本段开始时刻 (ms)
        self._current_bgm: str | None = None
        self._volume = 1.0

    def _resolve(self, filename: str) -> Path:
        """支持大小写无关查找 (原版文件名混用大写/小写)."""
        p = self.assets_dir / filename
        if p.exists():
            return p
        # 大小写无关 fallback
        lower = filename.lower()
        for f in self.assets_dir.iterdir():
            if f.name.lower() == lower:
                return f
        raise FileNotFoundError(f"audio not found: {filename} (in {self.assets_dir})")

    def play_bgm(self, filename: str, loops: int = -1) -> None:
        """循环播放背景音乐 (loops=-1 表示无限循环)."""
        if self._current_bgm == filename and pygame.mixer.music.get_busy():
            return
        path = self._resolve(filename)
        pygame.mixer.music.load(str(path))
        pygame.mixer.music.play(loops=loops)
        self._current_bgm = filename

    def stop_bgm(self) -> None:
        pygame.mixer.music.stop()
        self._current_bgm = None

    def play_sfx(self, filename: str) -> None:
        if filename not in self._sfx_cache:
            self._sfx_cache[filename] = pygame.mixer.Sound(str(self._resolve(filename)))
        self._sfx_cache[filename].play()

    def play_sfx_id(self, sound_id: int, solo: bool = False) -> None:
        """按全局 sound_id 播放战斗音效 (anim seq 'sound' op / 技能 dispatcher 用).
        映射见 core.sound_table; 缺失/加载失败静默忽略 (不阻断游戏).

        solo=True: 同 id **分段爆发** — 通道空闲时开新段, 段开头 SOLO_BURST_MS 窗口内允许
        叠放 (段内密集), 之后跳过直到本段播完 (段间隔). 密集技能音 (青龙冰锥雨每 80ms 一声
        0xad) 用它复刻原版"4-5 段、每段内密集"的听感; 不加则 100 声连叠成一整片糊."""
        snd = self._sfx_id_cache.get(sound_id, False)
        if snd is False:                       # 未尝试加载过
            snd = None
            from core.sound_table import sound_file
            fn = sound_file(sound_id)
            if fn:
                p = self.sfx_dir / fn
                if p.exists():
                    try:
                        snd = pygame.mixer.Sound(str(p))
                        snd.set_volume(self._volume)
                    except (pygame.error, FileNotFoundError):
                        snd = None
            self._sfx_id_cache[sound_id] = snd
        if snd is None:
            return
        if solo:
            # ⚠ 通道复用陷阱: 本段播完后 pygame 会把空闲 Channel 分给别的音 (如龙吟 0x147),
            # 只查 get_busy() 会把"别人占了这个通道"误判成"本段还在播" → 整段雨被跳掉.
            # 必须确认通道上放的还是**这个音**.
            chs = [c for c in self._solo_channels.get(sound_id, ())
                   if c is not None and c.get_busy() and c.get_sound() is snd]
            now = pygame.time.get_ticks()
            if chs:
                if now - self._solo_seg_start.get(sound_id, 0) > SOLO_BURST_MS:
                    self._solo_channels[sound_id] = chs
                    return                      # 本段爆发窗口已过 → 跳过, 等段播完
            else:
                self._solo_seg_start[sound_id] = now    # 全部播完 → 开新段
            chs.append(snd.play())
            self._solo_channels[sound_id] = chs
        else:
            snd.play()

    def stop_sfx_id(self, sound_id: int) -> None:
        """停掉指定 sound_id 的音效 (exe FUN_00416388, 技能收尾切断循环/长音用)."""
        snd = self._sfx_id_cache.get(sound_id)
        if snd:
            snd.stop()

    def set_volume(self, volume: float) -> None:
        """统一设置 BGM + SFX 音量, 0.0 ~ 1.0."""
        volume = max(0.0, min(1.0, volume))
        self._volume = volume
        pygame.mixer.music.set_volume(volume)
        for s in self._sfx_cache.values():
            s.set_volume(volume)
        for s in self._sfx_id_cache.values():
            if s is not None:
                s.set_volume(volume)
