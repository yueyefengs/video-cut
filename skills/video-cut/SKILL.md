# video-cut：口播文案 → 视频剪辑

## 核心理念

你拿到的是一段口播文案，目标是输出一个可发布的视频。

流程：文案 → (可选优化) → 分段 + B-roll 匹配 → TTS 合成 → 逐段渲染 → 拼接 + 字幕 → final.mp4

**B-roll 匹配靠文件名语义。** 让用户给 B-roll 素材起描述性文件名，Claude 读文件名列表，按语义匹配到文案段落。

---

## 目录结构

```
~/code/video-cut/
├── helpers/
│   ├── tts.py                # Ali qwen3-tts-flash 语音合成
│   ├── subtitles.py          # 按文案文本估算 SRT（无需 ASR）
│   ├── compose_segment.py    # 单段：B-roll + TTS → MP4
│   └── concat_final.py       # 拼接 + 字幕 → final.mp4
├── input/
│   └── broll/                # 用户放 B-roll 素材，文件名即语义
├── edit/                     # 所有生成物
│   ├── project.md            # 会话记录（每次追加）
│   ├── segments.json         # 分段 + B-roll 匹配决策
│   ├── segments/             # 逐段 TTS 音频
│   ├── transcripts/          # 逐段字幕 SRT（按文案文本估算时间戳）
│   ├── clips/                # 逐段渲染 MP4
│   ├── master.srt            # 最终字幕文件
│   └── final.mp4             # 最终输出
├── .env
└── pyproject.toml
```

---

## 工作流程

### Phase 0：启动检查

1. 读 `edit/project.md`（如果存在），一句话总结上次进度。
2. 确认 `.env` 包含 `DASHSCOPE_API_KEY`。

---

### Phase 1：接收文案

问用户：**「把口播文案发给我」**

收到文案后，先简要描述你看到的内容：字数、大致结构、有没有明显问题。

然后询问（一次问完）：
- 声音风格偏好（语速、语调，可选）
- 是否需要字幕（默认要）

---

### Phase 2：内容优化（按已安装 skill 条件触发）

**先检查当前会话的可用 skill 列表（system-reminder 中的 available skills）：**

- 若列表包含 `dbs:dbs-hook` → `hook_available = true`
- 若列表包含 `dbs:dbs-content` → `content_available = true`

**若两者都不可用：** 静默跳过本阶段，不向用户提及，直接进入 Phase 3。

**若至少一个可用：** 告知用户哪些诊断工具可用，询问是否运行：

```
检测到以下内容优化工具：
  [如果可用] 1. /dbs-hook — 诊断开头，生成 10-15 个优化方案
  [如果可用] 2. /dbs-content — 五维诊断（文字洁癖、封面、表达效率、认知落差等）

输入「跳过」直接进入下一步。
```

用户选择后：
- 若选 dbs-hook：用 Skill 工具调用 `dbs:dbs-hook`，把文案作为输入，等用户确认最终开头后更新文案
- 若选 dbs-content：用 Skill 工具调用 `dbs:dbs-content`，等用户确认是否修改文案
- 用户确认最终文案后继续

---

### Phase 3：扫描 B-roll 素材

```bash
ls ~/code/video-cut/input/broll/
```

列出所有视频文件及其文件名。如果目录为空，提示用户：
```
input/broll/ 目录为空。请把 B-roll 视频放进去，文件名用描述性命名：
  product_demo.mp4       ← 产品展示
  lifestyle_outdoor.mp4  ← 户外生活场景
  cta_phone.mp4          ← 手持手机/CTA 场景

放好后告诉我，继续分段。
```

---

### Phase 4：分段 + B-roll 匹配

根据文案内容和 B-roll 文件名列表，生成 `segments.json`：

**分段原则：**
- 按语义节奏分段，一段通常 1-3 句话（10-30 秒）
- 分段不要太碎——3-6 段为宜，除非文案很长
- 每段有独立的情绪或信息点

**匹配原则：**
- 语义最接近的 B-roll 优先
- 同一个 B-roll 可以多段复用
- 匹配理由必须说得通（不要硬凑）

生成 `segments.json` 后，**展示给用户确认：**

```
分段方案（共 N 段，总时长约 X 秒）：

  段落 1 [开头]：「你知道为什么 90% 的人...」
    → B-roll: lifestyle_outdoor.mp4   理由：户外场景配开头渲染氛围

  段落 2 [产品介绍]：「这款产品的核心是...」
    → B-roll: product_demo.mp4        理由：直接展示产品

  段落 3 [CTA]：「现在扫码...」
    → B-roll: cta_phone.mp4           理由：手机画面配行动引导

确认后开始 TTS 合成。如需调整，直接说。
```

用户确认后，把方案写入 `edit/segments.json`：

```json
{
  "voice": "Cherry",
  "instructions": null,
  "segments": [
    {
      "id": "01",
      "beat": "开头",
      "text": "你知道为什么 90% 的人...",
      "broll": "input/broll/lifestyle_outdoor.mp4"
    }
  ]
}
```

---

### Phase 5：TTS 合成

逐段调用 TTS，输出到 `edit/segments/seg_01.wav` 等：

```bash
cd ~/code/video-cut

python helpers/tts.py "段落文本" \
    --voice Cherry \
    --output edit/segments/seg_01.wav

# 如果有语调指令：
python helpers/tts.py "段落文本" \
    --voice Cherry \
    --instructions "语速稍快，结尾语调上扬" \
    --output edit/segments/seg_01.wav
```

完成后报告每段音频时长。

---

### Phase 6：逐段渲染

逐段合成 B-roll + TTS 音频：

```bash
python helpers/compose_segment.py \
    --tts edit/segments/seg_01.wav \
    --broll input/broll/product_demo.mp4 \
    --output edit/clips/seg_01.mp4
```

---

### Phase 7：生成字幕（可选）

字幕不需要 ASR——我们已经有文案文本，只需要时间戳。
对每段 TTS 音频，用文案文本 + 音频时长直接估算字幕时间：

```bash
python helpers/subtitles.py \
    --text "段落文本" \
    --audio edit/segments/seg_01.wav \
    --output edit/transcripts/seg_01.srt
```

如果用户不需要字幕，跳过此步，`concat_final.py` 加 `--no-subtitles` 参数。

---

### Phase 8：拼接 + 字幕

```bash
# 有字幕
python helpers/concat_final.py \
    --clips-dir edit/clips \
    --srt-dir edit/transcripts \
    --output edit/final.mp4

# 无字幕
python helpers/concat_final.py \
    --clips-dir edit/clips \
    --output edit/final.mp4 \
    --no-subtitles
```

---

### Phase 9：自检

用 ffprobe 验证输出：

```bash
ffprobe -v quiet -print_format json -show_format edit/final.mp4
```

检查：
- 时长是否与各段 TTS 时长之和吻合（误差 < 1s）
- 文件大小是否合理（>= 1 MB）

然后报告：输出路径、总时长、文件大小。

---

### Phase 10：持久化

追加到 `edit/project.md`：

```markdown
## Session N — YYYY-MM-DD

**文案摘要**：[一句话]
**分段方案**：N 段，总时长约 X 秒
**声音**：voice=Cherry，指令=[...]
**B-roll 匹配**：[简述各段匹配]
**字幕**：有/无
**输出**：edit/final.mp4 (X MB, X.Xs)
```

---

## Hard Rules（继承自 video-use）

1. **字幕最后叠加** — concat_final.py 在拼接后才烧字幕
2. **30ms 音频淡入淡出** — compose_segment.py 已内置，每段边界防爆音
3. **用户确认分段方案后才执行 TTS** — 不要在用户看到方案前就开始合成
4. **B-roll 匹配理由必须说得通** — 语义匹配，不是随机分配

---

## 快捷命令参考

```bash
# 查看可用声音
python helpers/tts.py --list-voices

# 单段测试
python helpers/tts.py "测试文本" --voice Cherry --output edit/test.wav

# 预览模式（720p 快速）
python helpers/compose_segment.py --tts edit/segments/seg_01.wav \
    --broll input/broll/demo.mp4 --output edit/clips/seg_01.mp4 --preview

# 拼接预览
python helpers/concat_final.py --clips-dir edit/clips \
    --output edit/preview.mp4 --preview --no-subtitles
```

---

## .env 配置说明

```
DASHSCOPE_API_KEY=sk-xxx          # 必须，TTS 用

# 字幕不依赖 Qiniu，直接从文案文本生成。
# Qiniu 仅在需要对原始素材做 ASR 时才需要（video-cut 默认不需要）。
```

---

## B-roll 命名建议

告知用户：**文件名即语义，命名越描述性，匹配越准确。**

好的命名：
- `product_close_shot.mp4`
- `person_walking_street.mp4`
- `coffee_morning_table.mp4`
- `phone_scrolling_app.mp4`

差的命名：
- `VID_20240101.mp4`
- `clip1.mp4`
- `footage.mp4`
