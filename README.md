# video-cut

口播文案 + B-roll 素材 → 可发布视频。

由 Claude Code 驱动，Ali TTS 配音，自动分段配图，支持字幕生成。

---

## 工作流

```
口播文案
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

**4. 安装 skill**

**Claude Code**

```bash
# 全局安装（推荐，任意目录可用）
cp -r skills/video-cut ~/.claude/skills/

# 或用符号链接（改动实时生效）
ln -s "$(pwd)/skills/video-cut" ~/.claude/skills/video-cut
```

**Codex**

```bash
# 全局安装
cp -r skills/video-cut ~/.codex/skills/

# 或符号链接
ln -s "$(pwd)/skills/video-cut" ~/.codex/skills/video-cut
```

---

**5. 在 Claude Code 里使用**

在项目目录下打开 Claude Code：

```bash
cd ~/code/video-cut
claude
```

输入 `/video-cut` 启动工作流，Claude 会引导你完成以下步骤：

1. **发送文案** — 把口播文案粘贴给 Claude，它会分析字数、结构和潜在问题
2. **（可选）内容优化** — 若安装了 `dbs` 套件，可运行 `/dbs-hook` 优化开头或 `/dbs-content` 做五维诊断
3. **确认分段方案** — Claude 展示 N 段划分 + 每段对应的 B-roll，你确认后才开始合成
4. **TTS 合成** — 逐段生成语音，报告每段时长
5. **渲染 + 拼接** — 自动完成，输出 `edit/final.mp4`

> **注意**：skill 需要 Claude Code CLI（`claude` 命令），不支持 Claude.ai 网页版。

---

## Helpers

| 文件 | 作用 |
|------|------|
| `helpers/tts.py` | Ali qwen3-tts-flash 语音合成 |
| `helpers/subtitles.py` | 文案文本 + 音频时长 → SRT 字幕 |
| `helpers/compose_segment.py` | 单段 B-roll + TTS → MP4 |
| `helpers/concat_final.py` | 拼接所有段落 + 字幕 + loudnorm |
| `helpers/asr.py` | ⚠️ 实验性备用：Paraformer v2 转录（需 Qiniu，不在主流程） |

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

## 与 dbs 集成（可选，按需检测）

若当前 Claude Code 环境安装了 [dontbesilent](https://github.com/dontbesilent) skill 套件，工作流会在 Phase 2 自动检测并提供：

- **`/dbs-hook`** — 诊断开头，生成 10-15 个优化方案
- **`/dbs-content`** — 五维诊断：文字洁癖、封面/标题、表达效率、认知落差、AI 辅助建议

未安装时 Phase 2 静默跳过，不影响主流程。

---

## 依赖

- Python ≥ 3.10
- `ffmpeg`（系统级）
- `dashscope>=1.24.6`（TTS）
- `requests`

> `qiniu` 不在默认依赖里。video-cut 的字幕直接从文案文本生成，无需 ASR，无需云存储。
