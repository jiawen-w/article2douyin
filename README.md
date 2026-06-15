# article2douyin

把一篇**图文文章**（公众号链接 / 网页 / 本地 md·html·txt）自动变成一条**符合抖音传播规律的竖屏视频**。

## 它会做什么

1. **解析文章** — 按原文顺序提取正文和配图（内置微信公众号正文解析）。
2. **视觉识图** — 用视觉大模型逐张描述配图内容，让 AI 按画面内容**精准选配图**，避免图文对不上。
3. **AI 改写爆款脚本** — 黄金 3 秒钩子 + 大字花字、短句快节奏、结尾争议互动钩子；自动产出标题和话题标签。
4. **Edge-TTS 配音** — 免费，默认 +28% 抖音快节奏，多种音色可选。
5. **ffmpeg 合成** — 1080×1920 竖屏、模糊填充背景、防抖 Ken Burns 缓推、大字硬字幕、顶部标题。
6. **自动配 BGM** — 从 `bgm/` 随机选一首，人声出现时背景音乐自动闪避（sidechain ducking）。
7. 输出成片 + `发布文案.txt`（标题 / 花字 / 话题）。

## 安装

```bash
python -m venv .venv && source .venv/bin/activate
pip install anthropic edge-tts requests beautifulsoup4
# 系统需安装 ffmpeg：brew install ffmpeg
```

## 配置

```bash
cp config_local.example.py config_local.py
# 编辑 config_local.py 填入你的 API Key（模型需支持视觉）
```

## 使用

```bash
# 交互式（推荐）：依次选来源 / 音色 / 语速 / BGM
python article2douyin.py

# 一步出片
python article2douyin.py "https://mp.weixin.qq.com/s/xxxx"
python article2douyin.py ~/Documents/我的文章.md
```

成片输出到 `~/Downloads/article2douyin/<标题>/`。

## 背景音乐版权

`bgm/` 内的曲目来自 [archive.org](https://archive.org) 上的 Jamendo 收录，采用 **CC-BY** 授权：

- *Pop Dance (Loop)* — TimTaj
- *Bright Pop (60 Sec)* — TimTaj
- *Fun Energetic Indie* — ABSounds

如用于商业发布，请遵循 CC-BY 注明原作者，或替换为你自有授权的音乐（放进 `bgm/` 即可被随机选用）。
