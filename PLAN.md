# 项目计划（PLAN）

目标：在本地（WSL/Linux）运行一个脚本，自动抓取 PKU Blackboard Learn（教学网）四个板块的数据（通知/教学内容/作业/成绩），做 SQLite 去重，并对“新内容/更新”做 Bark 推送，最终可由 `check.sh`/cron 定时运行。

## 当前进度（已实现）

- Step A：项目骨架可运行，日志落盘 `logs/run.log`
- Step B：Playwright 导出/复用登录态 `data/storage_state.json`，并可做登录态校验
- Step C：从 portal 页面提取“当前学期、学生身份”的课程列表（含 `course_id`）
- Step D：四个板块均已做到“在线抓 debug HTML + 离线解析 + 导出 JSON 便于人工核对”
  - 通知：`app/bb/announcements.py`
  - 教学内容：`app/bb/teaching_content.py`（可识别内容里的可提交作业并按作业处理）
  - 作业：`app/bb/assignments.py`（列表页识别 `uploadAssignment`；详情页解析到期/满分/成绩/提交状态）
  - 成绩：`app/bb/grades.py`（解析类别/评分时间/到期/成绩/链接）
- Step E：SQLite 去重 + Bark 推送闭环（含定时运行）
  - 全量抓取：`app/bb/fetch_all.py:fetch_all_items`（单 Playwright context、课程级失败隔离、`page.goto` 带重试）
  - 数据结构：`app/models.py:Item`（统一 `source/course_id/course_name/title/url/ts/due/external_id/raw`）
  - 去重与更新：`identity_fp()`（同一逻辑条目唯一行）+ `state_fp()`（同一条目的状态变化判定为更新）
  - DB：`app/store.py`（upsert、new/updated/unchanged 分类、`sent_state_fp` 已通知状态、`ack_state()`）
  - 首次运行：bootstrap 防刷屏（仅 1 条初始化通知，并把本轮全部条目标记为已通知）
  - 推送：`app/notify.py`（课程名简化、时间中文可读、消息不带可点击链接；在线提交作业附 due/提交时间）
  - 运行入口：`app/main.py --run/--fetch-all/--dry-run-out`
  - 定时入口：`check.sh` + crontab（`data/cron.lock` 文件锁、默认 `--limit 100`、优先 `conda run`）

## 验收（验证方式）

- 预览推送（不发到手机）：`python -m app.main --run --dry-run --dry-run-out data/bark_preview.json`
- 连续运行两次 `--run`：第二次应无新增/无更新推送（除非 Blackboard 页面内容真的变了）

## 关键定义

- 新内容（new）：`identity_fp` 在 DB 中不存在
- 更新（updated）：`identity_fp` 已存在，但 `state_fp` 变化（例如成绩从 `-` 变为具体分数；作业从未提交变为已提交）
- 不变（unchanged）：`identity_fp/state_fp` 都未变化

## Step F（后续）

- 稳定性：更细粒度的超时/重试与异常分类（登录/跳转/解析）
- 通知体验：批量折叠/摘要、优先级排序、避免同一课程短时间刷屏
- 可维护性：更强的 debug 工具（保存关键页面、错误快照、重放解析）
