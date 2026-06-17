# -*- coding: utf-8 -*-
"""
article2douyin.py — 把图文文章变成符合抖音传播规律的竖屏视频

流程：
  1. 解析文章（URL / 本地 md / html / txt），按原文顺序提取文字 + 配图
  2. 视觉模型逐图识内容，让 AI 按画面内容精准选配图（图文对应）
  3. AI 改写成抖音爆款脚本：黄金3秒钩子 + 大字花字、短句快节奏、结尾争议钩子
  4. Edge-TTS 逐镜配音（免费，默认 +28% 快节奏）
  5. ffmpeg 合成：1080x1920 竖屏、模糊填充 + 防抖 Ken Burns、大字硬字幕、顶部标题
  6. 自动混入抖音风背景音乐（bgm/ 目录随机选，带淡入淡出）
  7. 输出成片 + 发布文案（标题 / 花字 / 话题标签）

用法：
  .venv/bin/python article2douyin.py <文章URL或本地文件路径>
  .venv/bin/python article2douyin.py https://mp.weixin.qq.com/s/xxxx
  .venv/bin/python article2douyin.py ~/Documents/我的文章.md
"""

import asyncio
import base64
import json
import os
import re
import subprocess
import sys
from pathlib import Path

# ============================================================
# 1. 配置常量
# ============================================================
# 密钥从 config_local.py 读取（该文件不提交 git）；缺失时回退到环境变量
try:
    from config_local import AI_BASE_URL, AI_API_KEY, AI_MODEL
except ImportError:
    AI_BASE_URL = os.environ.get("AI_BASE_URL", "https://ark.cn-beijing.volces.com/api/coding")
    AI_API_KEY  = os.environ.get("AI_API_KEY", "")
    AI_MODEL    = os.environ.get("AI_MODEL", "doubao-seed-2.0-pro")
    if not AI_API_KEY:
        sys.exit("缺少 API Key：请在同目录建 config_local.py（参考 config_local.example.py）")

SCRIPT_DIR  = Path(__file__).resolve().parent
OUT_ROOT    = Path.home() / "Downloads" / "article2douyin"

TTS_VOICE   = "zh-CN-YunjianNeural"   # 有力解说男声；女声可换 zh-CN-XiaoxiaoNeural
TTS_RATE    = "+28%"                  # 抖音快节奏；想更快可调到 +35%

VIDEO_W, VIDEO_H = 1080, 1920
FPS         = 30
SCENE_PAD   = 0.18                    # 每镜结尾留白秒数（越小越紧凑）

# 背景音乐：bgm/ 目录里放抖音风曲子，默认自动随机选一首混入
BGM_DIR     = SCRIPT_DIR / "bgm"
BGM_PATH    = None                    # 指定某首则用它；None 时从 BGM_DIR 随机选
USE_BGM     = True                    # 默认自动配 BGM
BGM_VOLUME  = 0.09                    # BGM 基础音量（人声时还会自动闪避压更低）

# Ken Burns：缓慢推近，KB_SUPERSCALE 越大抖动越小（牺牲一点内存/速度）
KB_ZOOM       = 0.06                  # 整镜放大幅度（6%），幅度小+超采样=不抖
KB_SUPERSCALE = 4                     # 缩放超采样倍数，消除 zoompan 像素抖动

SUB_FONT    = "PingFang SC"
HTTP_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
}

# ============================================================
# 2. Prompt 模板
# ============================================================
SCRIPT_PROMPT = """你是抖音千万级爆款操盘手，精通完播率和互动率的底层逻辑。请把下面这篇图文文章改编成一条 35~60 秒的抖音口播爆款脚本。

【配图清单】（每张图我已用 AI 看过内容，描述如下，请严格按内容匹配，别张冠李戴）：
{captions}

【短视频素材清单】（共 {clip_count} 条，从原文里下载的真实短视频，描述如下；用作分镜画面会比静图更生动）：
{clips}

【黄金 3 秒 · 第一镜钩子】（决定生死，必须满足其一）：
- 反常识暴论：抛出一个和大众认知相反、让人想反驳的结论。
- 利益钩子：直接点破"看完你能得到什么/避免什么坑"。
- 悬念缺口：制造信息差，让人必须看下去才知道答案。
- 严禁出现"大家好""今天聊聊""带你了解""不知道大家"这类废话开场。第一句话直接开炸。

【节奏与口播】：
1. 每个分镜一句话，≤22 个字，纯口语，像跟朋友吐槽，删掉所有书面腔、形容词堆砌、官话。
2. 信息密度拉满：最反直觉、最有冲突感的干货前置，按"钩子→冲突展开→高潮反转→金句收尾"排。
3. 数字、对比、具体案例优先（如"省了30%""贵3倍""1.1万亿"），比抽象描述更抓人。
4. 全片 9~13 个分镜，口播总字数 160~260 字，控制在 60 秒内。

【结尾 · 最后一镜】（拉互动率）：
- 用争议性提问 / 站队选择 / 反问，逼观众评论，例如"你站哪边，评论区吵起来""这事你能接受吗"。
- 别用"谢谢观看""记得点赞关注"这种无效结尾。

【硬性禁止 · 一律剔除，绝不出现在脚本里】：
1. 作者/编辑/记者人名或署名（如"作者是XX""XX编辑""XX报道"）、媒体出处署名。
2. 任何广告和推广内容，哪怕原文里有：会议/大会/论坛/峰会的预告与报名（如"X月X地有XX大会""扫码报名""购票""嘉宾阵容"）、活动招募、课程/社群/星球引流、产品促销、优惠折扣、抽奖福利。
3. 任何品牌方/赞助商/合作方的露出与背书（如"由XX赞助""XX提供支持""XX冠名""关注XX公众号"）、二维码、外部链接、联系方式。
只保留对观众有价值的事实、观点和干货；上述软广硬广信息直接当不存在，不要改写、不要顺带提一句。

【画面匹配】：每个分镜要配一个画面，二选一：
- 优先用短视频素材：clip 字段填最贴合该句的视频编号（1~{clip_count}），同时 image 填 null。视频比静图生动，有合适的就尽量用。
- 没有合适视频时用配图：image 字段填配图编号（1~{image_count}），clip 填 null。
- 两者都对不上就都填 null（会用上一个画面兜底）。
必须严格按上面的描述匹配内容，别张冠李戴；同一素材别连续重复用。会议海报、报名页、品牌LOGO、二维码、嘉宾名单这类广告图一律不要选。

【发布物料】：
- title：≤18 字爆款标题，带情绪/悬念/数字，能和第一镜钩子呼应。
- hook_text：第一镜的大字幕花字（≤12 字），比口播更狠更短，砸在屏幕中央那种。
- hashtags：5~6 个精准抖音话题词（不带 # 号），含 1~2 个大流量泛标签 + 垂类标签。

只输出 JSON，不要任何解释或 markdown 围栏：
{{
  "title": "发布标题",
  "hook_text": "开场花字",
  "hashtags": ["话题1", "话题2"],
  "scenes": [
    {{"text": "口播文案", "clip": 2, "image": null}},
    {{"text": "口播文案", "clip": null, "image": 1}}
  ]
}}

文章正文如下（[图片N] 是配图在原文出现的位置）：
---
{article}
---"""

CAPTION_PROMPT = """判断并描述这张图，用于短视频选配图：
1) 如果它主要是品牌LOGO、公众号/媒体名片或推荐卡（如"夕小瑶科技说""新智元""量子位""极客公园"等账号名+头像那种卡片）、App下载二维码、应用商店徽章(App Store / Google Play)、关注引导图或纯广告横幅——第一行只输出四个字：这是LOGO
2) 否则用一句话（≤20字）客观描述画面内容（人物/产品/图表/场景）。
只输出结果，不要解释、不要前缀。"""

# ============================================================
# 3. 工具函数
# ============================================================

def ensure_package(pkg, import_name=None):
    name = import_name or pkg
    try:
        __import__(name)
    except ImportError:
        print(f"[setup] 安装依赖 {pkg} ...")
        subprocess.run([sys.executable, "-m", "pip", "install", pkg], check=True)
        __import__(name)


def run_cmd(cmd, **kw):
    """跑外部命令，失败时打印 stderr 再抛错。"""
    proc = subprocess.run(cmd, capture_output=True, text=True, **kw)
    if proc.returncode != 0:
        print(proc.stderr[-3000:])
        raise RuntimeError(f"命令失败: {cmd[0]} ...")
    return proc


def ffprobe_duration(path):
    proc = run_cmd([
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "csv=p=0", str(path),
    ])
    return float(proc.stdout.strip())


def _copy_into(path, dest_dir):
    """把 path 复制进 dest_dir，返回新路径；path 为 None 时原样返回 None。"""
    if not path:
        return None
    dest = dest_dir / Path(path).name
    dest.write_bytes(Path(path).read_bytes())
    return dest


def slugify(text, max_len=24):
    text = re.sub(r"[^\w一-鿿]+", "_", text).strip("_")
    return text[:max_len] or "article"


def format_ass_time(sec):
    h = int(sec // 3600)
    m = int(sec % 3600 // 60)
    s = sec % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def extract_json(text):
    """从 AI 回复里抠出 JSON（容忍 ```json 围栏和前后废话）。"""
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    if m:
        return json.loads(m.group(1))
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise ValueError(f"AI 回复中找不到 JSON：{text[:200]}")
    return json.loads(m.group(0))


def split_subtitle_chunks(text, max_chars=14):
    """把一句口播按标点切成短字幕块；超长再切，但不切断英文单词/数字串。"""

    # 只把 ASCII 字母/数字/.%- 视作不可切断的词（中文按字可切，故排除）
    tok = re.compile(r"[A-Za-z0-9.%\-]")

    def safe_cut(s):
        """在 ≤max_chars 处找一个不劈开英文单词/数字串的切点。"""
        cut = max_chars
        if cut < len(s) and tok.match(s[cut - 1]) and tok.match(s[cut]):
            back = cut
            while back > 1 and tok.match(s[back - 1]):
                back -= 1
            if back >= max_chars // 2:        # 回退别太狠，否则就硬切
                cut = back
        return cut

    parts = [p for p in re.split(r"[，。！？；、,!?;：:…\s]+", text) if p]
    chunks = []
    for p in parts:
        while len(p) > max_chars:
            cut = safe_cut(p)
            chunks.append(p[:cut])
            p = p[cut:]
        if p:
            chunks.append(p)
    return chunks or [text]

# ============================================================
# 4. Step 函数
# ============================================================

def parse_article(source, workdir):
    """返回 (带 [图片N] 标记的正文, [图片路径列表], [视频路径列表])。"""
    if re.match(r"^https?://", source):
        return parse_url(source, workdir)
    path = Path(source).expanduser()
    if not path.exists():
        raise FileNotFoundError(f"找不到文件：{path}")
    if path.suffix.lower() in (".md", ".markdown"):
        return (*parse_markdown(path, workdir), [])
    if path.suffix.lower() in (".html", ".htm"):
        return (*parse_html_text(path.read_text(encoding="utf-8"), path.parent, workdir), [])
    # 纯文本：无图无视频
    return path.read_text(encoding="utf-8"), [], []


def parse_url(url, workdir):
    ensure_package("requests")
    ensure_package("beautifulsoup4", "bs4")
    import requests

    print(f"[parse] 抓取网页：{url}")
    resp = requests.get(url, headers=HTTP_HEADERS, timeout=30)
    resp.raise_for_status()
    resp.encoding = resp.apparent_encoding or "utf-8"
    article, images = parse_html_text(resp.text, url, workdir)
    # 微信公众号文章里若嵌了短视频，用浏览器抓真实直链下载下来当素材
    videos = fetch_embedded_videos(resp.text, url, workdir)
    return article, images, videos


def parse_html_text(html, base, workdir):
    """base 是 URL 或本地目录，用来解析图片相对地址。"""
    ensure_package("beautifulsoup4", "bs4")
    from bs4 import BeautifulSoup
    from urllib.parse import urljoin

    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header"]):
        tag.decompose()
    # 微信公众号正文在 #js_content，普通网页找 article 或 body
    root = (soup.find(id="js_content") or soup.find("article")
            or soup.find(class_=re.compile(r"(article|content|post)", re.I))
            or soup.body or soup)

    lines, image_urls = [], []
    for node in root.find_all(["p", "h1", "h2", "h3", "li", "img", "section", "blockquote"]):
        if node.name == "img":
            src = node.get("data-src") or node.get("src") or ""
            if not src or src.startswith("data:"):
                continue
            if re.search(r"\.(svg|gif)(\?|$)", src, re.I):
                continue
            if isinstance(base, str) and re.match(r"^https?://", base):
                src = urljoin(base, src)
            image_urls.append(src)
            lines.append(f"[图片{len(image_urls)}]")
        else:
            if node.find(["p", "section", "img"]):   # 只取叶子节点，避免重复
                continue
            text = node.get_text(" ", strip=True)
            if text:
                lines.append(text)

    article = "\n".join(lines)
    images = download_images(image_urls, base, workdir)
    return article, images


def parse_markdown(path, workdir):
    text = path.read_text(encoding="utf-8")
    image_refs = []

    def repl(m):
        image_refs.append(m.group(1))
        return f"[图片{len(image_refs)}]"

    article = re.sub(r"!\[[^\]]*\]\(([^)\s]+)[^)]*\)", repl, text)
    images = download_images(image_refs, path.parent, workdir)
    return article, images


def download_images(refs, base, workdir):
    """refs 是 URL 或相对路径列表；下载/复制到 workdir，返回有效本地路径。"""
    img_dir = workdir / "images"
    img_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for i, ref in enumerate(refs, 1):
        dest = img_dir / f"img_{i:02d}.jpg"
        try:
            if re.match(r"^https?://", ref):
                ensure_package("requests")
                import requests
                r = requests.get(ref, headers=HTTP_HEADERS, timeout=30)
                r.raise_for_status()
                dest.write_bytes(r.content)
            else:
                src = (Path(base) / ref).expanduser() if not Path(ref).is_absolute() else Path(ref)
                if not src.exists():
                    paths.append(None)
                    continue
                dest.write_bytes(src.read_bytes())
            if dest.stat().st_size < 8 * 1024:      # 太小的多半是图标/跟踪像素
                paths.append(None)
                continue
            # 统一转成标准 jpg，顺便剔除损坏图片
            run_cmd(["ffmpeg", "-y", "-i", str(dest), "-frames:v", "1",
                     "-q:v", "2", str(dest) + ".tmp.jpg"])
            os.replace(str(dest) + ".tmp.jpg", dest)
            paths.append(dest)
        except Exception as e:
            print(f"[image] 第{i}张图获取失败，跳过：{e}")
            paths.append(None)
    valid = [p for p in paths if p]
    print(f"[image] 有效配图 {len(valid)}/{len(refs)} 张")
    return paths


def fetch_embedded_videos(html, url, workdir, max_videos=12):
    """微信文章里嵌的短视频：用 Playwright 拦截 mpvideo.qpic.cn 直链并下载。
    返回下载好的本地视频路径列表（无视频或失败则返回 []）。"""
    n_iframe = len(set(re.findall(r'data-mpvid="(wxv_\d+)"', html)))
    if n_iframe == 0:
        return []
    try:
        ensure_package("playwright")
        from playwright.sync_api import sync_playwright
    except Exception as e:
        print(f"[video] 检测到 {n_iframe} 条嵌入视频，但 Playwright 不可用，跳过：{e}")
        return []

    print(f"[video] 检测到 {n_iframe} 条嵌入视频，启动浏览器抓取直链 ...")
    vid_dir = workdir / "videos"
    vid_dir.mkdir(parents=True, exist_ok=True)
    seen = {}

    def on_req(req):
        m = re.search(r"mpvideo\.qpic\.cn/([0-9a-z]+)\.", req.url)
        if m and m.group(1) not in seen:
            seen[m.group(1)] = req.url

    paths = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            ctx = browser.new_context(user_agent=HTTP_HEADERS["User-Agent"])
            page = ctx.new_page()
            page.on("request", on_req)
            page.goto(url, wait_until="networkidle", timeout=45000)
            for _ in range(8):                       # 滚动触发懒加载视频
                page.mouse.wheel(0, 1500)
                page.wait_for_timeout(700)
            page.wait_for_timeout(2500)
            print(f"[video] 抓到 {len(seen)} 个视频直链，开始下载 ...")
            for i, (vid, vurl) in enumerate(list(seen.items())[:max_videos], 1):
                try:
                    resp = ctx.request.get(
                        vurl, headers={"referer": "https://mp.weixin.qq.com/"},
                        timeout=90000)
                    data = resp.body()
                    if len(data) < 50 * 1024:        # 太小多半不是有效视频
                        continue
                    dest = vid_dir / f"vid_{i:02d}.mp4"
                    dest.write_bytes(data)
                    paths.append(dest)
                    print(f"[video] 视频{i}: {len(data)//1024} KB")
                except Exception as e:
                    print(f"[video] 视频{i} 下载失败：{e}")
            browser.close()
    except Exception as e:
        print(f"[video] 抓取出错，本次不用视频素材：{e}")
    print(f"[video] 成功下载 {len(paths)} 条视频素材")
    return paths


def video_thumbnail(video_path, workdir, index):
    """抽取视频中段一帧做缩略图，用于视觉识别内容。"""
    thumb = workdir / "videos" / f"thumb_{index:02d}.jpg"
    try:
        dur = ffprobe_duration(video_path)
        ts = max(0.1, dur * 0.4)
        run_cmd(["ffmpeg", "-y", "-ss", f"{ts:.2f}", "-i", str(video_path),
                 "-frames:v", "1", "-q:v", "2", str(thumb)])
        return thumb if thumb.exists() else None
    except Exception:
        return None


def _vision_describe(client, img_path):
    """对一张图片调用视觉模型，返回去换行的描述文本。"""
    img_b64 = base64.b64encode(Path(img_path).read_bytes()).decode()
    msg = client.messages.create(
        model=AI_MODEL, max_tokens=128,
        messages=[{"role": "user", "content": [
            {"type": "image", "source": {"type": "base64",
                "media_type": "image/jpeg", "data": img_b64}},
            {"type": "text", "text": CAPTION_PROMPT},
        ]}],
    )
    return msg.content[0].text.strip().replace("\n", " ")


def ai_caption_images(images):
    """给每张有效图配描述并识别品牌LOGO。
    返回 (captions={编号:描述}, brand_idxs={品牌/LOGO图编号})。"""
    ensure_package("anthropic")
    import anthropic

    client = anthropic.Anthropic(api_key=AI_API_KEY, base_url=AI_BASE_URL)
    captions, brand_idxs = {}, set()
    for idx, path in enumerate(images, 1):
        if not path:
            continue
        try:
            cap = _vision_describe(client, path)
            if "LOGO" in cap.upper() or cap.startswith("这是LOGO"):
                brand_idxs.add(idx)
                print(f"[vision] 图{idx}: [品牌/LOGO，已排除]")
            else:
                captions[idx] = cap[:30]
                print(f"[vision] 图{idx}: {cap[:30]}")
        except Exception as e:
            print(f"[vision] 图{idx} 描述失败：{e}")
    return captions, brand_idxs


def ai_caption_videos(videos, workdir):
    """给每条视频抽帧识别内容，返回 {编号: 描述}。"""
    if not videos:
        return {}
    ensure_package("anthropic")
    import anthropic

    client = anthropic.Anthropic(api_key=AI_API_KEY, base_url=AI_BASE_URL)
    captions = {}
    for idx, vpath in enumerate(videos, 1):
        thumb = video_thumbnail(vpath, workdir, idx)
        if not thumb:
            continue
        try:
            cap = _vision_describe(client, thumb)
            cap = re.sub(r"^这是LOGO\s*", "", cap)[:30]
            captions[idx] = cap
            print(f"[vision] 视频{idx}: {cap}")
        except Exception as e:
            print(f"[vision] 视频{idx} 描述失败：{e}")
    return captions


def ai_make_script(article, image_count, captions, video_caps=None):
    ensure_package("anthropic")
    import anthropic

    video_caps = video_caps or {}
    if captions:
        caption_block = "\n".join(f"图片{i}：{captions[i]}"
                                  for i in range(1, image_count + 1) if i in captions)
    else:
        caption_block = "（无可用配图）"

    if video_caps:
        clip_block = "\n".join(f"视频{i}：{video_caps[i]}"
                               for i in sorted(video_caps))
    else:
        clip_block = "（本文没有可用短视频）"

    print(f"[ai] 调用 {AI_MODEL} 生成抖音脚本 ...")
    client = anthropic.Anthropic(api_key=AI_API_KEY, base_url=AI_BASE_URL)
    prompt = SCRIPT_PROMPT.format(article=article[:12000],
                                  image_count=max(image_count, 1),
                                  captions=caption_block,
                                  clips=clip_block,
                                  clip_count=len(video_caps))
    msg = client.messages.create(
        model=AI_MODEL, max_tokens=4096,
        messages=[{"role": "user", "content": prompt}],
    )
    data = extract_json(msg.content[0].text)
    assert data.get("scenes"), "AI 没有返回分镜"
    nclip = sum(1 for s in data["scenes"] if s.get("clip"))
    print(f"[ai] 标题《{data['title']}》，花字「{data.get('hook_text', '')}」，"
          f"共 {len(data['scenes'])} 个分镜（{nclip} 个用视频素材）")
    return data


def tts_scenes(scenes, workdir):
    """逐镜配音，返回 [(mp3路径, 时长)]。"""
    ensure_package("edge-tts", "edge_tts")
    import edge_tts

    audio_dir = workdir / "audio"
    audio_dir.mkdir(exist_ok=True)

    async def gen():
        results = []
        for i, scene in enumerate(scenes, 1):
            mp3 = audio_dir / f"scene_{i:02d}.mp3"
            await edge_tts.Communicate(scene["text"], TTS_VOICE, rate=TTS_RATE).save(str(mp3))
            dur = ffprobe_duration(mp3)
            results.append((mp3, dur))
            print(f"[tts] 镜{i}: {dur:.1f}s  {scene['text'][:20]}")
        return results

    return asyncio.run(gen())


def pick_visual(scene, images, videos):
    """解析分镜画面，返回 ('clip', 路径) / ('image', 路径) / (None, None)。
    视频优先（更生动），其次配图。"""
    cidx = scene.get("clip")
    if cidx and 1 <= cidx <= len(videos) and videos[cidx - 1]:
        return "clip", videos[cidx - 1]
    iidx = scene.get("image")
    if iidx and 1 <= iidx <= len(images) and images[iidx - 1]:
        return "image", images[iidx - 1]
    return None, None


def _kenburns_vf(frames, index):
    """图片 Ken Burns 滤镜串：超采样 + 缓慢线性缩放，防抖。"""
    zmax = 1.0 + KB_ZOOM
    if index % 2 == 1:
        zoom_expr = f"min({zmax:.4f},1.0+{KB_ZOOM:.4f}*on/{frames})"
    else:
        zoom_expr = f"max(1.0,{zmax:.4f}-{KB_ZOOM:.4f}*on/{frames})"
    sw, sh = VIDEO_W * KB_SUPERSCALE, VIDEO_H * KB_SUPERSCALE
    return (
        f"[0:v]scale={VIDEO_W}:{VIDEO_H}:force_original_aspect_ratio=increase,"
        f"crop={VIDEO_W}:{VIDEO_H},boxblur=30:5[bg];"
        f"[0:v]scale={VIDEO_W}:{VIDEO_H}:force_original_aspect_ratio=decrease[fg];"
        f"[bg][fg]overlay=(W-w)/2:(H-h)/2,scale={sw}:{sh}:flags=bicubic,"
        f"zoompan=z='{zoom_expr}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
        f":d={frames}:s={VIDEO_W}x{VIDEO_H}:fps={FPS},format=yuv420p[v]"
    )


def build_scene_clip(kind, visual, mp3, dur, index, workdir):
    """单镜视频：图片走 Ken Burns；视频素材模糊填充铺满竖屏并截到口播时长；配该镜音频。"""
    out = workdir / "clips" / f"clip_{index:02d}.mp4"
    out.parent.mkdir(exist_ok=True)
    total = dur + SCENE_PAD
    frames = int(total * FPS) + 1

    if kind == "clip":
        # 视频素材：从中段取一段，模糊背景填充 + 居中铺前景，保留原声但静音（用口播）
        src_dur = ffprobe_duration(visual)
        start = max(0.0, (src_dur - total) * 0.35) if src_dur > total else 0.0
        vf = (
            f"[0:v]scale={VIDEO_W}:{VIDEO_H}:force_original_aspect_ratio=increase,"
            f"crop={VIDEO_W}:{VIDEO_H},boxblur=30:5,setsar=1[bg];"
            f"[0:v]scale={VIDEO_W}:{VIDEO_H}:force_original_aspect_ratio=decrease,setsar=1[fg];"
            f"[bg][fg]overlay=(W-w)/2:(H-h)/2,fps={FPS},format=yuv420p[v]"
        )
        # 视频比口播短时循环播放铺满时长
        inputs = ["-stream_loop", "-1", "-ss", f"{start:.2f}", "-i", str(visual)]
    elif kind == "image":
        vf = _kenburns_vf(frames, index)
        inputs = ["-i", str(visual)]
    else:
        # 无素材分镜：深色底，靠字幕撑画面
        vf = "[0:v]format=yuv420p[v]"
        inputs = ["-f", "lavfi", "-i",
                  f"color=c=0x141a2e:s={VIDEO_W}x{VIDEO_H}:r={FPS}:d={total}"]

    run_cmd([
        "ffmpeg", "-y", *inputs, "-i", str(mp3),
        "-filter_complex",
        vf + ";[1:a]aresample=44100,aformat=channel_layouts=stereo,apad[a]",
        "-map", "[v]", "-map", "[a]", "-t", f"{total:.3f}",
        "-c:v", "libx264", "-preset", "fast", "-crf", "20",
        "-c:a", "aac", "-b:a", "128k", str(out),
    ])
    return out, total


def build_subtitles(scenes, durations, title, workdir, hook_text=""):
    """ASS 字幕：抖音风大字白底黑边 + 顶部标题 + 开场黄金3秒大花字。"""
    ass = workdir / "subs.ass"
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {VIDEO_W}
PlayResY: {VIDEO_H}
WrapStyle: 0

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Sub,{SUB_FONT},78,&H00FFFFFF,&H00FFFFFF,&H00000000,&H80000000,1,0,0,0,100,100,1,0,1,5,2,2,60,60,620,1
Style: Title,{SUB_FONT},56,&H0000E8FF,&H00FFFFFF,&H00000000,&H80000000,1,0,0,0,100,100,1,0,1,4,2,8,60,60,140,1
Style: Hook,{SUB_FONT},110,&H000CF0FF,&H000CF0FF,&H00202020,&HA0000000,1,0,0,0,100,100,2,0,1,7,3,5,80,80,0,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = []
    t = 0.0
    for scene, dur in zip(scenes, durations):
        speech = dur - SCENE_PAD
        chunks = split_subtitle_chunks(scene["text"])
        total_chars = sum(len(c) for c in chunks) or 1
        ct = t
        for chunk in chunks:
            cd = speech * len(chunk) / total_chars
            text = chunk.replace("{", "").replace("}", "")
            lines.append(f"Dialogue: 0,{format_ass_time(ct)},{format_ass_time(min(ct + cd, t + dur))},"
                         f"Sub,,0,0,0,,{text}")
            ct += cd
        t += dur

    title_text = title.replace("{", "").replace("}", "")
    lines.insert(0, f"Dialogue: 0,0:00:00.00,{format_ass_time(t)},Title,,0,0,0,,{title_text}")

    # 黄金3秒花字：开场弹出 + 轻微放大动画，砸在画面中央偏上
    if hook_text:
        hk = hook_text.replace("{", "").replace("}", "").replace("\n", "")
        hook_end = min(3.2, durations[0] if durations else 3.2)
        anim = "{\\fad(120,200)\\t(0,260,\\fscx118\\fscy118)\\t(260,520,\\fscx100\\fscy100)}"
        lines.insert(1, f"Dialogue: 1,0:00:00.00,{format_ass_time(hook_end)},"
                        f"Hook,,0,0,0,,{anim}{hk}")
    ass.write_text(header + "\n".join(lines) + "\n", encoding="utf-8")
    return ass


def pick_bgm():
    """返回要混入的 BGM 路径：优先 BGM_PATH，否则从 BGM_DIR 随机选一首。"""
    if BGM_PATH and Path(BGM_PATH).exists():
        return Path(BGM_PATH)
    if not USE_BGM or not BGM_DIR.exists():
        return None
    import random
    tracks = sorted(BGM_DIR.glob("*.mp3"))
    return random.choice(tracks) if tracks else None


def assemble(clips, ass, workdir, out_path, total_dur):
    """concat 所有分镜 → 烧字幕（自动混 BGM，带首尾淡入淡出）。"""
    concat_list = workdir / "concat.txt"
    concat_list.write_text("".join(f"file '{c}'\n" for c in clips), encoding="utf-8")
    merged = workdir / "merged.mp4"
    run_cmd(["ffmpeg", "-y", "-f", "concat", "-safe", "0",
             "-i", str(concat_list), "-c", "copy", str(merged)])

    ass_filter = "ass=" + str(ass).replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")
    bgm = pick_bgm()
    cmd = ["ffmpeg", "-y", "-i", str(merged)]
    if bgm:
        print(f"[bgm] 混入背景音乐（人声闪避）：{bgm.name}")
        fade_out_st = max(0.0, total_dur - 1.5)
        cmd += ["-stream_loop", "-1", "-i", str(bgm), "-filter_complex",
                # 人声分两路：一路进混音，一路当 sidechain 触发器
                f"[0:v]{ass_filter}[v];"
                f"[0:a]asplit=2[voice][vkey];"
                f"[1:a]volume={BGM_VOLUME},afade=t=in:st=0:d=1.2,"
                f"afade=t=out:st={fade_out_st:.2f}:d=1.5[bgmraw];"
                # 一有人声 BGM 立刻压低，停顿时回升
                f"[bgmraw][vkey]sidechaincompress="
                f"threshold=0.02:ratio=12:attack=15:release=350[bgmduck];"
                # normalize=0 防止 amix 把人声砍半
                f"[voice][bgmduck]amix=inputs=2:duration=first:"
                f"dropout_transition=0:normalize=0[a]",
                "-map", "[v]", "-map", "[a]"]
    else:
        cmd += ["-vf", ass_filter, "-c:a", "copy"]
    cmd += ["-c:v", "libx264", "-preset", "fast", "-crf", "20",
            "-t", f"{total_dur:.3f}", str(out_path)]
    run_cmd(cmd)


def write_publish_info(data, out_dir):
    info = out_dir / "发布文案.txt"
    tags = " ".join(f"#{t}" for t in data.get("hashtags", []))
    script = "\n".join(f"{i}. {s['text']}" for i, s in enumerate(data["scenes"], 1))
    info.write_text(
        f"标题：{data['title']}\n\n开场花字：{data.get('hook_text', '')}\n\n"
        f"话题：{tags}\n\n口播脚本：\n{script}\n",
        encoding="utf-8")
    return info

# ============================================================
# 5. 主流程
# ============================================================

def run(source):
    OUT_ROOT.mkdir(parents=True, exist_ok=True)

    # 1) 解析文章（含微信嵌入短视频下载）
    tmp_work = OUT_ROOT / "_parsing"
    tmp_work.mkdir(exist_ok=True)
    article, images, videos = parse_article(source, tmp_work)
    if len(article.strip()) < 50:
        raise ValueError("正文太短，可能解析失败，请检查来源")
    print(f"[parse] 正文 {len(article)} 字，配图 {len([p for p in images if p])} 张，"
          f"短视频 {len(videos)} 条")

    # 2) 视觉识图：配图描述 + 排除品牌LOGO；视频抽帧识内容
    print("[vision] AI 识别素材内容 ...")
    captions, brand_idxs = ai_caption_images(images)
    images = [None if (i + 1) in brand_idxs else p for i, p in enumerate(images)]
    video_caps = ai_caption_videos(videos, tmp_work)

    # 3) AI 生成抖音脚本（按内容精准匹配图/视频，剔除广告与品牌）
    data = ai_make_script(article, len(images), captions, video_caps)

    # 按标题建独立输出目录
    out_dir = OUT_ROOT / slugify(data["title"])
    out_dir.mkdir(exist_ok=True)
    workdir = out_dir / "work"
    workdir.mkdir(exist_ok=True)
    if tmp_work != workdir:
        if (tmp_work / "images").exists():
            (workdir / "images").mkdir(exist_ok=True)
            images = [_copy_into(p, workdir / "images") for p in images]
        if videos:
            (workdir / "videos").mkdir(exist_ok=True)
            videos = [_copy_into(p, workdir / "videos") for p in videos]

    # 4) 配音
    audio = tts_scenes(data["scenes"], workdir)

    # 5) 逐镜合成
    clips, durations = [], []
    last_kind, last_visual = None, None
    for i, (scene, (mp3, dur)) in enumerate(zip(data["scenes"], audio), 1):
        kind, visual = pick_visual(scene, images, videos)
        if not visual:                            # 兜底沿用上一画面
            kind, visual = last_kind, last_visual
        last_kind, last_visual = kind, visual
        clip, total = build_scene_clip(kind, visual, mp3, dur, i, workdir)
        clips.append(clip)
        durations.append(total)
        tag = {"clip": "视频素材", "image": "配图"}.get(kind, "纯底色")
        print(f"[clip] 镜{i} 完成（{total:.1f}s，{tag}）")

    # 6) 字幕 + 总装
    ass = build_subtitles(data["scenes"], durations, data["title"], workdir,
                          hook_text=data.get("hook_text", ""))
    out_path = out_dir / f"{slugify(data['title'])}.mp4"
    assemble(clips, ass, workdir, out_path, sum(durations))
    info = write_publish_info(data, out_dir)

    total_dur = sum(durations)
    print(f"\n✅ 完成！时长 {total_dur:.0f} 秒")
    print(f"   视频：{out_path}")
    print(f"   文案：{info}")
    return out_path


# ============================================================
# 6. 交互式入口
# ============================================================

VOICE_PRESETS = [
    ("zh-CN-YunjianNeural",   "云健 · 有力男声（默认，适合知识/解说）"),
    ("zh-CN-XiaoxiaoNeural",  "晓晓 · 亲和女声（适合情感/生活）"),
    ("zh-CN-YunxiNeural",     "云希 · 年轻男声（适合科技/数码）"),
    ("zh-CN-XiaoyiNeural",    "晓伊 · 活泼女声（适合种草/娱乐）"),
    ("zh-CN-YunyangNeural",   "云扬 · 沉稳男声（适合新闻/财经）"),
]

RATE_PRESETS = [
    ("+28%", "抖音快节奏（默认，推荐）"),
    ("+40%", "极快（卡点/高能）"),
    ("+15%", "偏快"),
    ("+0%",  "正常语速（偏慢）"),
]

BGM_PRESETS = [
    ("auto",  "自动随机抖音风 BGM（默认，推荐）"),
    ("none",  "不要背景音乐"),
    ("custom", "我自己指定一首 mp3"),
]


def ask(prompt, default=None):
    suffix = f"（默认 {default}）" if default else ""
    val = input(f"{prompt}{suffix}\n> ").strip()
    return val or (default or "")


def choose(prompt, options, default_idx=0):
    """options 是 [(value, label)]，返回选中的 value。"""
    print(f"\n{prompt}")
    for i, (_, label) in enumerate(options, 1):
        mark = " ←默认" if i - 1 == default_idx else ""
        print(f"  {i}. {label}{mark}")
    raw = input(f"> 输入序号（回车用默认 {default_idx + 1}）：").strip()
    if not raw:
        return options[default_idx][0]
    try:
        idx = int(raw) - 1
        if 0 <= idx < len(options):
            return options[idx][0]
    except ValueError:
        pass
    print("  输入无效，用默认项")
    return options[default_idx][0]


def interactive():
    global TTS_VOICE, TTS_RATE, BGM_PATH, USE_BGM

    print("=" * 56)
    print("  图文文章 → 抖音爆款竖屏视频")
    print("=" * 56)

    # 1) 文章来源
    while True:
        source = ask("\n① 文章来源：粘贴 文章URL 或 本地文件路径(md/html/txt)")
        source = source.strip().strip('"').strip("'")
        if not source:
            print("  不能为空，请重新输入")
            continue
        if not re.match(r"^https?://", source):
            p = Path(source).expanduser()
            if not p.exists():
                print(f"  找不到文件：{p}，请重新输入")
                continue
            source = str(p)
        break

    # 2) 配音音色
    TTS_VOICE = choose("② 选择配音音色：", VOICE_PRESETS, default_idx=0)

    # 3) 语速
    TTS_RATE = choose("③ 选择语速：", RATE_PRESETS, default_idx=0)

    # 4) 背景音乐
    bgm_mode = choose("④ 背景音乐：", BGM_PRESETS, default_idx=0)
    if bgm_mode == "none":
        USE_BGM = False
    elif bgm_mode == "custom":
        while True:
            bgm = ask("   粘贴 mp3 路径").strip().strip('"').strip("'")
            bp = Path(bgm).expanduser()
            if bp.exists():
                BGM_PATH = str(bp)
                break
            print(f"   找不到：{bp}，重输或直接回车改用自动")
            if not bgm:
                break

    bgm_show = BGM_PATH or ("自动随机" if USE_BGM else "无")
    print("\n" + "-" * 56)
    print(f"  来源：{source}")
    print(f"  音色：{TTS_VOICE}   语速：{TTS_RATE}")
    print(f"  BGM ：{bgm_show}")
    print("-" * 56)
    if ask("\n确认开始？(y/n)", "y").lower() not in ("y", "yes", ""):
        print("已取消")
        return

    run(source)


if __name__ == "__main__":
    try:
        if len(sys.argv) >= 2:
            # 兼容老用法：带参数直接出片
            run(sys.argv[1])
        else:
            interactive()
    except KeyboardInterrupt:
        print("\n已中断")
        sys.exit(130)
