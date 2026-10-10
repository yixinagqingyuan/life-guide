# 高性价比人生指南 Skill

一个包含《高性价比人生指南》原文、完整条目和本地检索脚本的 Codex Skill。知识库与脚本均在同一个文件夹内，检索只使用 Python 标准库，不下载模型、不调用外部 API。

默认使用方式是：先正常回答用户的问题，再在最终答复结尾附一条相关的“高性价比人生指南提醒：”，以“条目原标题——《章节名》”逐字展示原始标题，另加一行“性价比：极高／高／一般”中的对应分档。不展开成本明细，不加“原文”“出处”标签、章节条号或原文链接。用户无需每次说“查高性价比人生指南”；编程、知识问答、倾诉等问题也保留原本回答，只在末尾增加简短提醒。没有直接对应条目时，选与当前任务有关的通用条目，提醒标题保持一致，不加“（通用）”。

## 安装与启用

本项目面向支持本地 Skill 的 Codex 环境。运行检索脚本需要 Python 3.10 或以上；不需要安装第三方 Python 包、下载模型或配置检索 API Key。

### 方式一：让 Codex 安装（推荐）

把下面这段话复制到 **Codex 对话框**，它是一条消息，不是终端命令：

```text
$skill-installer 请从 https://github.com/yixinagqingyuan/life-guide 安装 life-guide。SKILL.md 位于仓库根目录，仓库内路径是 .，安装名称是 life-guide（--path . --name life-guide）。请把整个目录安装到当前 Codex 能发现的用户技能目录，保留 knowledge-base、scripts、references、agents 和 assets，并检查 Python 检索是否可用。
```

本仓库根目录就是完整 Skill，不能只下载 `SKILL.md`。`--path . --name life-guide` 明确指定根目录和安装后的文件夹名称，避免安装器把 `.` 当成名称。

安装完成后，在下一条消息中启用：

```text
请用 $life-guide 正常回答我接下来的问题，并在本会话每次答复结尾附一条相关的《高性价比人生指南》提醒：逐字展示“条目原标题——《章节名》”，另列“性价比：极高／高／一般”中对应的一档，不附原文链接，不展开成本明细。
```

内置 Skill Installer 支持从其他 GitHub 仓库安装；Codex 会检测新增技能，如果没有显示，可以重启后再调用。显式调用可确保本会话使用它，安装本身不保证所有新会话都自动附提醒。见 [OpenAI 官方 Skill 说明](https://learn.chatgpt.com/docs/build-skills)。

### 方式二：自己安装整个文件夹

<details>
<summary>有 Git：Windows、macOS 和 Linux 的安装命令</summary>

下面使用当前官方文档中的用户技能目录 `~/.agents/skills`，对应 Windows 的 `%USERPROFILE%\.agents\skills`。如果你的 Codex 已使用 `~/.codex/skills` 或自定义的 `$CODEX_HOME/skills`，把目标改成宿主实际使用的目录；只选一个位置。不确定目录时，优先使用方式一。目录依据见 [OpenAI 官方说明](https://learn.chatgpt.com/docs/build-skills#where-codex-loads-local-skills)。

**Windows PowerShell：**

```powershell
$lifeGuideSkills = Join-Path $HOME ".agents/skills"
New-Item -ItemType Directory -Path $lifeGuideSkills -Force | Out-Null
git clone --depth 1 https://github.com/yixinagqingyuan/life-guide.git "$lifeGuideSkills/life-guide"
```

**macOS / Linux：**

```bash
mkdir -p "$HOME/.agents/skills"
git clone --depth 1 https://github.com/yixinagqingyuan/life-guide.git "$HOME/.agents/skills/life-guide"
```

目标已存在时，先检查是否已经安装，不要覆盖个人改动。通过 Git 安装的版本可以在无本地修改时更新：

```bash
git -C "$HOME/.agents/skills/life-guide" pull --ff-only
```

更新命令同样需要替换成实际安装目录。安装后发送上面的启用消息。

</details>

<details>
<summary>没有 Git：下载 ZIP 后复制整个文件夹</summary>

1. 下载 [GitHub 仓库 ZIP](https://github.com/yixinagqingyuan/life-guide/archive/refs/heads/main.zip)，或在仓库页面选择 **Code → Download ZIP**。
2. 解压后，将包含 `SKILL.md` 的 `life-guide-main` 文件夹改名为 `life-guide`。
3. 把这个文件夹整体放进用户技能目录，例如 `~/.agents/skills/life-guide`；已有 Codex 使用其他目录时，以实际目录为准。
4. 回到 Codex，发送上面的启用消息；没有发现技能时重启再调用。

安装后的结构应如下，说明文件在这里省略：

```text
用户技能目录/
└── life-guide/
    ├── SKILL.md
    ├── agents/
    ├── knowledge-base/
    ├── scripts/
    ├── references/
    └── assets/
```

`SKILL.md` 要直接位于 `life-guide/` 下，不要多套一层 `life-guide-main/`。ZIP 方式更新时先比较并保留个人改动，再替换整个技能包。

</details>

### 确认安装成功

在 Codex 中发送：

```text
请用 $life-guide 检索“午休”，读取相关完整条目，告诉我找到的原标题和性价比分档，并确认你使用的是本地 knowledge-base 中的资料。
```

这一步同时检查 Skill 是否被加载、知识库是否完整，以及模型能否读取相关原文。若想单独验证脚本，在实际安装目录中执行：

```powershell
python --version
python -X utf8 scripts/validate_kb.py
python -X utf8 scripts/search_kb.py "午休" --limit 3 --context --json
```

macOS / Linux 若命令是 `python3`，将上述 `python` 替换为 `python3`。当前版本校验应报告 34 章、676 条；检索应返回 `status: ok`，并包含 `context_bundle.contexts` 的完整原文。

找不到 Skill 时检查目录与嵌套层级；找不到知识库或脚本时检查是否只复制了 `SKILL.md`；找不到 Python 时安装 Python 3.10+ 或使用宿主可用的 Python 运行时。公开仓库下载通常无需 GitHub 登录，网络失败时可改用 ZIP 手动安装。

## 知识库原理

想了解原文怎样整理成知识库、切片和检索怎样工作，以及 RAG 如何生成最后的提醒，请看 [知识库原理：从 Markdown 原文到检索与提醒](知识库原理.md)。说明按本仓库实际代码编写，包含流程图、查询示例和源码入口，方便学习与修改。

![高性价比人生指南知识库与回答流程图](assets/knowledge-base-flow.svg)

## 内容

- 34 个原始章节，676 个保留完整正文的条目。
- 原仓库专题、历史核实记录、主题与场景目录。
- BM25F 字段加权、36 组近义表达、三路召回、RRF 融合和规则重排。
- 命中后补读完整条目、少量明确交叉引用，并支持逐字引文校验。

默认提醒直接显示本地 Markdown 条目的原标题及原指南性价比分档，以“——《章节名》”署出处，不再从正文另挑一句代替标题。分档按原作者固定版本的成本权重和收益规则计算，不另设评分标准；完整条目仍用于核对适用条件。用户需要完整出处或打开原文时再提供条号或链接。上游链接用于追溯出处；指南原文引用的外部论文、政策页面只保留链接，未下载外部网页全文。

## 直接检索与暂停提醒

安装和启用方式见上方 [安装与启用](#安装与启用)。如需暂停，可说“这次不加提醒”或“关闭高性价比人生指南提醒”；严格限定输出格式时优先遵守用户要求。检索脚本也可以直接使用：

在仓库目录执行：

```powershell
python -X utf8 scripts/search_kb.py "公司不发工资怎么办" --limit 3 --context --json
python -X utf8 scripts/search_kb.py "自动扣费" --chapter 5 --limit 2
python -X utf8 scripts/search_kb.py --show 5-1
python -X utf8 scripts/search_kb.py --verify-citation 5-1 --quote "年付一般比月付便宜"
```

命令从其他目录运行时，改用脚本的实际绝对路径。`--context` 返回完整原文；预算不足时整条省略，并在 `omitted` 中标明。匹配分数仅用于排序，不是事实可信度或个人适用性概率。

## 文件入口

| 路径 | 用途 |
| --- | --- |
| [SKILL.md](SKILL.md) | Skill 的触发范围、回答流程与引用规则 |
| [知识库原理.md](知识库原理.md) | 原文整理、两层切片、召回排序、RAG 和提醒生成的入门说明 |
| [assets/knowledge-base-flow.svg](assets/knowledge-base-flow.svg) | 首页与原理文档共用的可编辑流程图 |
| [knowledge-base/INDEX.md](knowledge-base/INDEX.md) | 知识库总目录 |
| [knowledge-base/chapters/](knowledge-base/chapters/) | 原始章节 |
| [knowledge-base/entries/](knowledge-base/entries/) | 完整条目与检索元数据 |
| [knowledge-base/articles/INDEX.md](knowledge-base/articles/INDEX.md) | 专题和历史核实记录 |
| [references/usage.md](references/usage.md) | 命令、筛选和维护方式 |
| [references/retrieval.md](references/retrieval.md) | 实际召回与重排设计 |
| [references/retrieval-evaluation.md](references/retrieval-evaluation.md) | 开发样例对比与局限 |

## 源码阅读顺序

先运行上面的查询示例，再按下面的顺序阅读。六个 Python 脚本均附有中文模块说明、函数说明和关键步骤注释。检索脚本负责找出原文与上下文；宿主模型根据 `SKILL.md` 回答问题并选择相关提醒。

| 顺序 | 文件 | 建议关注的内容 |
| --- | --- | --- |
| 1 | [scripts/search_kb.py](scripts/search_kb.py) | 命令行入口、条目格式、筛选参数，以及默认算法和旧算法的调用关系 |
| 2 | [scripts/advanced_retrieval.py](scripts/advanced_retrieval.py) | 分词与窗口切片、BM25F、三路召回、RRF 融合、规则重排和完整上下文 |
| 3 | [scripts/build_kb.py](scripts/build_kb.py) | 如何把上游 Markdown 拆成完整条目，生成导航、元数据和校验值 |
| 4 | [scripts/validate_kb.py](scripts/validate_kb.py) | 如何核对条目与原始章节、文件哈希和本地链接 |
| 5 | [scripts/test_retrieval.py](scripts/test_retrieval.py) | 真实提问的回归样例，以及无匹配、预算不足和原文被修改等边界 |
| 6 | [scripts/benchmark_retrieval.py](scripts/benchmark_retrieval.py) | 如何比较旧算法、近义词扩展和增强检索，以及开发样例评估的局限 |

[agents/openai.yaml](agents/openai.yaml) 注释说明了技能名称、调用提示词和自动选择配置；完整的回答流程见 [SKILL.md](SKILL.md)。

## 验证与更新

```powershell
python -X utf8 scripts/validate_kb.py
python -X utf8 scripts/test_retrieval.py
python -X utf8 scripts/benchmark_retrieval.py
```

开发样例参与过规则调整，成绩不能当作任意问题的准确率。原文快照不表示医学、法律或政策事实已核验到当前日期。

重新构建知识库需要本地原仓库快照与固定提交号，见 [维护说明](references/usage.md)。构建脚本不联网，并拒绝覆盖已有输出。

## 原作者、版本与许可

知识原文来自 eternity4719 及《高性价比人生指南》贡献者的 [HowToLiveBetter](https://github.com/eternity4719/HowToLiveBetter)。本仓库使用固定提交 `bb25081b423091f9e22059aab6b4ed7343a2266d`，取得日期为 2026-10-10。

原指南正文保留 [CC BY 4.0 许可证](knowledge-base/LICENSE)，上游代码许可证保留在 [LICENSE-CODE](knowledge-base/LICENSE-CODE)。原始章节、专题与许可按字节复制；条目只规范化换行并附加检索元数据，主题、场景、近义表达与检索脚本是本 Skill 添加的内容。完整说明见 [SOURCES.md](knowledge-base/SOURCES.md)，原始文件校验值见 [MANIFEST.md](knowledge-base/MANIFEST.md)。
