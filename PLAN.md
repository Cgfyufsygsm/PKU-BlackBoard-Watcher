# 项目计划（PLAN）

目标：在本地（WSL/Linux）运行一个脚本，自动抓取 PKU Blackboard Learn（教学网）四个板块的数据（通知/教学内容/作业/成绩），做 SQLite 去重，并对“新内容”做 Bark 推送，最终可由 `check.sh`/cron 定时运行。

## 当前进度

- Step A（完成）：项目骨架可运行，日志落盘 `logs/run.log`
- Step B（完成）：Playwright 导出/复用登录态 `data/storage_state.json`，并可做登录态校验
- Step C（完成）：从 portal 页面提取“当前学期、学生身份”的课程列表（含 `course_id`）
- Step D（完成）：四个板块均已做到“在线抓 debug HTML + 离线解析 + 导出 JSON 便于人工核对”
  - 通知：`app/bb/announcements.py`
  - 教学内容：`app/bb/teaching_content.py`（可识别内容里的可提交作业并按作业处理）
  - 作业：`app/bb/assignments.py`（列表页识别 `uploadAssignment`；详情页解析到期/满分/成绩）
  - 成绩：`app/bb/grades.py`（解析 `itemCat` 类别、`lastactivity`、`duedate`、`grade_raw/grade`、`url`）

## Step E：SQLite 去重 + 推送闭环（要做的具体事情）

### E1. 统一“可入库”的 Item 结构

- 目标：四个板块的解析结果都能映射为一个统一结构，便于后续去重/推送。
- 建议字段（以 `app/models.py:Item` 为中心，必要时扩展）：
  - `source`：`announcement|teaching_content|assignment|grade_item`
  - `course_id`：课程唯一 id（例如 `_86215_1`，用于跨学期同名课程）
  - `course_name`：课程名（展示用）
  - `title`：标题
  - `url`：详情链接（无则空字符串）
  - `ts`：事件时间（例如通知发布时间、成绩最后活动时间等；拿不到就空）
  - `due`：截止时间/日期（作业/成绩作业项可用；拿不到就空）
  - `raw`：完整原始字段（用于 debug、回溯与后续增强）

状态：已实现（`app/models.py` + `app/bb/fetch_all.py`），并提供 `python -m app.main --fetch-all --items-json data/items.json` 用于验证。

### E2. 指纹（fingerprint）规则与去重策略

- 目标：同一条内容在多次运行间保持稳定 fp，“只推一次”。
- 原则：
  - 优先使用稳定 id（例如 `course_id` + 页面自带的行 id / content id / outcome id）；
  - 其次使用 `url`（若稳定）；
  - 最后再用 `title/ts/due` 补齐。
- 注意：`grade` 字段可能是数字、`-`、或“否”等文本；`ts/due` 缺失时也要能去重。

状态：已实现（`app/models.py:Item.fingerprint()`）。

### E3. SQLite 表结构与 store API

- 目标：实现可重复运行且安全的 DB 写入、查询与去重。
- 实现点：
  - 在 `app/store.py` 补齐：`seen(fp)`, `bulk_filter_new(items)`, `mark_seen/mark_sent`（命名可调整）
  - 支持最小迁移：如果需要从现有 `course` 字段升级到 `course_id/course_name`，提供向后兼容或一次性迁移逻辑
  - 推荐写入策略：
    - 先把“新条目”插入 DB（`created_at`），不立刻标 sent
    - 推送成功后更新 `sent_at`

状态：已实现基础 DB 迁移/去重接口（`app/store.py:init_db/bulk_filter_new/upsert_seen/mark_sent`）；推送闭环接入在 E5/E6。

### E4. 全量抓取入口（一次运行抓全量）

- 目标：一次运行内，复用同一个 Playwright context，依次抓取所有课程的四个板块，输出 `list[Item]`。
- 实现点：
  - 新增一个抓取聚合函数（例如 `fetch_all_items(...)`），内部：
    - 课程列表 → 遍历每门课
    - 每门课各板块抓取/解析失败要隔离（try/except），避免“单课失败导致全局失败”
  - 运行日志要包含：课程数、每门课每板块 item 数、失败原因摘要

状态：已实现（`app/bb/fetch_all.py:fetch_all_items`），入口已接到 CLI：`python -m app.main --fetch-all`。

## 已实现部分的实现说明（E1–E4）

- 统一 Item：`app/models.py:Item`，核心字段为 `source/course_id/course_name/title/url/ts/due/external_id/raw`。
  - `fp`（`identity_fp()`）：稳定身份 key（同一评分项/公告/条目只对应 DB 一行），优先 `course_id + source + external_id`，否则用 `url` 或 `title` fallback
  - `state_fp()`：状态 hash，用于检测同一身份条目的变化（例如成绩从 `-` 变为具体分数）
- 全量抓取：`app/bb/fetch_all.py:fetch_all_items`
  - 打开 portal → `eval_courses_on_portal_page()` 拿课程列表（含 `course_id`）
  - 遍历课程：进入课程入口页（通常就是“课程通知”页），并从入口页 HTML 用正则提取左侧菜单的 `教学内容/课程作业/个人成绩` 链接，再逐页抓 HTML 并调用对应 `parse_*_html()`
  - 每个板块解析得到的 dict 会通过 `_as_item()` 映射为统一 `Item`，原始字段会保存在 `raw` 里方便后续扩展/排错
  - 单课程/单板块失败会记录到 `errors`，不会中断全局抓取；若某门课未启用某个工具（左侧菜单无入口），会被视为“跳过”而非硬错误
  - 作业详情页：对在线提交作业会打开 `uploadAssignment` 详情页补齐到期/满分/成绩；若详情页落在“已提交/历史/评分”视图而缺少统一的“作业信息”，会自动跟随“开始新的”（`action=newAttempt`）以解析统一字段
- DB 去重接口：`app/store.py`
  - `init_db()` 会建表并做最小迁移（兼容旧的 `course` 字段）
  - `bulk_filter_new()` 用身份 key 过滤“新条目”；`bulk_classify()` 支持区分 new/updated/unchanged；`upsert_seen()` 会对同一身份条目做更新（不会插入重复行）

### E5. Bark 推送实现

- 目标：对“新内容”推送到 iOS（Bark），失败可重试一次且不阻塞整轮。
- 实现点：
  - `app/notify.py` 用 `requests` 落地 `send_bark(endpoint, title, body, url=None)`
  - `BARK_ENDPOINT` 为空时：不推送，但仍记录日志（便于 dry-run）
  - 标题/正文格式建议统一：
    - title：`[课程名] <标题>`
    - body：追加 `ts/due/grade` 的可读摘要（按 source 选择性拼）

当前实现的通知类型（`app/notify.py`）：
- 新通知：`[课程] 新通知`，包含发布时间/发帖者/内容摘要
- 新教学内容：`[课程] 新教学内容`，包含附件是否存在/内容摘要
- 新作业：`[课程] 新作业`，包含是否在线提交（作业到期/满分/出分更多信息会优先通过成绩页的作业评分项体现）
- 作业提交状态：会在抓 `uploadAssignment` 详情页时解析 `submitted/submitted_at_raw` 并纳入状态变化（未提交→已提交会触发作业更新通知）
- 新成绩项：`[课程] 新成绩项`，包含类别/成绩/到期/时间
- 作业出分 / 作业成绩变动：由“成绩页”里 `category=作业` 的 `grade_item` 变化触发
- 成绩出分 / 成绩变动：由其它 `grade_item` 的 `grade_raw` 变化触发

### E6. main.py 主流程与 CLI

- 目标：提供一个稳定的“跑一轮”命令，支持 dry-run、限流与可观测 summary。
- 建议参数：
  - `--run`：抓取 → 去重 → 推送 → 标记 sent
  - `--dry-run`：只抓取/去重/打印，不写 sent（可选：也不写入新条目）
  - `--limit`（或继续用 `POLL_LIMIT_PER_RUN`）：控制单次最多推送条数
- 需要输出 summary：总抓取数、新数、推送数、耗时

当前实现（`app/main.py`）：
- `--run` 会对比 DB 中 `sent_state_fp` 与本轮 `state_fp` 来决定是否需要推送，推送成功后写入 `sent_at/sent_state_fp`，避免重复推送同一状态
- 对 `grade_item/assignment`：状态变化会产生“更新”通知（尽量覆盖满分/截止/成绩/状态等变化）
- 对 `announcement/teaching_content`：默认只推“新条目”；如果老师编辑旧条目导致 `state_fp` 改变，会自动 ack 掉避免反复 pending

### E7. check.sh / cron 入口

- 目标：cron 环境下一条命令就能跑通。
- 实现点：
  - `check.sh` 从 `--check-login` 切到 `--run`
  - conda 环境建议使用非交互方式（例如 `conda run -n bbwatcher python -m app.main --run`），避免 `conda activate` 在 cron 里不生效

## Step F：稳定性与可维护性（后续）

- 超时/重试与单课程失败隔离进一步完善（Playwright page.goto、等待条件、异常分类）
- 更清晰的日志层级与关键字段（课程/板块/URL/耗时）
- 可选：将“在线抓取”和“离线解析”进一步拆成可复用组件，方便调试与单元测试
- 云端无人值守：当 `storage_state.json` 失效时可使用 `BB_USERNAME/BB_PASSWORD` 自动刷新登录态（前提：统一认证无需验证码/2FA）

## 完成标准（验收）

- 连续运行两次 `--run`：第二次应 `new=0 sent=0`
- DB 中每条 item 有稳定 fp；推送成功后 `sent_at` 被设置
- `POLL_LIMIT_PER_RUN` 生效（单次推送不超过限制）
- 无 `BARK_ENDPOINT` 时不会报错（仅日志提示跳过推送）

## “新内容 vs 更新”定义（供 Step E 使用）

- 新内容（new）：身份 key（`fp` / `identity_fp()`）在 DB 中不存在（第一次见到这个评分项/公告/条目）
- 更新（updated）：身份 key 已存在，但 `state_fp()` 发生变化（例如成绩从 `-` 变为具体分数）
- 不变（unchanged）：身份 key 已存在且 `state_fp()` 未变化

后续推送策略（E5/E6）会基于上述分类决定：
- 新内容：通常推送一次
- 更新：对“状态变化有意义”的类型推送（例如成绩出分/改分），而 DB 只更新同一行，不产生重复行
