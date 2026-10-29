"""把战斗用到的图集接到 Unity 工程 (FlyingSb.Domain.Tactics 的视图层): 帧表 + 贴图目录.

  venv/bin/python -m tools.export_unity_sprites <unity 工程根>
贴图优先复用工程自己的 Generated 图集 (ps_X → Generated/Actors/Atlases/X.png, fm 槽 N → Generated/Battle/Pages/*-bank-N.png),
色键转透明后与之逐像素比对 (透明像素不比 RGB); 没有现成的才输出 Resources/Tactics/Sprites/<资源名>.png (+ .meta, 点采样/不压缩).
    → Assets/FlyingSb/Resources/Tactics/TacticsSpriteCatalog.asset   资源名 → 贴图 guid (TacticsSpriteCatalog)
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
import re
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


CATALOG_SCRIPT_GUID = '6163265e0bee42f2b0ed0bee8e457429'   # FlyingSb/Tactics/TacticsSpriteCatalog.cs


def keyed_surface(name: str):
    """pcx → RGBA surface, 色键 (左上角像素或覆盖表) 变透明."""
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
    return surf


def pixel_diff(surf, png: Path) -> int:
    """与现成 PNG 不同的像素数 (两边都透明的不算); 尺寸不同 → -1."""
    other = pygame.image.load(str(png))
    if other.get_size() != surf.get_size():
        return -1
    a, b = pygame.image.tobytes(surf, 'RGBA'), pygame.image.tobytes(other, 'RGBA')
    if a == b:
        return 0
    return sum(1 for i in range(0, len(a), 4) if (a[i + 3] or b[i + 3]) and a[i:i + 4] != b[i:i + 4])


def guid_of(png: Path) -> str:
    for line in png.with_name(png.name + '.meta').read_text().splitlines():
        if line.startswith('guid:'):
            return line.split()[1]
    raise ValueError(png)


def own_png(surf, out: Path) -> str:
    out.parent.mkdir(parents=True, exist_ok=True)
    pygame.image.save(surf, str(out))
    meta = out.with_name(out.name + '.meta')
    if not meta.exists():
        meta.write_text(META.format(guid=uuid.uuid4().hex))
    return guid_of(out)


def write_catalog(path: Path, entries: dict[str, str]) -> None:
    names = sorted(entries)
    lines = ['%YAML 1.1', '%TAG !u! tag:unity3d.com,2011:', '--- !u!114 &11400000', 'MonoBehaviour:',
             '  m_ObjectHideFlags: 0', '  m_CorrespondingSourceObject: {fileID: 0}', '  m_PrefabInstance: {fileID: 0}',
             '  m_PrefabAsset: {fileID: 0}', '  m_GameObject: {fileID: 0}', '  m_Enabled: 1', '  m_EditorHideFlags: 0',
             f'  m_Script: {{fileID: 11500000, guid: {CATALOG_SCRIPT_GUID}, type: 3}}', '  m_Name: TacticsSpriteCatalog',
             '  m_EditorClassIdentifier: ', '  names:']
    lines += [f'  - {n}' for n in names]
    lines.append('  textures:')
    lines += [f'  - {{fileID: 2800000, guid: {entries[n]}, type: 3}}' for n in names]
    path.write_text('\n'.join(lines) + '\n')
    meta = path.with_name(path.name + '.meta')
    if not meta.exists():
        meta.write_text(f'fileFormatVersion: 2\nguid: {uuid.uuid4().hex}\nNativeFormatImporter:\n  externalObjects: {{}}\n'
                        '  mainObjectFileID: 11400000\n  userData: \n  assetBundleName: \n  assetBundleVariant: \n')


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
    gen = unity / 'Assets/FlyingSb/Generated'
    pages: dict[int, list[Path]] = {}
    for p in (gen / 'Battle/Pages').glob('*.png'):
        m = re.search(r'-bank-(\d+)\.png$', p.name) or re.match(r'bank0_g(\d+)_', p.name)
        if m:
            pages.setdefault(int(m.group(1)), []).append(p)
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
    ps_names += [n for n in ('ps_CUN00', 'ps_CDE00') if (SPRITES_DIR / f'{n}.pcx').exists() and n not in ps_names]   # 召喚精靈 (core.mina_skills)
    from tools.export_unity_tactics import export_seqs
    used = {214, 215, 216, 217}
    for hx in export_seqs().values():
        b = bytes.fromhex(hx)
        i = 0
        while i + 1 < len(b):
            if b[i] == 4:                                    # FM mode 0: 全局 fm 图集号
                used.add(b[i + 2] | b[i + 3] << 8)
            i += max(b[i + 1], 1)
    used |= set(ATLAS_NAME_BY_IDX)                   # 技能/远程普攻的特效实体在代码里直接设图集号 (不在 seq 里) → 全部战斗 fm 图集都接上
    slots = {i: 'fm_' + ATLAS_NAME_BY_IDX[i].upper() for i in sorted(used) if i in ATLAS_NAME_BY_IDX}
    from core.grid_atlas_table import GRID_ATLAS
    pack = {'ps': {}, 'fm': {}, 'slots': {str(k): v for k, v in slots.items()}, 'players': players,
            'grid': {str(k): v[0] for k, v in sorted(GRID_ATLAS.items()) if v[0] in ps_names},   # fm_mode1 绝对下标 → ps_ 资源名 (grid_atlas_key)
            'enemies': {str(k): v for k, v in enemies.items()}}
    entries: dict[str, str] = {}
    own: list[str] = []

    def bind(n: str, surf, cands: list[Path]) -> None:
        diffs = sorted((pixel_diff(surf, c), c) for c in cands)
        hit = next(((d, c) for d, c in diffs if 0 <= d <= 4), None)   # ps_CCHA06 有 1 像素 (207,450) 对方不透明黑
        if hit:
            if hit[0]:
                print(f'  {n}: 复用 {hit[1].name}, {hit[0]} 像素不同')
            entries[n] = guid_of(hit[1])
        else:
            entries[n] = own_png(surf, res / 'Sprites' / f'{n}.png')
            own.append(n)

    for n in ps_names:
        surf = keyed_surface(n)
        if surf:
            pack['ps'][n] = ps_entry(n, surf.get_size())
            p = gen / 'Actors/Atlases' / f'{n[3:]}.png'
            bind(n, surf, [p] if p.exists() else [])
    for idx, n in slots.items():
        key = ATLAS_NAME_BY_IDX[idx]
        surf = keyed_surface(n) if key in FM_FRAMES else None
        if surf:
            pack['fm'][n] = [list(f) for f in FM_FRAMES[key]]
            bind(n, surf, pages.get(idx, []))
    sh = pygame.image.load(str(ROOT / 'assets/ui/SHADOW.png')).convert()      # 单位/分身落地影子 (core.sprites.base.load_shadow), 工程里没有原图
    sh.set_colorkey((0, 163, 0))
    sh = sh.convert_alpha()
    entries['ui_SHADOW'] = own_png(sh, res / 'Sprites' / 'ui_SHADOW.png')
    own.append('ui_SHADOW')
    for p in (res / 'Sprites').glob('*.png'):                       # 不再需要的自带 PNG
        if p.stem not in own:
            p.unlink()
            p.with_name(p.name + '.meta').unlink(missing_ok=True)
    from core import real_map as realm                               # 竞技场真实地图的图集 (TacticsData arena_map.tileset)
    if realm.maps_available() and realm.is_available(realm.DEFAULT_ARENA_MAP):
        ts = realm.load(realm.DEFAULT_ARENA_MAP).ts_name
        raw = realm._load_surface(ts)
        if raw is not None:
            key = raw.get_colorkey()
            surf = raw.convert_alpha()
            surf.lock()
            for y in range(surf.get_height()):
                for x in range(surf.get_width()):
                    c = surf.get_at((x, y))
                    if key is not None and (c.r, c.g, c.b) == tuple(key)[:3]:
                        surf.set_at((x, y), (0, 0, 0, 0))
            surf.unlock()
            p = gen / 'Atlases' / f'{ts}.png'
            bind(f'map_{ts}', surf, [p] if p.exists() else [])
    for ui in ('SMENU',):                                          # 战斗 UI 图 (十字菜单图标), 直接用工程已有的
        p = gen / 'Battle/Pages' / f'{ui}.png'
        if p.exists():
            entries[f'ui_{ui}'] = guid_of(p)
    write_catalog(res / 'TacticsSpriteCatalog.asset', entries)
    (res / 'TacticsSprites.json').write_text(json.dumps(pack, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
    total = sum(p.stat().st_size for p in (res / 'Sprites').glob('*.png'))
    print(f"ps {len(pack['ps'])} fm {len(pack['fm'])} slots {len(slots)} 复用 {len(entries) - len(own)} "
          f"自带 {len(own)} ({total // 1024}KB): {' '.join(own)}")


if __name__ == '__main__':
    main(sys.argv)
