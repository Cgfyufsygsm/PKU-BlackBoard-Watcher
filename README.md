# PKU-BlackBoard-Watcher

在本地（WSL/Linux）运行的教学网（Blackboard Learn）更新监控脚本：抓取课程内容 → 去重 → 推送（后续）。

## 当前进度（已完成）

- Step A：项目骨架 + `python -m app.main` 可运行，日志写入 `logs/run.log`
- Step B：Playwright 导出登录态 `data/storage_state.json`，并可做登录态校验
- Step C：从 portal 页面保存 `data/debug_courses.html`，并从“在以下课程中，您是学生”区域提取当前学期课程链接（保守策略 + fallback）
- 代码结构：`app/bb/` 已按登录/课程/公告拆分模块，方便后续继续扩展教学内容/作业/成绩

## 下一步（准备做）

- Step D：按“四个板块”逐个实现抓取（先导出 debug HTML，再定 selector）
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
   - TODO：有些老师会在这个板块下面布置作业（我也不理解为什么），比如自然语言处理。到时候需要特殊解析。

3. 课程作业（Assignments）
   - 课程作业的页面和教学内容没有本质区别，都是 listContent.jsp 列出来的。所以解析方式可以参考课程内容。但是需要注意的是，我们需要重点解析**可提交的作业**，点进去可以看得到作业到期日期以及分数（如果还没有提交）。
   - 课程名
   - 标题
   - 发布时间（若页面可读到）
   - 截止时间（Due）
   - 是否已提交（Submitted: yes/no/unknown）
   - 详情 URL

4. 个人成绩（Grades）
  - 评分项标题（例如作业/测验/期中等）
  - 时间（若页面可读到：发布时间/评分时间/截止时间等，按页面语义取一个可用字段）
  - 具体成绩（例如 95/100、A、已评分/未评分等原样字符串）
  - 课程名（成绩页是分课程的）
  - 详情 URL（若有）

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

## 生成登录态（第一次需要）

- `python scripts/export_state.py`
- 在弹出的 Chromium 窗口完成登录，然后回到终端按 Enter 保存
- 输出文件：`data/storage_state.json`

## 运行与验证

- Hello only：`python -m app.main`
- 校验登录态：`python -m app.main --check-login`
- 保存 portal HTML + 抓“学生”课程列表：`python -m app.main --list-courses`
  - Debug 文件：`data/debug_courses.html`
- 抓取某门课“课程通知”的 debug HTML：`python -m app.main --debug-announcements --course-query "信息学中的概率统计"`
  - Debug 文件：`data/debug_course_entry.html`、`data/debug_announcements.html`
  - 同时会在日志里输出解析到的公告数量与前 10 条（发布时间/标题/URL）
- 离线解析已保存的公告 HTML：`python -m app.main --parse-announcements-html data/debug_announcements.html`
- 把公告字段导出成 JSON（方便人工核对）：`python -m app.main --parse-announcements-html data/debug_announcements.html --announcements-json data/announcements.json`
- 在线抓取并导出 JSON：`python -m app.main --debug-announcements --course-query "信息学中的概率统计" --announcements-json data/announcements.json`
- 抓取某门课“教学内容”的 debug HTML：`python -m app.main --debug-teaching-content --course-query "信息学中的概率统计" --teaching-content-json data/teaching_content.json`
  - Debug 文件：`data/debug_teaching_content.html`
- 离线解析已保存的“教学内容”HTML：`python -m app.main --parse-teaching-content-html data/debug_teaching_content.html --teaching-content-json data/teaching_content.json`

## 产物位置

- 日志：`logs/run.log`
- 登录态：`data/storage_state.json`
- SQLite：`data/state.db`（目前仅初始化建表）
- Debug HTML：`data/debug_courses.html`
  - 通知 debug：`data/debug_course_entry.html`、`data/debug_announcements.html`

## 给 cron 的入口（后续会完善）

- `bash check.sh`
  - 当前 `check.sh` 只做 `--check-login`；后续会改成“抓取 → 去重 → 推送”的完整闭环
