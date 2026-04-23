# video-cut

口播文案 + B-roll 素材 → 可发布视频。

由 Claude Code 驱动，Ali TTS 配音，自动分段配图，支持字幕生成。

---

## 工作流

```
口播文案
  ↓
(可选) dbs-hook 优化开头 / dbs-content 内容诊断
  ↓
Claude 自动分段 + 按 B-roll 文件名语义匹配
  ↓
逐段 TTS 合成（阿里云 qwen3-tts-flash）
  ↓
逐段渲染（B-roll 循环/裁剪 + TTS 音频）
  ↓
拼接 + 字幕 + 响度归一（-14 LUFS）
  ↓
final.mp4
```

---

## 快速开始

**1. 安装依赖**

```bash
cd ~/code/video-cut
pip install -e .
```

需要系统安装 `ffmpeg`：

```bash
brew install ffmpeg
```

**2. 配置密钥**

```bash
cp .env.example .env
```

编辑 `.env`：

```
DASHSCOPE_API_KEY=sk-your-key-here   # 必须，TTS 使用
```

> 字幕直接从文案文本生成，不需要 ASR，不需要 Qiniu。

**3. 放入 B-roll 素材**

```bash
input/broll/
  product_demo.mp4
  lifestyle_outdoor.mp4
  cta_phone.mp4
```

> 文件名即语义——Claude 靠文件名匹配段落，命名越描述性，匹配越准确。

**4. 在 Claude Code 里开始**

把 `skills/video-cut/SKILL.md` 注册为 skill，然后把口播文案发给 Claude，按引导完成流程。

---

## Helpers

| 文件 | 作用 |
|------|------|
| `helpers/tts.py` | Ali qwen3-tts-flash 语音合成 |
| `helpers/subtitles.py` | 文案文本 + 音频时长 → SRT 字幕 |
| `helpers/compose_segment.py` | 单段 B-roll + TTS → MP4 |
| `helpers/concat_final.py` | 拼接所有段落 + 字幕 + loudnorm |

**单独使用：**

```bash
# TTS 合成
python helpers/tts.py "你的文案" --voice Cherry --output edit/test.wav

# 查看可用声音
python helpers/tts.py --list-voices

# 单段渲染（预览）
python helpers/compose_segment.py \
    --tts edit/segments/seg_01.wav \
    --broll input/broll/product_demo.mp4 \
    --output edit/clips/seg_01.mp4 \
    --preview

# 生成字幕（文案文本 + 音频时长，无需 ASR）
python helpers/subtitles.py \
    --text "你的文案" \
    --audio edit/segments/seg_01.wav \
    --output edit/transcripts/seg_01.srt

# 拼接（有字幕）
python helpers/concat_final.py \
    --clips-dir edit/clips \
    --srt-dir edit/transcripts \
    --output edit/final.mp4
```

---

## 与 dbs 集成

工作流内置对 [dontbesilent](https://github.com/dontbesilent) 系列 skill 的可选调用：

- **`/dbs-hook`** — 诊断开头，生成 10-15 个优化方案
- **`/dbs-content`** — 五维诊断：文字洁癖、封面/标题、表达效率、认知落差、AI 辅助建议

两步均可跳过，直接进入 TTS 合成。

---

## 依赖

- Python ≥ 3.10
- `ffmpeg`（系统级）
- `dashscope>=1.24.6`（TTS）
- `requests`

> `qiniu` 不在默认依赖里。video-cut 的字幕直接从文案文本生成，无需 ASR，无需云存储。
