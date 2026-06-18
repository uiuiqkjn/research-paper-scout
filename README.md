# Research Paper Scout

Research Paper Scout 是一个用于研究方向 prior-art 检索的 Codex skill。它会检索多个学术论文数据库，对返回论文进行去重、补全和重排，并基于论文标题与摘要的内容相似度，初步判断一个研究方向是否已经有相近工作。

它适合回答：

- 这个研究方向有没有人做过？
- 这个 idea 是否可能已有类似论文？
- 哪些论文最接近我的 proposed topic？
- 哪些部分看起来已经被覆盖，哪些角度可能仍有新颖性？

> 注意：本工具给出的是文献侦察结论，不是专利新颖性意见，也不能替代系统综述。用于论文、开题、基金或法律判断前，请人工阅读最接近论文的全文、related work、limitations 和 references。

## 功能特性

- 检索 OpenAlex、Crossref、DBLP、arXiv，并在可用时使用 Semantic Scholar。
- 按标准化 DOI 优先去重，其次按标准化标题去重。
- 使用 Semantic Scholar 对 DOI 或 arXiv ID 对应论文进行元数据补全。
- 结合内容相似度、概念覆盖、领域聚焦、方法聚焦、年份、引用数、venue 匹配和 survey/review 信号进行重排。
- 生成 prior-art verdict、closest evidence、可能新颖点和可靠性提醒。
- 标准输出固定为两个文件：`papers.csv` 和 `prior_art_conclusion.md`。

## 目录结构

```text
.
├── README.md
└── research-paper-scout/
    ├── SKILL.md
    ├── agents/
    │   └── openai.yaml
    └── scripts/
        └── research_paper_scout.py
```

## 环境要求

必需：

- Python 3
- 能访问 OpenAlex、Crossref、DBLP、arXiv

可选环境变量：

| 变量 | 作用 |
| --- | --- |
| `S2_API_KEY` | 启用 Semantic Scholar 搜索，并提高 Semantic Scholar 元数据补全稳定性 |
| `OPENALEX_MAILTO` | 提供给 OpenAlex 的联系邮箱 |
| `CROSSREF_MAILTO` | 提供给 Crossref 的联系邮箱；未设置时脚本会尝试使用 `OPENALEX_MAILTO` |

## 安装

本项目是一个标准的 skill 文件夹，核心目录是 `research-paper-scout/`。安装时只需要把这个目录放到对应客户端的 skills 目录中。

### 方式一：通过 Codex 直接安装

如果你已经在使用 Codex，并且该仓库已发布到 GitHub，可以直接让 Codex 使用内置的 skill 安装器安装：

```text
$skill-installer 请从 GitHub 安装这个 skill：
https://github.com/uiuiqkjn/research-paper-scout
```

### 方式二：手动安装到 Codex

下载或 clone 本仓库后，把 `research-paper-scout` 文件夹复制到 Codex skills 目录：

```bash
mkdir -p ~/.codex/skills
cp -R research-paper-scout ~/.codex/skills/
```

安装后，新开一个 Codex 会话，即可通过下面的方式调用：

```text
$research-paper-scout
```

### 方式三：安装到 Claude Code

Claude Code 的本地 skills 目录通常是 `~/.claude/skills`。把 `research-paper-scout` 文件夹复制进去：

```bash
mkdir -p ~/.claude/skills
cp -R research-paper-scout ~/.claude/skills/
```

安装后，重启 Claude Code 或新开一个 Claude Code 会话，之后可以直接描述任务。

## 在 Codex 中快速使用

把下面的模板粘贴到 Codex 中：

```text
$research-paper-scout 帮我判断下面这个研究方向是否已有相近工作：

research_topic: retrieval augmented generation for scientific literature question answering
keywords: RAG,retrieval augmented generation,scientific literature,scholarly QA,citation-aware question answering
year_from: 2021
year_to: 2026
max_results: 50
venues: ACL,EMNLP,NAACL,NeurIPS,ICLR,SIGIR

请基于标题和摘要内容判断 prior art，不要只按标题关键词判断。
最终只返回 papers.csv 和 prior_art_conclusion.md 两个文件链接。
```

Codex 会运行 bundled script，并返回两个结果文件：

- `papers.csv`
- `prior_art_conclusion.md`

## 命令行使用

也可以直接运行脚本：

```bash
python3 research-paper-scout/scripts/research_paper_scout.py \
  --intent prior-art \
  --research-topic "retrieval augmented generation for scientific literature question answering" \
  --keywords "RAG,retrieval augmented generation,scientific literature,scholarly QA,citation-aware question answering" \
  --year-from 2021 \
  --year-to 2026 \
  --max-results 50 \
  --venues "ACL,EMNLP,NAACL,NeurIPS,ICLR,SIGIR" \
  --output-dir ./outputs/rag-scientific-literature
```

如果已经安装到 `~/.codex/skills`，也可以运行：

```bash
python3 ~/.codex/skills/research-paper-scout/scripts/research_paper_scout.py \
  --intent prior-art \
  --research-topic "retrieval augmented generation for scientific literature question answering" \
  --keywords "RAG,retrieval augmented generation,scientific literature,scholarly QA,citation-aware question answering" \
  --year-from 2021 \
  --year-to 2026 \
  --max-results 50 \
  --venues "ACL,EMNLP,NAACL,NeurIPS,ICLR,SIGIR" \
  --output-dir ./outputs/rag-scientific-literature
```

脚本会在终端打印一段 JSON，包含输出目录、生成文件路径、prior-art verdict 和 confidence。

## 输入参数

检索质量高度依赖输入质量。一个好的 `research_topic` 应尽量包含：问题或任务、方法、数据或领域、评估目标。

| 参数 | 必填 | 说明 | 建议 |
| --- | --- | --- | --- |
| `research_topic` / `--research-topic` | 是 | 简洁描述研究方向或问题 | 尽量包含问题/任务、方法、数据/领域和评估目标 |
| `keywords` / `--keywords` | 是 | 关键词、同义词、缩写、方法名、任务名、数据集、应用领域 | 用英文逗号、分号或竖线分隔 |
| `year_from` / `--year-from` | 是 | 检索起始年份，包含该年 | 第一轮 prior-art 侦察建议给宽一些 |
| `year_to` / `--year-to` | 是 | 检索结束年份，包含该年 | 通常设为当前年份 |
| `max_results` / `--max-results` | 是 | 重排后保留的论文数量 | prior-art 检查建议 50-100 |
| `venues` / `--venues` | 否 | 目标会议、期刊或 venue 缩写 | 关注特定社区时使用 |
| `output_dir` / `--output-dir` | 是 | 输出目录 | 每个研究问题使用单独目录 |

较好的主题示例：

```text
retrieval augmented generation for scientific literature question answering
```

不推荐的主题示例：

```text
AI for papers
```

后者过宽，无法区分具体问题、方法和领域，容易返回泛泛相关但不构成 close prior art 的论文。

## 输出约定

标准输出只包含两个文件：

```text
papers.csv
prior_art_conclusion.md
```

除非你修改脚本或明确要求额外产物，否则不会生成 BibTeX、JSON 或单独 ranking summary。脚本还会自动删除输出目录中旧的 `papers.bib`、`papers.json` 和 `summary.md`，避免旧结果误导使用者。

建议每次检索使用独立输出目录，例如：

```text
./outputs/rag-scientific-literature
./outputs/multimodal-medical-report-generation
./outputs/graph-neural-networks-for-molecule-property
```

## `prior_art_conclusion.md`

这是给人阅读的结论文件，建议优先打开。

它包含：

- Reliability Warning：当数据源失败、候选结果过少或关键词覆盖弱时给出提醒。
- Verdict：对研究方向是否已有相近工作的判断。
- Confidence：本次自动侦察结论的可靠程度。
- Closest Evidence：最接近的证据论文。
- What Seems Already Covered：哪些内容看起来已经被已有工作覆盖。
- What May Still Be Novel：哪些角度可能仍有新颖性。
- Possible Research Gaps：基于检索结果推测的潜在研究空白。
- API Status：各数据源成功、失败、候选数量和补全状态。

### Verdict 取值

| Verdict | 含义 |
| --- | --- |
| `likely_done` | 多篇论文在问题、方法和领域上都有较强内容重合，应视为已有接近 prior art |
| `partially_done` | 存在相邻工作，但具体任务、方法、模态、数据集、人群、约束或评估不同 |
| `no_clear_prior_work_found` | 在已检索来源中没有发现清晰的内容级强匹配 |

### Confidence 口径

`confidence` 反映的是这次自动侦察的可靠程度，不等于最终学术结论强度。它受以下因素影响：

- 是否有多个数据源成功返回结果。
- 排名前列论文的标题和摘要是否同时覆盖问题、方法和领域。
- 结果是否主要来自泛关键词匹配。
- 是否出现 API 失败、限流或候选过少。

## `papers.csv`

这是机器可读的论文表，适合排序、筛选、二次分析或导入表格工具。

| 字段 | 说明 |
| --- | --- |
| `score` | 综合排序分数 |
| `relevance` | 内容相关性综合分 |
| `content_similarity` | 输入 topic/keywords 与论文标题+摘要的词项相似度 |
| `concept_coverage` | 论文标题+摘要对输入概念的覆盖程度 |
| `domain_focus` | 是否命中较有区分度的领域锚点 |
| `method_focus` | 是否命中方法或技术路径相关概念 |
| `title` | 论文标题 |
| `year` | 发表年份 |
| `venue` | 会议、期刊、来源或 arXiv 分类 |
| `citations` | 可获取的引用数 |
| `influential_citations` | Semantic Scholar 提供的 influential citations |
| `references_count` | 可获取的参考文献数量 |
| `authors` | 作者列表，使用分号分隔 |
| `doi` | DOI |
| `arxiv_id` | arXiv ID |
| `url` | 论文或元数据链接 |
| `sources` | 命中或补全该记录的数据源 |
| `is_survey` | 是否像 survey/review/tutorial 类型论文 |
| `abstract` | 摘要 |

不要把高分直接理解为“已经做过”。判断 close prior art 时，应人工比较论文的实际问题、方法、数据/领域和评估目标是否与 proposed topic 对齐。

## 排序信号

脚本使用以下启发式信号进行重排：

- 输入 topic/keywords 与标题+摘要的内容相似度。
- topic、方法、数据/领域、评估概念的覆盖度。
- 有区分度的领域锚点，而不是泛化研究词。
- 方法或技术路径相关概念。
- 对引用数做 log 缩放，避免老论文过度占优。
- 请求年份范围内的近期性。
- 用户指定 venue 匹配。
- 已知高质量 venue 的弱加权。
- survey/review/tutorial 信号。

这些信号适合快速 triage，不是严格的文献计量结论。

## 数据源

脚本会尽量使用：

- OpenAlex：跨学科学术元数据和引用信息。
- Crossref：出版元数据和 DOI 覆盖。
- DBLP：计算机科学会议和期刊元数据。
- arXiv：近期预印本。
- Semantic Scholar：可选搜索源，也用于元数据补全。

如果某个数据源失败，脚本会继续使用其他来源，并在 `prior_art_conclusion.md` 中披露失败状态。

## 使用建议

- 第一轮 prior-art 侦察建议设置 `max_results=50` 或更高。
- `keywords` 不要只写大词；应加入同义词、缩写、数据集、任务名、方法名和应用领域。
- 如果结果过宽，增加领域、数据集、任务或 venue 限制。
- 如果结果过窄，增加同义词、上位概念和相邻任务名称。
- 在正式宣称 novelty 前，阅读最接近论文的全文、related work、references 和 limitations。

## 常见问题

### 这个工具能证明“没人做过”吗？

不能。它只能说：在当前检索源和输入词下，没有发现清晰的 prior match。没有检索到证据不等于不存在 prior work。

### 为什么某些明显相关论文没有出现？

常见原因包括：关键词没有覆盖常用说法、论文没有摘要、API 覆盖缺口、限流、年份范围过窄、venue 限制过窄。可以扩大关键词和年份范围后重跑。

### 为什么 survey 排名靠前？

Survey/review 能提示某个领域已有系统性整理，但它不一定是直接 empirical prior art。判断“是否已经做过”时，要区分 survey coverage 和真正实现同一问题/方法/领域组合的论文。

### 可以把结果直接当作文献综述吗？

不建议。它适合作为第一轮 prior-art scouting。正式文献综述仍需要明确检索式、纳入/排除标准、人工筛选和全文阅读。
