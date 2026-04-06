# Opportunity Filter Engine — 长期项目计划

## 项目愿景
帮低年级本科生（尤其国际生）从散乱的机会信息中，快速找到"自己现在有机会拿到"的 research / internship / summer program，并提供可执行的申请指导。

## 当前状态 (2026-04-06)
- ✅ 312 条机会数据（33 manual + 25 RSS + 254 SRO）
- ✅ 三层评分引擎（eligibility/readiness/upside）
- ✅ Streamlit MVP 可运行
- ✅ UIUC OUR RSS + SRO 抓取器
- ✅ 数据刷新自动化 (`make refresh`)
- ✅ LLM auto-tagger（有 bug 待修）
- ✅ Dashboard + About 页面
- ✅ GitHub: github.com/EricXu-0805/opportunity-filter-engine
- ✅ 39 测试用例通过

---

## Phase 1: 产品定义 ✅ 完成
## Phase 2: 数据集建设 ✅ 完成 (312条)
## Phase 3: 评分引擎 ✅ 完成
## Phase 4: MVP 界面 ✅ 完成

---

## Phase 5: 申请辅助 ⬅️ 当前阶段
**目标：** 从"发现机会"升级到"指导行动"
**预计时间：** 1-2 周

| 任务 | 状态 | 说明 |
|------|------|------|
| 5.1 修复 tagger bug | 🔴 | 从 title/URL/keywords 等更多字段提取信息 |
| 5.2 Cold email 生成器 | 🔴 | 模板化冷邮件，集成到每个机会卡片 |
| 5.3 Resume gap 分析器 | 🔴 | 缺什么技能、建议修什么课、怎么改简历 |
| 5.4 集成到 Streamlit | 🔴 | 每个卡片加"生成冷邮件"和"简历建议"按钮 |
| 5.5 综合测试套件 | 🔴 | 端到端测试：数据完整性、评分正确性、推荐合理性 |

**退出标准：**
- 用户能对任意机会一键生成冷邮件
- 用户能看到针对每个机会的个性化简历建议
- 所有测试通过，覆盖 collector → tagger → matcher → recommender 全链路

---

## Phase 6: 数据质量提升
**目标：** 减少 "unknown"，提升推荐精度
**预计时间：** 1-2 周

| 任务 | 说明 |
|------|------|
| 6.1 全量 SRO deep scrape | 跑通 279 条详情页，提升 intl/paid/skills 字段质量 |
| 6.2 LLM 增强标签（有 API key 时） | 用 gpt-4o-mini 批量提取结构化字段 |
| 6.3 人工审核界面 | 在 Streamlit 加 admin 页面，快速审核/修正标签 |
| 6.4 数据质量仪表盘 | 显示字段完成率、unknown 比例趋势 |
| 6.5 去重和过期清理 | 检测重复机会，标记过期（deadline 已过）|

**退出标准：** unknown 字段 < 30%，international_friendly 覆盖率 > 80%

---

## Phase 7: 扩展数据源
**目标：** 从 UIUC 扩展到更广泛的机会
**预计时间：** 2-3 周

| 任务 | 说明 |
|------|------|
| 7.1 NSF REU API 集成 | 500+ NSF 资助的暑期研究项目 |
| 7.2 USAJobs API 集成 | 联邦实习（多数需要 citizenship） |
| 7.3 Pathways to Science | 外部暑期项目聚合 |
| 7.4 其他学校 REU 页面 | MIT MSRP, Stanford SURF, Caltech SURF 等 |
| 7.5 SerpApi / Google Jobs | 按关键词搜索行业实习（需 API key） |

**退出标准：** 数据库 1000+ 条机会，覆盖 5+ 数据源

---

## Phase 8: 生产化部署
**目标：** 从本地 Streamlit 升级为可公开访问的产品
**预计时间：** 2-3 周

| 任务 | 说明 |
|------|------|
| 8.1 FastAPI 后端 | RESTful API，替代直接 JSON 文件读取 |
| 8.2 PostgreSQL + pgvector | 结构化数据 + 语义搜索 |
| 8.3 Next.js / React 前端 | 替代 Streamlit，更好的 UX |
| 8.4 部署到 Railway / Vercel | 公开访问，域名绑定 |
| 8.5 自动数据刷新 cron | 每日自动抓取 + 标签更新 |

**退出标准：** 可通过 URL 访问，自动每日更新数据

---

## Phase 9: 用户系统 + 增长
**目标：** 多用户支持，让更多 UIUC 学生用起来
**预计时间：** 3-4 周

| 任务 | 说明 |
|------|------|
| 9.1 用户注册/登录 | OAuth (Google/GitHub) |
| 9.2 个人 profile 保存 | 不用每次重新填 |
| 9.3 收藏 + 申请追踪 | 标记已申请/感兴趣/已拒 |
| 9.4 邮件/推送提醒 | 新机会匹配或 deadline 临近提醒 |
| 9.5 校内推广 | ACM/WCS/SWE 等社团合作 |
| 9.6 反馈循环 | 用户标记"推荐是否准确"，优化权重 |

---

## Phase 10: 语义匹配 + AI 升级
**目标：** 超越关键词匹配，理解语义

| 任务 | 说明 |
|------|------|
| 10.1 sentence-transformers 嵌入 | 机会描述 + profile 的向量化 |
| 10.2 pgvector 语义搜索 | "我想做 AI 安全相关的" → 语义匹配 |
| 10.3 LLM 个性化推荐理由 | 从模板升级为 AI 生成的解释 |
| 10.4 LLM 冷邮件定制 | 基于教授论文生成高度个性化邮件 |

---

## Phase 11: 多校扩展
**目标：** 从 UIUC → 全美

| 任务 | 说明 |
|------|------|
| 11.1 配置驱动的多校架构 | sources.yaml 支持任意学校 |
| 11.2 Top 20 学校覆盖 | Berkeley, MIT, Stanford, CMU... |
| 11.3 学校间机会交叉推荐 | UIUC 学生也能看到 MIT MSRP |

---

## 里程碑时间线

| 时间 | 里程碑 | 关键指标 |
|------|--------|----------|
| 2026-04 中 | Phase 5 完成 | 冷邮件 + 简历建议 + 测试套件 |
| 2026-04 底 | Phase 6 完成 | unknown < 30% |
| 2026-05 中 | Phase 7 完成 | 1000+ 条机会 |
| 暑假期间 | Phase 8-9 | 部署上线 + 用户系统 |
| 暑假后 | Phase 10-11 | 语义匹配 + 多校扩展 |

---

## 核心原则
1. **先做窄、做深** — UIUC ECE/CS 国际生做透，再扩展
2. **数据质量 > 数据量** — 312 条高质量 > 10000 条垃圾
3. **推荐要可解释** — 不只给分数，要告诉用户 why
4. **行动导向** — 不止"你应该看这个"，而是"你下一步做这个"
5. **每次迭代必须有测试** — 不允许 regression

---
*Created: 2026-04-06 | Author: Eric Xu + 行者*
