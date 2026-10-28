"""把战斗用到的图集导出给 Unity 工程 (FlyingSb.Domain.Tactics 的视图层), 色键转透明 PNG + 帧表.

  venv/bin/python -m tools.export_unity_sprites <unity 工程根>
    → Assets/FlyingSb/Resources/Tactics/Sprites/<资源名>.png (+ .meta, 点采样/不压缩)
    → Assets/FlyingSb/Resources/Tactics/TacticsSprites.json
        ps:    {资源名: [帧宽, 帧高, 列, 行, 锚x, 锚y, 走路帧数]}   ps_ 网格图 (走路 00 / 虚弱 04 / 待机受击 06 / 其它槽)
        fm:    {资源名: [[x, y, w, h, 锚x, 锚y], ...]}             fm_ 逐帧 BBox 图集
        slots: {全局图集号: fm 资源名}                              seq 的 fm 槽号 → 资源
        players: {角色名: 走路图资源名}, enemies: {敌人表下标: 走路图资源名}
锚点与 Python 渲染一致: ps_ 用 exe 网格表 (非标准锚 y+2) 否则 (帧宽/2, 帧高-12); fm_ 用 core.fm_frames.
"""
from __future__ import annotations

import json
import os
import sys
import uuid
from pathlib import Path

os.environ.setdefault('SDL_VIDEODRIVER', 'dummy')
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pygame  # noqa: E402

from core import character_data as CD  # noqa: E402
from core.character_sprites import CHARACTER_SPRITES, sprite_resource  # noqa: E402
from core.fm_frames import FM_FRAMES  # noqa: E402
from core.raw_attack_seqs import ATLAS_NAME_BY_IDX  # noqa: E402
from core.sprites.loaders import SPRITES_DIR, STD_ANCHOR, _FM_COLORKEY_OVERRIDE, _grid_info, get_character_sprite  # noqa: E402

META = """fileFormatVersion: 2
guid: {guid}
TextureImporter:
  internalIDToNameTable: []
  externalObjects: {{}}
  serializedVersion: 13
  mipmaps:
    mipMapMode: 0
    enableMipMap: 0
    sRGBTexture: 1
    linearTexture: 0
    fadeOut: 0
    borderMipMap: 0
    mipMapsPreserveCoverage: 0
    alphaTestReferenceValue: 0.5
    mipMapFadeDistanceStart: 1
    mipMapFadeDistanceEnd: 3
  bumpmap:
    convertToNormalMap: 0
    externalNormalMap: 0
    heightScale: 0.25
    normalMapFilter: 0
    flipGreenChannel: 0
  isReadable: 0
  streamingMipmaps: 0
  streamingMipmapsPriority: 0
  vTOnly: 0
  ignoreMipmapLimit: 0
  grayScaleToAlpha: 0
  generateCubemap: 6
  cubemapConvolution: 0
  seamlessCubemap: 0
  textureFormat: 1
  maxTextureSize: 4096
  textureSettings:
    serializedVersion: 2
    filterMode: 0
    aniso: 1
    mipBias: 0
    wrapU: 1
    wrapV: 1
    wrapW: 1
  nPOTScale: 0
  lightmap: 0
  compressionQuality: 50
  spriteMode: 0
  spriteExtrude: 1
  spriteMeshType: 0
  alignment: 0
  spritePivot: {{x: 0.5, y: 0.5}}
  spritePixelsToUnits: 100
  spriteBorder: {{x: 0, y: 0, z: 0, w: 0}}
  spriteGenerateFallbackPhysicsShape: 1
  alphaUsage: 1
  alphaIsTransparency: 1
  spriteTessellationDetail: -1
  textureType: 0
  textureShape: 1
  singleChannelComponent: 0
  flipbookRows: 1
  flipbookColumns: 1
  maxTextureSizeSet: 0
  compressionQualitySet: 0
  textureFormatSet: 0
  ignorePngGamma: 0
  applyGammaDecoding: 0
  swizzle: 50462976
  cookieLightType: 0
  platformSettings:
  - serializedVersion: 3
    buildTarget: DefaultTexturePlatform
    maxTextureSize: 4096
    resizeAlgorithm: 0
    textureFormat: -1
    textureCompression: 0
    compressionQuality: 50
    crunchedCompression: 0
    allowsAlphaSplitting: 0
    overridden: 0
    ignorePlatformSupport: 0
    androidETC2FallbackOverride: 0
    forceMaximumCompressionQuality_BC6H_BC7: 0
  spriteSheet:
    serializedVersion: 2
    sprites: []
    outline: []
    physicsShape: []
    bones: []
    spriteID:
    internalID: 0
    vertices: []
    indices:
    edges: []
    weights: []
    secondaryTextures: []
    nameFileIdTable: {{}}
  mipmapLimitGroupName:
  pSDRemoveMatte: 0
  userData:
  assetBundleName:
  assetBundleVariant:
"""


def keyed_png(name: str, out: Path) -> tuple[int, int] | None:
    """pcx → RGBA PNG, 色键 (左上角像素或覆盖表) 变透明. 返回 (宽, 高)."""
    src = SPRITES_DIR / f"{name}.pcx"
    if not src.exists():
        return None
    surf = pygame.image.load(str(src)).convert_alpha()
    key = _FM_COLORKEY_OVERRIDE.get(name) or tuple(pygame.image.load(str(src)).get_at((0, 0)))[:3]
    w, h = surf.get_size()
    surf.lock()
    for y in range(h):
        for x in range(w):
            c = surf.get_at((x, y))
            if (c.r, c.g, c.b) == key:
                surf.set_at((x, y), (0, 0, 0, 0))
    surf.unlock()
    out.parent.mkdir(parents=True, exist_ok=True)
    pygame.image.save(surf, str(out))
    meta = out.with_name(out.name + '.meta')
    if not meta.exists():
        meta.write_text(META.format(guid=uuid.uuid4().hex))
    return w, h


def ps_entry(name: str, size: tuple[int, int]) -> list[int]:
    g = _grid_info(name)
    w, h = size
    fw, fh = (w // g[0], h // g[1]) if g else (64, 96)
    ax, ay = (g[2], g[3] + 2) if g and (g[2], g[3]) != STD_ANCHOR else (fw // 2, fh - 12)
    walk = 0
    if name.endswith('00'):
        try:
            walk = get_character_sprite(name).walk_frames
        except Exception:
            walk = 0
    return [fw, fh, w // fw, h // fh, ax, ay, walk]


def main(argv: list[str]) -> None:
    unity = Path(argv[1]) if len(argv) > 1 else ROOT.parent / 'flyingsb-unity'
    res = unity / 'Assets/FlyingSb/Resources/Tactics'
    pygame.display.init()
    pygame.display.set_mode((1, 1))
    players = {n: sprite_resource(n) for n in CHARACTER_SPRITES if n in CD.NAME_TO_RECORD}
    enemies = {}
    for t in range(CD.enemy_count()):
        e = CD.enemy(t)
        if e and e.get('sprite'):
            enemies[t] = e['sprite']
    bases = sorted({k[:-2] for k in list(players.values()) + list(enemies.values())})
    ps_names = sorted(p.stem for b in bases for p in SPRITES_DIR.glob(f'{b}??.pcx'))
    from tools.export_unity_tactics import export_seqs
    used = {214, 215, 216, 217}
    for hx in export_seqs().values():
        b = bytes.fromhex(hx)
        i = 0
        while i + 1 < len(b):
            if b[i] == 4:                                    # FM mode 0: 全局 fm 图集号
                used.add(b[i + 2] | b[i + 3] << 8)
            i += max(b[i + 1], 1)
    slots = {i: 'fm_' + ATLAS_NAME_BY_IDX[i].upper() for i in sorted(used) if i in ATLAS_NAME_BY_IDX}
    pack = {'ps': {}, 'fm': {}, 'slots': {str(k): v for k, v in slots.items()}, 'players': players,
            'enemies': {str(k): v for k, v in enemies.items()}}
    for n in ps_names:
        size = keyed_png(n, res / 'Sprites' / f'{n}.png')
        if size:
            pack['ps'][n] = ps_entry(n, size)
    for idx, n in slots.items():
        key = ATLAS_NAME_BY_IDX[idx]
        if key in FM_FRAMES and keyed_png(n, res / 'Sprites' / f'{n}.png'):
            pack['fm'][n] = [list(f) for f in FM_FRAMES[key]]
    (res / 'TacticsSprites.json').write_text(json.dumps(pack, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
    total = sum(p.stat().st_size for p in (res / 'Sprites').glob('*.png'))
    print(f"ps {len(pack['ps'])} fm {len(pack['fm'])} slots {len(slots)} png {total // 1024}KB")


if __name__ == '__main__':
    main(sys.argv)
