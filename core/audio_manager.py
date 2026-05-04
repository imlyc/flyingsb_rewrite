"""音频管理: 封装 pygame.mixer, 自动从 assets/audio/ 加载."""

from __future__ import annotations

from pathlib import Path

import pygame

ASSETS_DIR = Path(__file__).resolve().parent.parent / "assets" / "audio"


class AudioManager:
    def __init__(self, assets_dir: Path = ASSETS_DIR) -> None:
        if not pygame.mixer.get_init():
            pygame.mixer.init()
        self.assets_dir = assets_dir
        self._sfx_cache: dict[str, pygame.mixer.Sound] = {}
        self._current_bgm: str | None = None

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

    def set_volume(self, volume: float) -> None:
        """统一设置 BGM + SFX 音量, 0.0 ~ 1.0."""
        volume = max(0.0, min(1.0, volume))
        pygame.mixer.music.set_volume(volume)
        for s in self._sfx_cache.values():
            s.set_volume(volume)
