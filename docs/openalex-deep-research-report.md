# OpenAlex API 调研报告

**执行摘要：** OpenAlex 是一个覆盖全球学术文献的开放元数据库，提供 `/works` 等 REST API 接口，可按关键词（`search`）、作者ID、机构ID、DOI 等多种方式检索论文。它返回丰富的元数据：包括论文标题（`display_name/title`）、作者列表（`authorships`）、出版年份、DOI（`ids.doi`）、引用数（`cited_by_count`）、参考文献列表（`referenced_works`）、相关论文列表（`related_works`）以及开放获取信息（`open_access`）等。对计算机科学领域而言，OpenAlex 拥有超过 3.2 亿条记录，涵盖arXiv、Crossref、DOAJ、PubMed 及上千个机构/学科数据库。其引用图谱功能完善：每个作品对象包含被引用数、参考文献ID列表和算法推荐的相关论文ID。作为检索引擎，OpenAlex 支持全文搜索（`search`参数搜索标题/摘要/全文），也支持基于精确条件的过滤（`filter`参数，如按`author.id`、`institution.id`、`doi`等）。 

**API 端点与查询模式：** 主要使用 `/works` 端点。可通过 `search=关键词` 执行全文关键字搜索，或用 `filter=` 进行字段过滤，例如按作者ID、机构ID、主题ID（topics.id）、DOI、出版年份等筛选。支持布尔运算（`AND/OR/NOT`）和通配符查询。示例：  
- 按作者查找：`GET https://api.openalex.org/works?filter=author.id:A1234567890`  
- 按关键词查找：`GET https://api.openalex.org/works?search=%E5%A4%8D%E6%9D%82+%E6%95%B0%E5%AD%97`  
- 按DOI批量查找：`GET https://api.openalex.org/works?filter=doi:https://doi.org/10.xxx/yy|https://doi.org/10.xxx/zz&per_page=100`。  

**支持的响应字段（元数据 & OA 信息）：** OpenAlex 返回 JSON 列表，每篇论文包含多种字段：  
- **基本元数据：** `title`（标题）、`authors`（作者列表在`authorships`中）、`publication_year`、`doi`；  
- **外部标识：** `ids` 对象包含 DOI、MAG ID、PubMed ID 等；  
- **引用与关系：** `cited_by_count`（引用次数）、`referenced_works`（参考文献ID列表）、`related_works`（相关论文ID列表）；  
- **开放获取信息：** `open_access` 对象包括 `is_oa`、`oa_status`（金/绿/混合/闭源等）和最佳全文链接 `oa_url`；`locations` 列表包含所有发现的版本，每个`location`有 `pdf_url`、`landing_page_url`、`license` 等；`best_oa_location` 指出当前最优OA版本（含直链`pdf_url`）。例如，查询 DOI `10.7717/peerj.4375` 返回的 JSON 可见 `best_oa_location` 字段，其中`pdf_url` 即可用于直接下载 OA PDF：  
```json
{
  "best_oa_location": {
    "is_oa": true,
    "landing_page_url": "https://doi.org/10.7717/peerj.4375",
    "pdf_url": "https://peerj.com/articles/4375.pdf",
    "license": "cc-by"
  }
}
```  

**PDF 解析能力：** OpenAlex 可提供已收录OA论文的直接PDF链接。其 `best_oa_location` 对象的 `pdf_url` 字段（如果非 null）即为该论文的可下载PDF。此外，OpenAlex 对50M+篇论文构建了全文内容库，可通过 Content API 下载：`GET https://content.openalex.org/works/{OpenAlexID}.pdf?api_key=...`。可用过滤器 `has_content.pdf:true` 找到可下载PDF的论文。注意仅开放获取论文有直接PDF链接；闭源论文在OpenAlex中仅返回元数据，通常不能直接从 OpenAlex 获得全文。  

**覆盖范围：** OpenAlex 数据源广泛，**跨学科**包括科技、医学、人文等。其文献量巨大（2026 年统计约3.27亿条记录），更新频率高：系统每日从 Crossref、DataCite、PubMed、DOAJ、arXiv 等数千家机构和仓储持续抓取新记录。对于**计算机科学**而言，常见的会议和期刊DOI均可在Crossref中找到，OpenAlex通过DOI引入这些记录，因此也能覆盖IEEE/ACM等主流出版物（需通过DOI访问）。arXiv 预印本也在索引中，通过`indexed_in`字段可见。不过，OpenAlex自身只收录开源可获取的论文元数据，对有版式保护的出版商论文只提供少量元信息（引用等），无法直接下载PDF。

**引用图谱特性：** 每个作品节点包含完整的引用网络：`cited_by_count`统计被引次数，`referenced_works`列出参考文献的OpenAlex ID，`related_works`列出主题相关论文。例如，可以通过`filter=cites:Wxxxxx`查询引用某论文的所有作品。这种有向图功能对于文献追踪和关联分析十分有用。

**鉴权与速率限制：** API 基本使用**无需注册**、**免费开放**。注册免费账号并获得 API key 可以将每日配额提升10倍，并便于跟踪使用情况。默认每天赠送的免费额度足以支持常规调研（约相当于 10 万次查询），超过可通过预付费方式扩容。每秒最多允许 100 次请求，单次调用可用 `per_page=100` 获取更多结果；超过速率或当天额度上限会返回 429 错误。查询时建议使用 `select` 参数减少不必要字段，批量ID查询使用 `|` 分隔实现单次拉取多个记录。

**数据时效性：** OpenAlex 背后数据持续更新。核心文献库每日同步新增数万条记录。`created_date` 和 `updated_date` 字段指示入库和最后更新时间。可以通过付费筛选器（`from_updated_date` 等）增量获取最新变化。总之，对新发表的CS论文（含 arXiv 预印本）而言，OpenAlex 通常几天内能反映更新。

**标识符与去重：** OpenAlex 为每篇作品分配内部ID（如 `W123456789`），并在 `ids` 对象中保留 DOI、MAG ID、PubMed ID 等外部标识。作品的**权威外部ID**是 DOI。系统会根据 DOI 等元数据合并重复记录，确保同一论文只有一个条目。`indexed_in` 字段标明论文来源（如是否为 arXiv 预印本）。这种设计保证去重和统一引用。

**已知限制和注意事项：** OpenAlex 重点在开放和可下载内容，对付费墙后的文献不提供PDF。某些学术社交网站（如 ResearchGate、SSRN）由于登录或验证码限制不被包括。长URL搜索（包含大量 OR 术语）可能因长度限制失败。此外，ArXiv 上的早期版本和同行评议版本会作为不同 location 存储在同一工作条目中，因此需注意 `version` 字段区别。总体而言，OpenAlex 提供数据广度极佳，但商业出版社的全文仍需通过其他渠道获取。

## 与 Semantic Scholar & arXiv 的比较

|      特性      | **Semantic Scholar**        | **OpenAlex**                   | **arXiv**                        |
|:--------------:|:--------------------------:|:-----------------------------:|:--------------------------------:|
| **检索质量**   | 🔍 高质量跨学科检索；算法相关性强（自然语言搜索） | 🔍 **广覆盖**，支持字段筛选+全文搜索，但相关性排序略弱 | 🔍 限于预印本，自然相关性较低（关键词匹配） |
| **PDF 可用性** | 📄 仅 OA 论文给出 PDF 链接（`openAccessPdf.url`） | 📄 OA 论文可获 `best_oa_location.pdf_url`；并提供大规模全文库（需API key） | 📄 **稳定**提供所有预印本 PDF（固定链接） |
| **引用图谱**   | 📈 完备（引用、被引用、影响分数等） | 📈 完备（`cited_by_count`、`referenced_works`、`related_works`） | 📈 不支持引用关系（无引用计数） |
| **鉴权/限流**  | 🗝️ 免费 Key（100次/5分钟限额） | 🗝️ 可选免费 Key（提高每日额度10倍）；100次/秒上限 | 🗝️ 无需 Key；官方推荐 1 次/3 秒左右访问 |
| **在管道中的角色** | ⭐️ 主力搜索引擎（语义搜索），返回论文列表 | ⭐️ 补充搜索引擎+OA PDF 解析器；提供附加元数据和PDF链接 | ⭐️ 备用全文源；主要用于下载 CS 预印本PDF |

## 示例 API 请求

- **按 DOI 查找并提取 PDF 链接：**  
  ```bash
  curl "https://api.openalex.org/works?filter=doi:https://doi.org/10.7717/peerj.4375&select=best_oa_location"
  ```  
  返回 JSON 中的 `best_oa_location.pdf_url` 即为 PDF 链接。  
- **按关键词搜索：**  
  ```bash
  curl "https://api.openalex.org/works?search=%E8%AE%A1%E7%AE%97%E6%9C%BA&per_page=5"
  ```  
  返回前5条与“计算机”相关的论文元数据列表。  
- **示例返回片段（JSON）：**  
  ```json
  {
    "meta": { "count": 1, "per_page": 25 },
    "results": [
      {
        "id": "https://openalex.org/W2741809807",
        "doi": "https://doi.org/10.7717/peerj.4375",
        "display_name": "The state of OA: a large-scale analysis...",
        "best_oa_location": {
          "is_oa": true,
          "landing_page_url": "https://doi.org/10.7717/peerj.4375",
          "pdf_url": "https://peerj.com/articles/4375.pdf",
          "license": "cc-by"
        },
        "cited_by_count": 234
      }
    ]
  }
  ```

## 检索–PDF 解析流程图

```mermaid
flowchart LR
  用户查询 --> SemanticScholar[Semantic Scholar (主检索)]
  SemanticScholar -->|候选论文列表| OpenAlex[OpenAlex (补充检索)]
  SemanticScholar -->|预印本搜索| arXiv[arXiv (预印本源)]
  OpenAlex -->|最佳OA PDF链接| PDF解析[PDF 解析器]
  arXiv -->|PDF下载| PDF解析
  PDF解析 --> MinerU[MinerU 解析及知识库]
```

**给 Claude 的建议：** 推荐将 **OpenAlex 作为 Semantic Scholar 的补充检索引擎**，主要用于获取额外元数据和开放访问PDF链接。Claude 应先用 Semantic Scholar 搜索论文列表，再用 OpenAlex 对同一问题（关键词或DOI）发起检索，从返回结果中提取 `best_oa_location.pdf_url`（若非空则为可下载PDF）。同时可利用 OpenAlex 的 `filter=has_content.pdf:true` 进行 OA 论文筛选。具体流程：**Semantic Scholar → OpenAlex → arXiv → Unpaywall**，优先使用 Semantic Scholar 结果，遇 OA 论文则用 OpenAlex 拿 `pdf_url`，如无则再尝试 arXiv 或 Unpaywall 查找全文。这样 OpenAlex 在管道中既补充了检索覆盖，又提供了稳定的PDF解析路径。