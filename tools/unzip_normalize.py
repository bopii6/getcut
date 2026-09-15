"""解压素材包 zip（云端/Linux 用）。

处理两类 Windows 打包常见问题：
1. 路径分隔符是反斜杠（PowerShell Compress-Archive 产物）→ 归一化为正斜杠；
2. zip 里多套了一层同名目录（压缩时选的是文件夹本身）→ 自动展平到根。

用法：python tools/unzip_normalize.py <zip> <目标目录>
"""
from __future__ import annotations

import shutil
import sys
import zipfile
from pathlib import Path


def _extract(zf: zipfile.ZipFile, dest: Path) -> None:
    dest_res = dest.resolve()
    for info in zf.infolist():
        name = info.filename.replace("\\", "/").lstrip("/")
        if not name or name.endswith("/"):
            continue
        target = (dest_res / name).resolve()
        if target != dest_res and dest_res not in target.parents:
            raise SystemExit(f"非法路径（疑似 Zip Slip）：{info.filename}")
        target.parent.mkdir(parents=True, exist_ok=True)
        with zf.open(info) as src, open(target, "wb") as out:
            shutil.copyfileobj(src, out)


def main(src: str, dest: str) -> None:
    dest_path = Path(dest)
    dest_path.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(src) as zf:
        _extract(zf, dest_path)

    # 展平：content.json 若在一层同名子目录里，提到根
    if not (dest_path / "content.json").is_file():
        subs = [d for d in dest_path.iterdir() if d.is_dir()]
        for sub in subs:
            if (sub / "content.json").is_file():
                for item in list(sub.iterdir()):
                    shutil.move(str(item), str(dest_path / item.name))
                sub.rmdir()
                break

    if not (dest_path / "content.json").is_file():
        raise SystemExit("zip 里没有 content.json，不是有效的素材包")

    print(f"解压完成：{dest_path}（{len(list(dest_path.rglob('*')))} 项）")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit(__doc__)
    main(sys.argv[1], sys.argv[2])
