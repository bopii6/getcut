# -*- coding: utf-8 -*-
"""补结尾卡：单独渲染 3 秒 slogan 卡 → 与原片拼接 → 重混音 → 输出最终片"""
import sys, json, shutil, subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'videogen'))
from videogen import compose, remotion_render as rr

WORK = ROOT / '_replica'
FRAMES = 90  # 3 秒
END_PROPS = {
    'durationInFrames': FRAMES,
    'template': 'zhigu',
    'showSubtitles': False,
    'headline': {'lines': [{'text': 'AI办公"三国杀"'}, {'text': '百度搭子 有多惊艳？'}]},
    'sources': [], 'disclaimer': '', 'clauses': [],
    'shots': [{'kind': 'footage', 'startMs': 0, 'endMs': FRAMES / 30 * 1000,
               'stage': {'mode': 'end', 'end': {'slogan': '有大事看 GetCut', 'highlight': 'GetCut'}}}],
}
(rr.RENDERER / 'props.json').write_text(json.dumps(END_PROPS, ensure_ascii=False, indent=1), encoding='utf-8')

print('渲染结尾卡…')
end_mp4 = rr.render_visual(END_PROPS, WORK / 'end_card.mp4', timeout=900)
print('结尾卡完成:', end_mp4)

# 原片 + 结尾卡拼接
listfile = WORK / 'concat.txt'
listfile.write_text(
    f"file '{(WORK / 'visual_out.mp4').as_posix()}'\nfile '{end_mp4.as_posix()}'\n", encoding='utf-8')
joined = WORK / 'joined.mp4'
subprocess.run(['ffmpeg', '-y', '-v', 'error', '-f', 'concat', '-safe', '0', '-i', str(listfile),
                '-c', 'copy', str(joined)], check=True)
print('拼接完成:', joined, joined.stat().st_size)

# 重混音（时长 +3 秒，尾部静音）
import json as _json
mp3 = WORK / 'tts' / 'tts.mp3'
props = _json.loads((rr.RENDERER / 'props.json').read_text(encoding='utf-8'))  # 占位，避免未用告警
total_s = 205.9 + FRAMES / 30
audio = compose.mix_audio(mp3, total_s, WORK, bgm=None)
print('音频完成:', audio)

final = compose.mux(joined, audio, ROOT / '_zhigu_replica.mp4', WORK)
print('DONE:', final, final.stat().st_size)
