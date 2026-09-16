"""生成剪映（JianYing 专业版）草稿包，供用户在剪映里二次剪辑。

产出 zip 结构：
    videogen_draft_<rid6>/          ← 这个整体拷进剪映草稿库（一键导入剪映.bat 会代劳）
        draft_content.json          ← 时间线：按分镜切好的视频段 +（关字幕渲染时）可编辑字幕
        draft_meta_info.json
        media/final.mp4             ← 成片（含全部声音）
        media/voice.mp3             ← 配音干声（备件）
    一键导入剪映.bat                 ← 拷贝草稿到剪映草稿库并改写素材绝对路径
    使用说明.txt

格式基准：pyJianYingDraft (MIT) 的 draft 模板（JianYing 5.9 线，向上兼容）。
媒体路径在 JSON 里以 __VG_DRAFT_DIR__ 占位 + 正斜杠，由 bat 导入时改写为
真实路径的正斜杠形式（避免 JSON 反斜杠转义问题；Windows 文件 API 通用）。
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path

_US = 1000  # 毫秒 -> 微秒
TMPL_DIR = Path(__file__).resolve().parent
PLACEHOLDER = "__VG_DRAFT_DIR__"


def _uid() -> str:
    return uuid.uuid4().hex


def _trange(start_ms: float, dur_ms: float) -> dict:
    return {"start": int(round(start_ms * _US)), "duration": int(round(dur_ms * _US))}


def _speed_entry() -> tuple[str, dict]:
    sid = _uid()
    return sid, {"curve_speed": None, "id": sid, "mode": 0, "speed": 1.0, "type": "speed"}


def _clip() -> dict:
    return {"alpha": 1.0, "flip": {"horizontal": False, "vertical": False},
            "rotation": 0.0, "scale": {"x": 1.0, "y": 1.0}, "transform": {"x": 0.0, "y": 0.0}}


def _segment_base(material_id: str, target: dict, *, source: dict | None,
                  speed_id: str, render_index: int) -> dict:
    return {
        "enable_adjust": True, "enable_color_correct_adjust": False,
        "enable_color_curves": True, "enable_color_match_adjust": False,
        "enable_color_wheels": True, "enable_lut": True, "enable_smart_color_adjust": False,
        "last_nonzero_volume": 1.0, "reverse": False, "track_attribute": 0,
        "track_render_index": render_index,
        "visible": True,
        "id": _uid(), "material_id": material_id,
        "target_timerange": target,
        "source_timerange": source,
        "common_keyframes": [], "keyframe_refs": [],
        "speed": 1.0, "volume": 1.0,
        "extra_material_refs": [speed_id],
        "is_tone_modify": False,
        "clip": _clip(),
        "uniform_scale": {"on": True, "value": 1.0},
    }


def _text_material(text: str) -> dict:
    content = json.dumps({
        "styles": [{
            "fill": {"alpha": 1.0, "content": {
                "render_type": "solid", "solid": {"alpha": 1.0, "color": [1.0, 1.0, 1.0]}}},
            "range": [0, len(text)], "size": 8, "bold": True,
            "italic": False, "underline": False, "strokes": [],
        }],
        "text": text,
    }, ensure_ascii=False)
    return {
        "id": _uid(), "content": content, "typesetting": 0, "alignment": 1,
        "letter_spacing": 0.0, "line_spacing": 0.02, "line_feed": 1,
        "line_max_width": 0.82, "force_apply_line_max_width": False,
        "check_flag": 7, "type": "text", "global_alpha": 1.0,
    }


def dump_manifest(path, *, video: str, duration_ms: float, fps: int = 30,
                  width: int = 1080, height: int = 1920, title: str = "",
                  subtitles: bool = True, sources: bool = True, fmt: str = "",
                  sfx_mode: str = "", voice: str | None = None, bgm: str | None = None,
                  render_id: str | None = None,
                  shots: list | None = None, clauses: list | None = None) -> None:
    """渲染结束时把草稿需要的元数据落在成片旁（<成片名>.draft.json）。"""
    data = {"version": 1, "video": video, "duration_ms": float(duration_ms),
            "fps": int(fps), "width": int(width), "height": int(height),
            "title": title, "subtitles": bool(subtitles), "sources": bool(sources),
            "format": fmt, "sfx_mode": sfx_mode,
            "voice": voice, "bgm": bgm, "render_id": render_id,
            "shots": shots or [], "clauses": clauses or []}
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def load_manifest(video_path) -> dict | None:
    """读取成片旁的草稿清单；旧成片没有则返回 None。"""
    p = Path(video_path).with_suffix(".draft.json")
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def build_draft_content(manifest: dict, draft_dir_placeholder: str = PLACEHOLDER) -> dict:
    """按 manifest 构造 draft_content.json 字典。

    manifest 键（见 cli.build 落盘的 *.draft.json）：
    video_name, duration_ms, fps, width, height, shots[], clauses[], subtitles
    """
    media = f"{draft_dir_placeholder}/media"
    tpl = json.load(open(TMPL_DIR / "jianying_template.json", encoding="utf-8"))
    tpl["name"] = manifest.get("title") or "videogen 成片"
    tpl["canvas_config"] = {"width": manifest.get("width", 1080),
                            "height": manifest.get("height", 1920), "ratio": "original"}
    tpl["duration"] = int(round(manifest["duration_ms"] * _US))
    tpl["fps"] = int(manifest.get("fps", 30))

    # 素材：成片视频（声音完整：配音/音乐/音效都在里面）
    vid = _uid()
    tpl["materials"]["videos"].append({
        "audio_fade": None, "category_id": "", "category_name": "local",
        "check_flag": 63487,
        "crop": {"upper_left_x": 0.0, "upper_left_y": 0.0, "upper_right_x": 1.0,
                 "lower_left_x": 0.0, "lower_left_y": 1.0,
                 "lower_right_x": 1.0, "lower_right_y": 1.0},
        "crop_ratio": "free", "crop_scale": 1.0,
        "duration": int(round(manifest["duration_ms"] * _US)),
        "height": int(manifest.get("height", 1920)),
        "width": int(manifest.get("width", 1080)),
        "id": vid, "local_material_id": "", "material_id": vid,
        "material_name": manifest.get("video_name", "final.mp4"),
        "media_path": "", "path": f"{media}/final.mp4", "type": "video",
    })

    # 视频轨：按分镜切段（同源文件不同 source 区间），整轨还原成片
    segments: list[dict] = []
    speeds: list[dict] = []
    shots = manifest.get("shots") or [{"start_ms": 0, "end_ms": manifest["duration_ms"]}]
    for shot in shots:
        start = max(0.0, float(shot.get("start_ms", 0)))
        end = min(float(manifest["duration_ms"]), float(shot.get("end_ms", manifest["duration_ms"])))
        if end - start <= 0:
            continue
        sid, sp = _speed_entry()
        speeds.append(sp)
        seg = _segment_base(vid, _trange(start, end - start),
                            source=_trange(start, end - start),
                            speed_id=sid, render_index=0)
        seg["audio_fade"] = None
        segments.append(seg)
    track_video = {"attribute": 0, "flag": 0, "id": _uid(), "is_default_name": True,
                   "name": "", "segments": segments, "type": "video"}

    tracks = [track_video]

    # 文本轨：仅在渲染时关闭了字幕（画面无烧入字幕）才带可编辑字幕
    if manifest.get("subtitles") is False and manifest.get("clauses"):
        tsegs: list[dict] = []
        for cl in manifest["clauses"]:
            text = (cl.get("text") or "").strip()
            start = float(cl.get("start_ms", 0))
            end = min(float(cl.get("end_ms", start)), float(manifest["duration_ms"]))
            if not text or end - start <= 0:
                continue
            tm = _text_material(text)
            tpl["materials"]["texts"].append(tm)
            sid, sp = _speed_entry()
            speeds.append(sp)
            seg = _segment_base(tm["id"], _trange(start, end - start), source=None,
                                speed_id=sid, render_index=1)
            seg["render_index"] = 1
            tsegs.append(seg)
        if tsegs:
            tracks.append({"attribute": 0, "flag": 0, "id": _uid(), "is_default_name": True,
                           "name": "", "segments": tsegs, "type": "text"})

    tpl["materials"]["speeds"] = speeds
    tpl["tracks"] = tracks
    return tpl


def build_meta_info(draft_name: str, duration_ms: float) -> dict:
    mi = json.load(open(TMPL_DIR / "jianying_meta_template.json", encoding="utf-8"))
    mi["draft_id"] = _uid()
    mi["draft_name"] = draft_name
    mi["draft_fold_path"] = PLACEHOLDER
    mi["draft_root_path"] = ""
    mi["tm_duration"] = int(round(duration_ms * _US))
    return mi


_BAT = r"""@echo off
setlocal
set "DEST=%LOCALAPPDATA%\JianyingPro\User Data\Projects\com.lveditor.draft"
set "DESTF=%DEST:\=/%"
set "NAME=__FOLDER__"

if not exist "%DEST%" (
  echo [X] JianYing draft folder not found: %DEST%
  echo     See README.txt for manual install steps.
  pause
  exit /b 1
)

echo Copying draft ...
robocopy "%~dp0__FOLDER__" "%DEST%\__FOLDER__" /E /NFL /NDL /NJH /NJS >nul
if errorlevel 8 (
  echo [X] Copy failed. Please copy folder "__FOLDER__" manually to:
  echo     %DEST%
  pause
  exit /b 1
)

echo Fixing media paths ...
powershell -NoProfile -Command "$d='%DESTF%/__FOLDER__'; $f=$d+'/draft_content.json'; $t=[IO.File]::ReadAllText($f); [IO.File]::WriteAllText($f, $t.Replace('__VG_DRAFT_DIR__', $d)); $f2=$d+'/draft_meta_info.json'; $t2=[IO.File]::ReadAllText($f2); [IO.File]::WriteAllText($f2, $t2.Replace('__VG_DRAFT_DIR__', $d))"

echo.
echo Done! Restart JianYing - the draft appears in the draft list.
pause
"""


def build_bat(draft_folder_name: str) -> str:
    return _BAT.replace("__FOLDER__", draft_folder_name)


README = """videogen 剪映草稿 · 使用说明
================================

这是什么
  一个剪映专业版（Windows 桌面版）草稿包。里面不是只有一个视频：
  - 成片已按 AI 分镜切好段，每一镜在时间线上独立可拖动/裁剪/替换
  - 渲染时如果关闭了字幕，文案会以可编辑文本轨进草稿（可直接改字）
  - media/voice.mp3 是配音干声，需要时可拖回时间线使用

怎么导入（推荐）
  1. 把整个压缩包解压到任意位置
  2. 关闭正在运行的剪映
  3. 双击「一键导入剪映.bat」
  4. 打开剪映 → 首页草稿列表即可看到这条草稿

手动导入（bat 不工作时）
  1. 解压后，把 videogen_draft_xxx 整个文件夹复制到：
     %LOCALAPPDATA%\\JianyingPro\\User Data\\Projects\\com.lveditor.draft\\
  2. 用记事本打开其中的 draft_content.json 和 draft_meta_info.json，
     把里面的 __VG_DRAFT_DIR__ 全部替换为该文件夹的实际路径
  3. 打开剪映即可看到草稿

常见问题
  · 打开草稿提示素材丢失：说明草稿文件夹被移动过，重新跑一次 bat，
    或在剪映里对缺失素材点「查找」并指向草稿文件夹内的 media 目录
  · Mac 版剪映：本包仅支持 Windows 专业版
  · 草稿建立在剪映 5.9 兼容格式上，新版剪映打开时会自动升级
"""


def build_zip(manifest: dict, final_mp4: Path, voice_mp3: Path | None,
              out_zip: Path) -> Path:
    """打包剪映草稿 zip。"""
    import zipfile

    rid = (manifest.get("render_id") or "draft")[:6]
    title = (manifest.get("title") or "成片").strip() or "成片"
    folder = f"videogen_draft_{rid}"
    draft_name = f"{title}（videogen）"

    content = build_draft_content({**manifest, "title": draft_name},
                                  draft_dir_placeholder=PLACEHOLDER)
    meta = build_meta_info(draft_name, manifest["duration_ms"])

    out_zip.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(out_zip, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(f"{folder}/draft_content.json",
                   json.dumps(content, ensure_ascii=False, indent=1))
        z.writestr(f"{folder}/draft_meta_info.json",
                   json.dumps(meta, ensure_ascii=False, indent=1))
        z.write(final_mp4, f"{folder}/media/final.mp4")
        if voice_mp3 and Path(voice_mp3).is_file():
            z.write(voice_mp3, f"{folder}/media/voice.mp3")
        z.writestr("一键导入剪映.bat", build_bat(folder).replace("\n", "\r\n"))
        z.writestr("使用说明.txt", README.replace("\n", "\r\n"))
    return out_zip
