# PKU-BlackBoard-Watcher

在本地（WSL/Linux）运行的教学网（Blackboard Learn）更新监控脚本：抓取课程内容 → 去重 → 推送（后续）。

## 当前进度（已完成）

- Step A：项目骨架 + `python -m app.main` 可运行，日志写入 `logs/run.log`
- Step B：Playwright 导出登录态 `data/storage_state.json`，并可做登录态校验
- Step C：从 portal 页面保存 `data/debug_courses.html`，并从“在以下课程中，您是学生”区域提取当前学期课程链接（保守策略 + fallback）
- Step D：按“四个板块”逐个实现抓取与离线解析（先导出 debug HTML，再定 selector），并可导出 JSON 供人工核对
- 代码结构：`app/bb/` 已按登录/课程/通知/教学内容/作业/成绩拆分模块，便于继续扩展与维护

更详细的里程碑与下一步拆解见：`PLAN.md`。

## 下一步（准备做）

- Step E：SQLite 去重 + 推送闭环（新内容只推一次）
- Step F：超时/重试/单课程失败隔离 + 更清晰日志

## 监控范围（四个板块）与字段

我们需要维护并去重/推送的内容分为 4 类（后续会在代码里对应到统一的数据模型与 `source` 字段）：

1. 课程通知（Announcements）
   - 课程名
   - 课程唯一标识（`course_id`，用于跨学期同名课程）
   - 标题/内容（正文文本或可读摘要）
   - 发布时间：原始字符串 + 规范化时间（ISO-8601，带 `+08:00`）
   - 详情 URL

2. 教学内容（Course Content / Materials）
   - 课程名
   - 标题
   - 内容（正文文本或可读摘要）
   - 发布时间：不记录（页面通常无明确发布时间）
   - 附件：只需要标记“是否有附件”（必要时可补充附件数量/文件名）
   - 详情 URL
   - 注意：有些老师会在这个板块下面布置“可在线提交的作业”（例如自然语言处理）。当条目链接指向 `/webapps/assignment/uploadAssignment` 时，会被当作 `assignment` 处理（`origin=teaching_content`）。

3. 课程作业（Assignments）
   - 课程作业的页面和教学内容没有本质区别，都是 listContent.jsp 列出来的。所以解析方式可以参考课程内容。但是需要注意的是，我们需要重点解析**可提交的作业**，点进去可以看得到作业到期日期以及分数（如果还没有提交）。
   - 课程名
   - 标题
   - 发布时间（若页面可读到）
   - 截止时间（Due）
   - 是否已提交（Submitted: yes/no/unknown）
   - 是否可在线提交（通过 URL 是否为 `/webapps/assignment/uploadAssignment` 判断）
   - 详情 URL

Assignments 当前实现分两层：
- 列表页（课程作业 / 教学内容里的作业条目）字段：`course_id`、`course_name`、`title`、`content_item_id`、`url`、`is_online_submission`、`submission_url`（以及 `origin` 可选）
- 详情页（uploadAssignment）可解析字段：`due_at_raw`（到期日期）、`points_possible`（满分）、`grade_raw`（成绩；未出分时常为 `-`）、`submitted`（是否已提交）、`submitted_at_raw`（提交时间，若可读到）
- 已提交作业：页面可能是评分/查看模式；可通过“开始新的”（`action=newAttempt`）进入新提交界面以抓取统一的“作业信息”字段（到期日期/满分）

4. 个人成绩（Grades）
  - 评分项标题（`title`）
  - 类别（`category`，来自 `<div class="itemCat">测试/作业</div>`；可能为空）
  - 最后活动时间（`lastactivity`，由 `lastactivity="<ms>"` 规范化为 ISO8601 +08:00；同时保留 `lastactivity_display`）
  - 成绩（`grade_raw` 原样字符串 + `grade` 数值化若可行）
  - 满分（`points_possible_raw` 原样字符串 + `points_possible` 数值化若可行）
  - 截止日期（若为作业评分项：`duedate`/`duedate_display`）
  - 详情 URL（`url`；有些行没有链接则为空）

说明：
- 课程维度需要有“唯一标识符”（例如 Blackboard course_id / internal id），不要只用课程名：跨学期可能出现同名课程。后续数据模型会同时保存 `course_id` + `course_name`，并在去重/fingerprint 时优先使用 `course_id`。
- “发布时间/时间”在不同页面可能没有明确字段；实现时以页面可稳定获取的时间信息为准，拿不到就留空但仍参与去重（通过标题/URL/课程等）。
- 去重 key 会基于（课程 + 类型 + 标题 + URL + 时间/截止时间/成绩等）生成稳定 fingerprint。

## 环境与依赖

- Python 3.10+（推荐使用你的 conda 环境，例如 `bbwatcher`）
- Playwright（Chromium）

安装依赖与浏览器：
- `bash scripts/init_playwright.sh`

如果你使用 conda 环境运行，建议先：
- `conda activate bbwatcher`

## 配置（.env）

从 `.env.example` 复制为 `.env`，至少填：

- `BB_BASE_URL`：教学网站点根地址，例如 `https://course.pku.edu.cn`
- `BB_LOGIN_URL`：登录入口（可以直接填 portal URL，未登录会自动跳转统一认证）
- `BB_COURSES_URL`：登录后才能访问的 portal 页面（用于校验与抓课程列表）

其它配置暂时可留空（推送/去重闭环在后续步骤实现）。

`BARK_ENDPOINT` 支持两种写法：
- 完整 URL：`https://api.day.app/<token>`
- 只填 token：`<token>`（程序会自动补全为 `https://api.day.app/<token>`）

当前推送不会附带可点击超链接（不设置 Bark 的 `url` 参数）。

推送里展示给人的时间会做一次格式化（示例：`2025-10-18T23:59:59+08:00` → `2025年10月18日 23:59:59`）；内部仍保留 ISO 时间用于去重/比较。

## 云端/无人值守登录（自动刷新登录态）

默认我们复用 `data/storage_state.json`。如果登录态过期，`--run` 会优先尝试用账号密码自动刷新登录态（适用于你的统一认证不需要验证码/2FA的情况）。

- 在 `.env` 配置：
  - `BB_USERNAME` / `BB_PASSWORD`
- 行为：
  - `--run` 启动时先校验登录态；若失效则自动打开 `BB_LOGIN_URL`，尝试提交账号密码并访问 `BB_COURSES_URL` 验证成功，然后重写 `BB_STATE_PATH`
  - 若自动登录失败，会退出并在日志里给出原因（不会打印密码）

## 生成登录态（第一次需要）

- `python scripts/export_state.py`
- 在弹出的 Chromium 窗口完成登录，然后回到终端按 Enter 保存
- 输出文件：`data/storage_state.json`

## 运行与验证

- Hello only：`python -m app.main`
- 校验登录态：`python -m app.main --check-login`
- 保存 portal HTML + 抓“学生”课程列表：`python -m app.main --list-courses`
  - Debug 文件：`data/debug_courses.html`
- 全量抓取“四个板块”（所有课程）并导出统一 Item JSON：`python -m app.main --fetch-all --items-json data/items.json`
  - 每条 item 都会包含：
    - `fp`：稳定身份 key（用于 DB 一行对应一个评分项/公告/条目；优先 `course_id + source + external_id`，否则用 `url`）
    - `state_fp`：状态 hash（用于检测同一身份条目的变化，例如“未评分 → 出分”）
- 跑一轮“抓取 → 去重（基于 fp/state_fp）→ Bark 推送”（Step E，建议先 dry-run）：`python -m app.main --run --dry-run`
  - 限制只抓前 N 门课：`python -m app.main --run --dry-run --course-limit 1`
  - 限制单次最多推送 N 条：`python -m app.main --run --limit 5`
  - dry-run 预览写入文件（不发到手机）：`python -m app.main --run --dry-run --dry-run-out data/bark_preview.json`
- 抓取某门课“课程通知”的 debug HTML：`python -m app.main --debug-announcements --course-query "信息学中的概率统计"`
  - Debug 文件：`data/debug_course_entry.html`、`data/debug_announcements.html`
  - 同时会在日志里输出解析到的公告数量与前 10 条（发布时间/标题/URL）
- 离线解析已保存的公告 HTML：`python -m app.main --parse-announcements-html data/debug_announcements.html`
- 把公告字段导出成 JSON（方便人工核对）：`python -m app.main --parse-announcements-html data/debug_announcements.html --announcements-json data/announcements.json`
- 在线抓取并导出 JSON：`python -m app.main --debug-announcements --course-query "信息学中的概率统计" --announcements-json data/announcements.json`
- 抓取某门课“教学内容”的 debug HTML：`python -m app.main --debug-teaching-content --course-query "信息学中的概率统计" --teaching-content-json data/teaching_content.json`
  - Debug 文件：`data/debug_teaching_content.html`
- 离线解析已保存的“教学内容”HTML：`python -m app.main --parse-teaching-content-html data/debug_teaching_content.html --teaching-content-json data/teaching_content.json`
- 抓取某门课“课程作业”的 debug HTML + 判定可在线提交：`python -m app.main --debug-assignments --course-query "信息学中的概率统计" --assignments-json data/assignments.json`
  - Debug 文件：`data/debug_assignments.html`
- 离线解析已保存的“课程作业”HTML：`python -m app.main --parse-assignments-html data/debug_assignments.html --assignments-json data/assignments.json`
- 抓取“已提交/未提交”作业详情页样板：`python -m app.main --debug-assignment-samples --course-query "信息科学中的物理学（上）" --submitted-assignment-query "第十一次作业" --unsubmitted-assignment-query "第十二次作业"`
  - 输出：`data/debug_assignment_submitted.html`、`data/debug_assignment_submitted_new_attempt.html`、`data/debug_assignment_unsubmitted.html`
  - 同时会在日志里输出两份样板的“到期日期/满分”（已提交样板会优先用“开始新的”后的页面解析）
- 抓取某门课“个人成绩”的 debug HTML：`python -m app.main --debug-grades --course-query "信息学中的概率统计"`
  - Debug 文件：`data/debug_grades.html`
- 离线解析已保存的“个人成绩”HTML：`python -m app.main --parse-grades-html data/debug_grades.html --grades-json data/grades.json`

## 产物位置

- 日志：`logs/run.log`
- 登录态：`data/storage_state.json`
- SQLite：`data/state.db`（目前仅初始化建表）
- Debug HTML：`data/debug_courses.html`
  - 通知 debug：`data/debug_course_entry.html`、`data/debug_announcements.html`

## 给 cron 的入口（后续会完善）

- `bash check.sh`
  - 当前 `check.sh` 只做 `--check-login`；后续会改成“抓取 → 去重 → 推送”的完整闭环
