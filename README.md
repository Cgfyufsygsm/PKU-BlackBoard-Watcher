# PKU-BlackBoard-Watcher

在本地/云端（WSL/Linux）运行的教学网（Blackboard Learn）更新监控脚本：抓取课程内容 → SQLite 去重 → Bark 推送。

更详细的计划、里程碑与设计说明见：`PLAN.md`。

## 监控范围

当前覆盖 4 个板块：
- 课程通知（Announcements）
- 教学内容（Course Content）
- 课程作业（Assignments，含在线提交作业的到期/满分/提交状态）
- 个人成绩（Grades，含评分项类别/评分时间/成绩变化）

## 快速开始

1) 安装依赖（建议在你的 conda 环境里，比如 `bbwatcher`）：
- `conda activate bbwatcher`
- `python -m pip install -r requirements.txt`
- 安装 Playwright 浏览器：`python -m playwright install chromium`
- 如果提示缺少系统依赖：按提示安装（Ubuntu/Debian 可用 `python -m playwright install-deps chromium`，可能需要 `sudo`）

2) 配置：
- 从 `.env.example` 复制为 `.env`
- 至少填写 `BB_BASE_URL/BB_LOGIN_URL/BB_COURSES_URL`
- 配置推送：`BARK_ENDPOINT`
- 云端无人值守自动刷新登录态（可选）：`BB_USERNAME/BB_PASSWORD`

3) 先 dry-run 预览（不发到手机）：
- `python -m app.main --run --dry-run --dry-run-out data/bark_preview.json --course-limit 1 --limit 10`

4) 正式运行（会推送）：
- `python -m app.main --run --limit 100`

首次运行行为（避免刷屏）：
- 如果 DB 里还没有任何已通知记录，`--run` 会只发 1 条“初始化完成”的 Bark，然后把当前抓到的所有条目标记为已通知；后续才开始推送新增/变更。

## 配置（.env）

必填（至少）：
- `BB_BASE_URL`：例如 `https://course.pku.edu.cn`
- `BB_LOGIN_URL`：登录入口（未登录会跳统一认证）
- `BB_COURSES_URL`：登录后可访问的 portal 页（用于校验与抓课程列表）

推送：
- `BARK_ENDPOINT` 支持：
  - 完整 URL：`https://api.day.app/<token>`
  - 只填 token：`<token>`（程序会自动补全）
- 当前推送不会附带可点击超链接（不设置 Bark 的 `url` 参数）
- **Bark 目前只支持 iOS/iPadOS 设备，如果有同学想支持邮件通知欢迎随时联系我并提 PR！**

云端无人值守自动刷新登录态（可选）：
- `BB_USERNAME` / `BB_PASSWORD`
- `--run` 启动时会校验登录态；若 `storage_state.json` 失效，会自动提交账号密码并重写 `BB_STATE_PATH`

## 环境与依赖

- Python 3.10+（推荐使用你的 conda 环境，例如 `bbwatcher`）
- Playwright（Chromium）

如果你使用 conda 环境运行，建议先：
- `conda activate bbwatcher`

## 生成登录态（第一次需要）

- 如果你在云端配置了 `BB_USERNAME/BB_PASSWORD`，通常不需要手动导出登录态；程序会在登录态失效时自动刷新。
- `python scripts/export_state.py`
- 在弹出的 Chromium 窗口完成登录，然后回到终端按 Enter 保存
- 输出文件：`data/storage_state.json`

## 运行与验证

常用：
- 预览（不推送）：`python -m app.main --run --dry-run --dry-run-out data/bark_preview.json`
- 正式运行（推送）：`python -m app.main --run --limit 100`

调试：
- 导出本轮抓取到的统一 items（便于检查字段）：`python -m app.main --fetch-all --items-json data/items.json`
- 校验登录态：`python -m app.main --check-login`

## 产物位置

- 日志：`logs/run.log`
- 登录态：`data/storage_state.json`
- SQLite：`data/state.db`（去重/通知状态）
- dry-run 预览：`data/bark_preview.json`（你用 `--dry-run-out` 指定的文件）

## 定时运行（cron）

- `bash check.sh`
  - 当前 `check.sh` 会跑完整闭环：`--run --limit 100`（避免初期限流影响；后续再优化折叠/批量）
  - 默认优先用 `conda run -n bbwatcher`（可用 `CONDA_ENV_NAME` 覆盖环境名）
  - 使用文件锁 `data/cron.lock` 避免并发重叠

示例 crontab（每 20 分钟跑一次）：
- `*/20 * * * * /bin/bash /ABS/PATH/PKU-BlackBoard-Watcher/check.sh`
