"""把原版 6 个 DLL 的 PE 资源批量 dump 出来.

输出布局:
  assets/sprites/    PCX (角色/怪物 atlas), 来自 ase_fm.dll + ase_ps.dll
  assets/maps/       PCX/MAP/MAT/MFO, 来自 mapset.dll
  assets/ui/         PCX/BMP, 来自 pcxset.dll
  assets/audio_extracted/  WAV, 来自 se_event.dll + wav_eft.dll

每个 PCX 同时存 .pcx (原始) + .png (pygame 加载后另存, 便于查看).
最后写一份 assets/_manifest.json 列出全部资源 (路径/尺寸/源 DLL).

跑法: cd rewrite && venv/bin/python -m tools.extract_dll
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# 原版游戏目录: 默认 repo 上一级的 origin/flyingsb, 可用 FLYINGSB_ORIGIN 环境变量覆盖
ORIGIN = Path(os.environ.get("FLYINGSB_ORIGIN", ROOT.parent / "origin" / "flyingsb"))
ASSETS = ROOT / "assets"

# DLL → 输出子目录 (相对 ASSETS)
DLL_LAYOUT = {
    "ase_fm.dll":   "sprites",
    "ase_ps.dll":   "sprites",
    "mapset.dll":   "maps",
    "pcxset.dll":   "ui",
    "se_event.dll": "audio_extracted",
    "wav_eft.dll":  "audio_extracted",
}

# DLL prefix 用于避免命名冲突 (两个 sprite DLL 都有 CAELE 等同名)
DLL_PREFIX = {
    "ase_fm.dll":   "fm_",
    "ase_ps.dll":   "ps_",
    "mapset.dll":   "",
    "pcxset.dll":   "",
    "se_event.dll": "se_",
    "wav_eft.dll":  "ef_",
}


def iter_resources(pe):
    """yield (type_name, resource_name, raw_bytes) for every leaf in the resource tree."""
    if not hasattr(pe, "DIRECTORY_ENTRY_RESOURCE"):
        return
    for type_entry in pe.DIRECTORY_ENTRY_RESOURCE.entries:
        if type_entry.name is not None:
            type_name = type_entry.name.string.decode(errors="replace")
        else:
            # 标准 PE 类型 ID (BMP/RT_BITMAP 等); 我们用不到, 全打数字
            type_name = str(type_entry.id)
        for name_entry in type_entry.directory.entries:
            if name_entry.name is not None:
                res_name = name_entry.name.string.decode(errors="replace")
            else:
                res_name = str(name_entry.id)
            for lang_entry in name_entry.directory.entries:
                rva = lang_entry.data.struct.OffsetToData
                size = lang_entry.data.struct.Size
                data = pe.get_memory_mapped_image()[rva : rva + size]
                yield type_name, res_name, data


def extract():
    import pefile  # 延迟 import, 让 --help 等不依赖
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    import pygame
    pygame.init()

    manifest: list[dict] = []
    counts: dict[str, dict[str, int]] = {}  # dll -> type -> n

    for dll_name, subdir in DLL_LAYOUT.items():
        src = ORIGIN / dll_name
        if not src.exists():
            print(f"[skip] {src} 不存在")
            continue
        out_dir = ASSETS / subdir
        out_dir.mkdir(parents=True, exist_ok=True)
        prefix = DLL_PREFIX[dll_name]

        print(f"\n=== {dll_name} → {subdir}/ ===")
        pe = pefile.PE(str(src), fast_load=True)
        pe.parse_data_directories(
            directories=[pefile.DIRECTORY_ENTRY["IMAGE_DIRECTORY_ENTRY_RESOURCE"]]
        )

        n_total = 0
        n_failed_png = 0
        for type_name, res_name, data in iter_resources(pe):
            ext = type_name.lower()  # PCX → 'pcx', WAV → 'wav', MAP → 'map', etc
            base = f"{prefix}{res_name}"
            raw_path = out_dir / f"{base}.{ext}"
            raw_path.write_bytes(data)
            entry = {
                "dll": dll_name,
                "type": type_name,
                "name": res_name,
                "raw_path": str(raw_path.relative_to(ROOT)),
                "size_bytes": len(data),
            }

            # 图像类: 尝试转 PNG 顺手记录 (w, h)
            if ext in ("pcx", "bmp"):
                try:
                    surf = pygame.image.load(str(raw_path))
                    png_path = raw_path.with_suffix(".png")
                    pygame.image.save(surf, str(png_path))
                    entry["png_path"] = str(png_path.relative_to(ROOT))
                    entry["width"], entry["height"] = surf.get_size()
                except Exception as e:
                    n_failed_png += 1
                    entry["png_error"] = str(e)

            manifest.append(entry)
            counts.setdefault(dll_name, {}).setdefault(type_name, 0)
            counts[dll_name][type_name] += 1
            n_total += 1

        type_summary = "  ".join(f"{t}:{n}" for t, n in counts.get(dll_name, {}).items())
        print(f"  {n_total:4d} 项  ({type_summary})", end="")
        if n_failed_png:
            print(f"  PNG 失败 {n_failed_png}", end="")
        print()

    # 写 manifest
    manifest_path = ASSETS / "_manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
    print(f"\n→ 共 {len(manifest)} 项  manifest: {manifest_path.relative_to(ROOT)}")


if __name__ == "__main__":
    sys.exit(extract())
