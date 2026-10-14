# OpenVideoStudio

**本地优先、采用 Apache-2.0 许可证的 AI 视频创作工作室。**
从一句提示词，到一部完整的视频——其中大部分处理都不会离开你的机器。

[English](README.md) · [安装指南](docs/INSTALL.md) · [架构说明](docs/architecture.md) · [路线图](ROADMAP.md) · [贡献指南](CONTRIBUTING.md) · [Discussions](../../discussions)

### 一眼看懂

| | |
|---|---|
| **这是什么** | 一个开源流水线，把一句文字提示词变成一部完整剪辑、配音、带字幕的视频——剧本 → 分镜 → 角色/场景一致性设定 → 关键帧 → 视频片段 → 配音 → 字幕 → 最终视频。 |
| **为什么做这个** | 由一名开发者在 6GB 显存的笔记本显卡上独立开发，没有 GPU 集群、也没有无限的 AI 预算——所以这套流水线必须能在普通硬件上真正跑起来，而不只是一个数据中心里的演示。 |
| **有什么不一样** | 本地优先（剧本/分镜/一致性设定/关键帧/视频全部在你自己的机器上运行）、模型提供方可通过配置切换而非改代码、按场景做检查点支持断点续跑、并且在任何 GPU 生成开始前设有强制的人工审核环节——具体内容见下方 [功能特性](#功能特性)。 |
| **怎么试用** | `git clone` → `pip install -r requirements.txt` → `python -m server`。完整步骤见 [快速开始](#快速开始)。 |

*有一点需要提前说明：默认的配音方案目前会用到一个云端服务（Edge
TTS）——不会藏着不提，见下文
["默认本地运行"](#默认本地运行但有一个例外需要如实说明)一节。流水线的其余
部分都在你自己的硬件上运行。*

## 演示

![OpenVideoStudio 真实、未经剪辑美化的完整运行结果：一名宇航员探索一座废弃的空间站](examples/hero_demo/preview.gif)

*"Echoes of Home"——从一句提示词端到端生成：剧本 → 分镜 → 角色/场景一致性
设定 → 6 个关键帧 → 6 段视频片段 → 配音 → 字幕 → 自动剪辑合成。以上为
2 倍速预览；完整的 32.9 秒视频和完整的生成信息（提示词、模型、随机种子）见
[`examples/hero_demo/`](examples/hero_demo/)。不是模拟效果图——这就是
真实的流水线输出，未经剪辑美化。**需要如实说明：**这次运行中角色的外貌
在不同场景之间出现了明显漂移（发色、面部特征不完全一致）——这是
[角色一致性赛道](docs/COMMUNITY_TRACKS.md#track-c--character-consistency)
这一开放研究方向真实存在、且被如实披露的问题，不是被剪辑掩盖过的。完整
说明见
[`examples/hero_demo/README.md`](examples/hero_demo/README.md)（英文）。*

## 项目愿景

OpenVideoStudio 近期的目标就是现在已经上线的部分：一条可靠的、本地优先的、
单句提示词到成片的流水线，能在消费级硬件上运行。更长期的方向，是把它发展
成一个更完整的开源 AI 视频制作系统——更丰富的故事规划能力、真正的角色记忆
模型、可视化工作流编辑器，以及社区共享的工作流——就像 ComfyUI 从一个单纯
的 Stable Diffusion 图执行器,成长为通用的节点式生成平台,或者像 Blender
的产线围绕一个稳定的开源内核不断生长。

以上这些长期方向目前都还没有实现。哪些是今天真实存在的功能、哪些只是尚无
代码支撑的愿景，请看
[`docs/architecture.md`](docs/architecture.md)的"长期愿景"一节和
[`ROADMAP.md`](ROADMAP.md)——本文档不会把两者混为一谈。

## 架构概览

```
模型提供方 (Ollama · ComfyUI · Edge TTS)
        ↓
创作流水线 (剧本 → 分镜 → 一致性设定 → 关键帧 → 视频片段)
        ↓
审核环节 (任何 GPU 生成开始前，需要你先确认)
        ↓
渲染核心 (FFmpeg：配音混音、字幕烧录、冻结/运动质检)
        ↓
最终视频
```

每一类模型（LLM、图像、视频、语音合成）都在 `providers/base.py` 中定义为
接口；实际使用哪个提供方由 `config.toml` 决定，而不是写死在代码里——新增
一个提供方只需要一个新文件加 `providers/registry.py` 里的两行注册。创作
流水线和渲染核心也被 **Media Remix** 共用——这是同一个应用里的辅助工具，
用来剪辑你自己的照片/视频素材库：两者是同一套渲染引擎上的两种前端工作流，
而不是两套独立的视频引擎。

→ 完整的组件拆解，以及"故事引擎 / 场景图谱 / 角色记忆"这一长期愿景架构
（尚未实现，已明确标注）：见 [`docs/architecture.md`](docs/architecture.md)。

## AI 视频流水线

```
提示词
  → 剧本
  → 分镜脚本
  → 角色 / 场景一致性设定
  → 关键帧
  → AI 视频片段
  → 配音
  → 字幕
  → 自动剪辑
  → 最终视频
```

只需输入一句提示词，就能生成一部完整剪辑、配音、带字幕的视频。生成过程
按阶段做检查点保存——某个场景的关键帧/视频片段如果已经存在，重跑时会
自动跳过——分镜脚本未经你审核批准前，不会进入后续渲染。

→ 每个阶段具体做什么、哪些在本地运行、哪些走云端，完整说明见
[`docs/workflow.md`](docs/workflow.md)（英文）。

### 默认本地运行，但有一个例外需要如实说明

剧本、分镜、角色/场景设定、关键帧、视频片段，全部由运行在你自己机器上的
模型生成（Ollama + ComfyUI），完全不需要离开你的硬件。**目前唯一的例外
是配音**：默认的语音合成服务是微软的免费在线服务 Edge TTS，配音文本会
通过网络发送出去。目前还没有完全本地/离线的语音合成方案可用——这是一个
公开征集贡献的方向，见 [`docs/ISSUES_SEED.md`](docs/ISSUES_SEED.md)。
我们宁愿把这一点说清楚，也不愿让"本地运行"这个说法产生误导。

## 功能特性

- **免费开源。** 采用 Apache-2.0 许可证——软件本身没有账号、没有付费墙、
  没有用量计费。许可证具体覆盖和不覆盖的范围见下方[许可证](#许可证)一节。
- **本地优先。** 如上所述——除了配音的默认方案之外，其余全部在你自己的
  硬件上运行。
- **对消费级显卡友好。** 已在 6GB 显存的笔记本显卡上完整验证通过端到端流程
  （具体哪些是"已测试"、哪些是"预期可行"、哪些是"未知"，请见
  [`docs/HARDWARE.md`](docs/HARDWARE.md)——我们不会宣称未经验证的硬件支持；
  目前仅支持 NVENC 编码，还没有 CPU / 其他厂商显卡的编码回退方案）。
- **模型提供方的选择是配置项，不是写死在代码里的。** 参见上方
  [架构概览](#架构概览)。目前还没有兼容 OpenAI 接口的适配器（已列为待认领
  的方向）——现已上线的提供方是 Ollama、ComfyUI（SDXL + LTX-Video）和
  Edge TTS。
- **可断点续跑，带一个人工审核环节。** 生成过程按阶段做检查点保存；分镜脚本
  未经你审核批准前不会进入后续渲染，失败的任务可以从断点恢复，而不用
  从头重来。
- **自动化视频质检。** 生成过程中自动进行画面冻结/运动检测、结构校验和
  叙事质量检查。

两种模式，如实标注各自的状态：

- **快速模式**（现已上线）：提示词 → 自动生成 → 到达分镜审核这个必经的
  检查点 →（你确认后）→ 自动生成 → 最终视频。它并不是从头到尾完全无需
  介入——这个审核环节是刻意设计的安全机制，不是遗漏。
- **专业模式**（路线图中，尚未实现）：把角色设计、场景设计、关键帧审核
  做成独立的可视化步骤，并配上真正的时间线编辑器。详见
  [`ROADMAP.md`](ROADMAP.md)——任何尚未上线的功能都会明确标注为
  规划中（PLANNED）、招募贡献者（HELP WANTED）或研究方向（RESEARCH），
  绝不会当作已完成功能宣传。

## 安装

已验证环境：**Windows 10/11**，NVIDIA 显卡（**6GB 以上显存**）+ NVENC，
Python 3.11+，Ollama，ComfyUI，FFmpeg。模型文件（Ollama 的 LLM、SDXL、
LTX-Video 权重）体积达数 GB，不随本仓库分发，需要自行下载。

→ 快速了解：[`docs/installation.md`](docs/installation.md)（英文）
→ 完整分步指南（前置依赖、精确模型文件名与下载来源、常见问题排查）：
[`docs/INSTALL.md`](docs/INSTALL.md)

## 快速开始

```bash
git clone <repository-url>
cd OpenVideoStudio/studio
pip install -r requirements.txt
cp .env.example .env    # 设置 COMFYUI_ROOT
python -m server        # 打开 http://127.0.0.1:7870
```

目标是在已下载好所需模型的前提下，10 分钟内完成配置。启动后会打开
OpenVideoStudio 编辑器（单屏本地网页应用），包含两个工作区：**Create**
（上面的提示词到视频流水线；需要生成时会根据 `COMFYUI_ROOT` 自动启动
ComfyUI，Ollama 需要已在运行）和 **Remix**（把你自己的照片/视频素材库
剪辑成成片：自动方案、监视器、时间线、素材库、风格、标题、转场、随节拍
剪辑、项目保存、后台渲染，共用同一套 FFmpeg / 音频 / 评分核心逻辑）。
Windows 上可直接运行 `Avvia_OpenVideoStudio.bat` 启动，
`Ferma_OpenVideoStudio.bat` 停止。

不需要 GPU 即可验证安装是否正确：

```bash
cd studio && python -m pytest tests/ -q
```

## 路线图

已上线：提示词 → 剧本 → 分镜 → 角色/场景一致性设定 → 关键帧 → 视频片段 →
配音 → 字幕 → 最终视频，本地 Ollama + ComfyUI 生成，按场景断点续跑，
67/67 测试通过。尚未实现：专业模式的引导式界面、真正的时间线编辑器、
Ollama/ComfyUI/Edge TTS 之外的更多提供方，以及上方[项目愿景](#项目愿景)
中提到的角色记忆 / 场景图谱 / 多智能体等更长期方向。

→ 按版本划分的完整状态，每一项都标注了 DONE / HELP WANTED / RESEARCH /
PLANNED：见 [`ROADMAP.md`](ROADMAP.md)（英文）。

## 想一起打造 OpenVideoStudio 吗？

核心流水线由维护者主导开发，并有完整测试覆盖。除此之外的每一个方向，
都是真实、可独立认领的贡献空间——我们特意没有把这些都做完，就是为了
留下真正值得贡献的部分。

| 方向 | 内容 |
|---|---|
| 🎨 [AI 美术工作室](docs/COMMUNITY_TRACKS.md#track-a--ai-art--visual-development) | 角色/场景设定库、参考图一致性、局部重绘、Krita 集成 |
| 🧑 [角色一致性](docs/COMMUNITY_TRACKS.md#track-c--character-consistency) | 视觉一致性漂移、人脸相似度质检、基准测试 |
| 🔌 [模型网关](docs/COMMUNITY_TRACKS.md#track-b--universal-model-gateway) | OpenAI 兼容接口 / llama.cpp / vLLM 适配器、企业级接入 |
| 🎬 [视频模型](docs/COMMUNITY_TRACKS.md#track-d--provider-integrations) | 更多图像/视频模型适配器 |
| 🎞 [时间线编辑器](docs/COMMUNITY_TRACKS.md#track-f--timeline--editor) | 分镜重排、剪切、转场、字幕编辑器 |
| 🧪 [AI 视频质检](docs/COMMUNITY_TRACKS.md#track-g--ai-video-qc) | 成片冻结检测、重复镜头/音频质检、质量评分 |
| 🐧 [Linux](docs/COMMUNITY_TRACKS.md#track-e--platform-support) / 🍎 [macOS](docs/COMMUNITY_TRACKS.md#track-e--platform-support) | 目前仅在 Windows 上验证，需要跨平台支持 |
| 🌍 [翻译](docs/COMMUNITY_TRACKS.md#track-h--documentation--localization) / 📚 [文档](docs/COMMUNITY_TRACKS.md#track-h--documentation--localization) | 本地化、安装指南、教程 |

从 [`docs/ISSUES_SEED.md`](docs/ISSUES_SEED.md) 开始——里面有标注了完整
验收标准的 `good first issue`；完整贡献流程见
[`docs/contribution.md`](docs/contribution.md) /
[`CONTRIBUTING.md`](CONTRIBUTING.md)（英文）——包括 Fork、分支命名、
提交 PR、DCO 签署，以及贡献如何逐步转化为仓库权限。

## 社区

- **[GitHub Discussions](../../discussions)** ——使用问题、想法、工作流
  分享都在这里进行，而不是在 Issues 里。
- **Issues** ——结构化模板，覆盖
  [Bug 反馈](.github/ISSUE_TEMPLATE/bug_report.md)、
  [功能建议](.github/ISSUE_TEMPLATE/feature_request.md)、
  [模型/提供方申请](.github/ISSUE_TEMPLATE/model_request.md)、
  [工作流分享](.github/ISSUE_TEMPLATE/workflow_share.md)。
- **[行为准则](CODE_OF_CONDUCT.md)** ——采用 Contributor Covenant 2.1；
  适用于所有项目相关的场合。
- **[治理模式](GOVERNANCE.md)** ——项目如何运作，以及贡献如何逐步转化为
  可信贡献者 / Reviewer / Maintainer 身份。赞助永远不能购买治理权——见
  `GOVERNANCE.md` 中的"赞助不能购买治理权"一节。
- **[支持](SUPPORT.md)** ——在哪里寻求帮助，以及如何联系维护者处理非安全
  问题。
- **安全问题** ——请通过私密渠道报告漏洞，见 [`SECURITY.md`](SECURITY.md)，
  不要提交公开 Issue。

## 为什么做这个项目

做 OpenVideoStudio 之前，我手头并没有什么昂贵的 GPU，也没有充裕的 AI
预算——恰恰相反。我的主力机器是一台配备 RTX 3060 6GB 显卡的笔记本电脑
（具体验证过什么、哪些只是预期可行，见
[`docs/HARDWARE.md`](docs/HARDWARE.md)，不是随口一说）。为了做实验持续
为每一次生成、每一次失败重试付费，对我来说不是能长期维持的方案，而且
这台机器本身也算不上多强。所以与其靠"买更多算力"解决问题，我干脆把这套
工作流自己搭出来：提示词 → 剧本 → 分镜 → 关键帧 → 视频片段 → 配音 → 字幕
→ 自动剪辑合成，让它真正能在我已经拥有的这台机器上端到端跑起来。

它还远谈不上完成。角色在不同镜头之间的外貌一致性还有明显的提升空间——
上面 demo 部分如实披露的漂移就是例子，也是
[角色一致性赛道](docs/COMMUNITY_TRACKS.md#track-c--character-consistency)
存在的原因；需要接入更多模型和 provider；编辑器还只是设计稿；Linux 和
macOS 的支持也还不够好。与其一个人关起门来继续埋头做下去，我更想现在就
把它开放出来——交给开发者、创作者和研究者，尤其是像我一样没有无限 GPU、
也没有无限 API 预算的人，一起打磨它。发现 bug，欢迎提 Issue；有想法，
欢迎在 Discussions 里聊；哪怕只改好一个小地方，也
欢迎提 PR——具体流程见 [`CONTRIBUTING.md`](CONTRIBUTING.md)。希望有一天
打开 Contributors 页面，看到的不只是一个名字。

## 项目状态

持续开发中。已完成内容见 [`CHANGELOG.md`](CHANGELOG.md)，后续计划见
[`ROADMAP.md`](ROADMAP.md)。治理模式见 [`GOVERNANCE.md`](GOVERNANCE.md)，
安全策略见 [`SECURITY.md`](SECURITY.md)。

## 许可证

[Apache License 2.0](LICENSE)。完整的方案比较（对比 MIT / GPLv3 /
AGPLv3）和选择 Apache-2.0 的理由见
[`docs/LICENSE_STRATEGY.md`](docs/LICENSE_STRATEGY.md)——简单来说：
接近 MIT 的友好度，加上明确的专利授权条款，这对一个紧贴快速演进的
AI/模型生态的项目来说很重要。贡献者通过
[DCO](https://developercertificate.org/)（`git commit -s`）签署提交，
而不是 CLA——见 [`CONTRIBUTING.md`](CONTRIBUTING.md)。

许可证覆盖的是本仓库的代码，不包括 OpenVideoStudio 的名称、标志或官方
发布渠道——这些如何单独得到保护、为什么宽松的代码许可证不等于把这些也
一并让渡出去，见 [`GOVERNANCE.md`](GOVERNANCE.md#brand-control)。
