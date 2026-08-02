# BMC 智能日志平台 — AI Handoff

## 当前状态

- 版本：`0.9.0-local`
- 更新日期：2026-07-30
- 当前阶段：本地调试完成，**尚未部署到服务器**。
- GitHub 代码仓库（公开）：`https://github.com/Xiaowei1025/bmc-log-analysis-server`。公开仓库只推送可复现源码、测试、部署配置、Handoff 和文档生成素材；绝不推送 `.env`、`data/`、`uploads/`、公司日志样例、真实 API Key 或本地交付包。公开后新增漏洞请按 `SECURITY.md` 报告，不要在 Issue 或 PR 中粘贴日志、Token 或客户信息。
- 目标服务器：openEuler 24.03 `x86_64`、Python 3.11。
- 运行架构：FastAPI + SQLite + Nginx/systemd（生产）或 Uvicorn（本地）。
- 公开仓库保护：GitHub Secret Scanning、Push Protection 和 Dependabot 安全更新已开启；`.github/workflows/ci.yml` 会在 Python 3.11 上执行编译、单元测试和差异检查。仓库尚未选择软件许可证，外部复用前必须由负责人补充 LICENSE。
- 公开安全告警修复已提交到后续 PR：`Jinja2==3.1.6`、`python-multipart==0.0.31`。合并该 PR 后重新查看 Dependabot 告警，确认 8 个旧告警全部关闭；不要在生产服务器只升级虚拟环境而忘记同步锁定版本文件。

### 2026-07-30 0.9.0：自然交互与报告处置闭环

- 全局表单交互已统一：所有 `POST` 表单会在提交后锁定并显示处理中状态，防止重复提交；危险操作改用站内玻璃确认框，不再依赖浏览器原生弹窗。成功提示会自动收起，错误提示保留并允许手动关闭。
- 特征、案例、需求和工具发布等长表单支持浏览器本地自动草稿、恢复提示与手动清除。草稿只保存在当前 Windows 浏览器的 `localStorage`，不会写入服务器；CSRF、密码、文件和禁用字段不会进入草稿。成功提交后才清除草稿，页面校验失败时继续保留。
- 日志上传页增加拖放、文件清单、单文件移除、全部清除、数量和总体积统计，以及扩展名、空文件和单文件大小预检。文件仍只在用户明确点击“开始上传并分析”后提交；前端预检不能替代后端安全校验。当前进度是等待型状态，不代表可恢复上传或后台任务队列。
- 报告列表增加名称/上传人搜索、状态、命中情况筛选和分页。报告详情可将当前报告作为受控上下文继续“询问 AI”“沉淀特征”或“发布案例”；后端会再次校验报告归属，仅上传者、审核者和管理员可使用该上下文。创建关系只追加 `feature_log_links` / `case_log_links`，不会复制、覆盖或删除原始报告。
- 空案例库、空需求板和筛选无结果时提供明确下一步操作。中窄屏主导航改为可关闭抽屉并保留键盘 Escape、焦点恢复和遮罩；WeLink 指标卡在 Windows 窄窗口自动两列/单列，不产生横向滚动。
- 本次没有数据库 schema 迁移，也没有修改、上传或删除真实业务日志、案例、报告、对话和 WeLink 配置。回滚时可恢复 `app/main.py`、本次模板与 `app/static/app_interactions.js`、`upload_runtime.js`、`workflow.css`；无需回滚 SQLite。
- 验证结果：`.venv312/bin/python -m compileall -q app tests`、`.venv312/bin/python -m unittest discover -v`（共 **44 项通过**）和 `git diff --check` 均通过。浏览器已在 `1011 × 837` 与 `773 × 837` 检查报告筛选、报告上下文、日志文件清单、草稿恢复/清除、空状态、站内确认框和窄屏导航；上传验收只选择本地脱敏示例，没有点击提交。
- 后续 Agent 若要进一步提升大文件体验，应先引入受控后台任务、任务状态表和可审计取消协议，再实现真实百分比与断点续传；不能用前端动画伪造上传或分析进度。部署前继续按 `deploy/OPEN_EULER_24_03_X86_64.md` 在目标 x86 服务器运行预检。

### 2026-07-30 0.8.5：工具详情页液态玻璃重构

- `app/templates/tool_detail.html` 已从两个普通白色表单卡片重构为工具身份区、版本概览、工具说明、版本时间线、版本发布和协作反馈六个清晰层级。最新版本、历史版本数和累计下载只读取现有 `versions` 数据；下载、上传、编辑和反馈仍使用原有路由与权限条件，没有数据库迁移，也没有覆盖版本、下载计数或反馈历史。
- 新增 `app/static/tool-detail.css`，把玻璃效果限制在工具详情页：内容卡使用较克制的透明材质和边界，下载、上传等功能控件使用更强的蓝紫浮层、复合外阴影、内高光以及悬停/按压反馈。深色模式单独调整边界和阴影，避免卡片与背景融为一体；资源查询串为 `/static/tool-detail.css?v=0.8.5`。
- 响应式验收覆盖批注对应的 Windows 浏览器宽度：`1011 × 837` 保持主内容与管理侧栏双列；`773 × 837` 改为主区单列，发布和反馈卡在其下双列排列。两档视口的 `documentElement.scrollWidth` 都等于视口宽度，没有横向溢出；下载按钮实测保留 `13px / 28px` 主阴影。
- 新增 `tests/test_tool_detail_ui.py`，固定工具概览、原有操作路由、无嵌套 `main`、下载按钮复合阴影、深色和响应式规则。`.venv312/bin/python -m unittest discover -v` 共 **41 项通过**，`compileall` 与 `git diff --check` 通过。浏览器验收只读取页面，没有下载、上传或提交反馈，因此业务数据未变化。

### 2026-07-30 0.8.4：历史对话重命名

- 维护知识问答与 WeLink 重大问题持续追问共用 `_conversation_controls.html`。当前对话下拉框旁新增“重命名”，点击后打开一致的玻璃弹窗，可修改、保存或取消；输入框会自动聚焦并全选当前名称，最多 60 个字符。
- 新增 `rename_conversation()` 统一后端逻辑，以及 `/ask/conversations/{id}/rename`、`/welink/chat/conversations/{id}/rename` 两个只接受 `POST` 的接口。名称会去除首尾空白并合并连续空白；人工名称保存后，后续提问不会再被首条问题自动覆盖。
- 权限条件同时包含对话 ID、登录用户、问答范围和 WeLink 当前运行模式。其他账号、错误范围或演示/生产模式不匹配时统一返回 404，不泄露对话是否存在。重命名不会删除或改写任何历史消息。
- `app_interactions.js` 统一处理历史对话切换、弹窗打开、输入全选、取消、点击遮罩关闭和关闭后焦点恢复；`interaction.css` 提供深浅色及 Windows 窄窗口样式。缓存版本更新为 `interaction.css?v=0.8.4`、`app_interactions.js?v=0.8.4`。
- 验证结果：`.venv312/bin/python -m unittest discover -v` 共 **39 项通过**，`compileall` 与 `git diff --check` 通过。浏览器在知识问答页确认当前名称会自动填入并全选、表单使用受 CSRF 保护的 `POST`、取消后名称不变且焦点返回“重命名”；WeLink 生产上下文同样显示共享控件和弹窗。`760 × 837` 窄窗口下弹窗完整可见。浏览器验收未提交名称，没有改动现有对话和消息。

### 2026-07-30 0.8.3：Markdown 专业使用指南

- 案例发布页的“语法说明”已由简单语法列表升级为专业指南。内容以 CommonMark 0.31.2 的核心语法为基础，并使用 GitHub Flavored Markdown 的表格规则；页面保留规范链接供维护人员核对。
- 指南包含 8 类服务器维护场景示例：标题与段落、强调与行内代码、列表、引用、链接与分隔线、代码块、表格，以及一份可直接套用的完整服务器维护案例模板。每项都并排展示“Markdown 写法”和“本工具实际效果”，效果区直接调用 `BmcMarkdown` 当前安全渲染器生成，避免文档示例与真实能力不一致。
- 页面明确说明当前兼容边界：原生 HTML、图片语法、任务列表、删除线和复杂嵌套列表不作为正式支持能力。日志示例同时提示发布前删除序列号、IP、账号、Token 和客户信息。
- 桌面端对话框宽度上限为 `1040px`，正文独立滚动，目录可跳转到相应语法；小于等于 `760px` 时“写法/效果”自动改为上下布局，适配 Windows 窄窗口。样式版本使用 `/static/case-editor.css?v=0.8.3` 避免浏览器继续使用旧缓存。
- 验证结果：`.venv312/bin/python -m unittest discover -v` 共 **37 项通过**，`compileall` 与 `git diff --check` 通过。浏览器实测 8 份示例全部成功渲染，包含 2 个表格、粗体、代码块、标题、列表和引用；`1280 × 720` 下左右对照且对话框内部滚动，`760 × 837` 下上下堆叠、等宽且无横向溢出，目录跳转和关闭按钮正常。验收过程未发布案例、未写入业务数据。

### 2026-07-30 0.8.2：案例 Markdown 左右实时预览

- 案例发布页切换到 Markdown 模式后，正文编辑器与发布前预览改为左右双栏；右侧预览固定在当前阅读区域，长内容独立滚动。小于等于 `860px` 时自动改成上下布局，避免 Windows 窄窗口出现横向滚动。
- Markdown 模式不再依赖“实时预览”按钮。输入、工具栏格式操作和 `⌘/Ctrl+B` 都会立即调用本地安全渲染器，因此标题、粗体、斜体、列表、引用、代码块和表格可以边写边看。
- 富文本模式保留原有按需预览按钮；两种模式最终仍统一保存为 Markdown，没有改变案例数据结构、发布接口或历史数据。
- 新增 `app/static/case-live-preview.css`，并新增模板/响应式回归测试。后续修改案例编辑器时必须继续验证左右栏宽度、实时刷新、粗体渲染、移动端单列和表单提交内容。
- 验证结果：`.venv312/bin/python -m unittest discover -v` 共 **36 项通过**，`git diff --check` 通过。浏览器在 `1280 × 837` 下确认输入区与预览区左右等宽且无横向溢出；直接输入测试 Markdown 后，无需点击按钮即可生成 `h1`、`strong`、`li` 和 `blockquote`。在 `760 × 837` 下两栏会自动上下堆叠、宽度一致且无横向溢出。验收过程未发布案例、未写入业务数据。

### 2026-07-30 0.8.1：WeLink 对齐与长列表滚动

- “重大问题持续追问”保留通用聊天交互，但移除通用聊天页的 `960px` 最大宽度，改为与 WeLink 上方报告、配置和审计区域左右边界一致。
- 消息源管理与接收方管理继续保持相同布局；两类配置列表均限制为 `min(620px, 65vh)` 的可视高度，超过后在列表内部滚动，不再持续拉长整个页面。
- 列表标题显示当前条目数和“列表内滚动”提示；滚动容器支持鼠标滚轮、Windows 滚动条和键盘聚焦滚动，窄屏时高度进一步限制为 `min(520px, 62vh)`。
- 回归测试 `test_welink_chat_aligns_full_width_and_config_lists_scroll` 固定上述结构和无障碍标识；`.venv312/bin/python -m unittest discover -v` 已通过 35 项，`compileall` 与 `git diff --check` 通过。
- 浏览器实测：在批注对应的 `1011 × 837` 视口中，报告区和问答区的左右边界均为 `16px / 995px`、宽度均为 `979px`；消息源列表内容高度 `574px`、可视高度约 `544px`，鼠标滚轮会在列表内部滚动。在 `760 × 837` 窄屏中配置区改为单列，页面宽度等于视口宽度，没有横向溢出；控制台没有错误或警告。

### 2026-07-29 0.8.0：Codex 风格交互统一

- WeLink 的演示/生产隔离扩展到问题、报告和问答上下文。`welink_reports.run_mode` 会随数据库初始化自动补建并根据旧报告标题回填；页面只查询当前模式报告。生产模式不再显示旧演示报告或通用演示成功提示。
- `welink_runs` 新增 `run_mode`、`progress`、`current_stage`。生产巡检必须同时满足“至少一个当前账号启用的消息源”和“桥接 URL + Token 已配置”，否则前端禁用启动且后端再次拒绝，不创建误导性的空任务。
- 同一账号已有 `queued` / `awaiting_bridge` 生产任务时，前后端都会阻止重复提交。当前公司桥接协议只定义任务创建，没有提供外部任务 ID、进度查询或取消端点；因此网页不会伪造“停止巡检”。内网接入时必须先扩展桥接合约，再实现真实轮询和跨服务取消。
- 消息源、接收方和巡检记录都按当前登录账号查询；开始巡检也只提交当前账号的启用配置。消息源与接收方均可修改类型、名称和群标识/工号，可独立启停并在删除前确认。
- 新增 `chat_conversations`，`chat_messages` 与 `welink_chat_messages` 增加 `conversation_id`。旧历史会原地迁移进“历史对话”，不会删除；WeLink 对话再按 `demo` / `production` 上下文分开。用户可以新建和切换对话。
- `app/static/chat_runtime.js` 统一两个问答入口：单一发送/停止按钮、正在停止状态、自动增高、会话级草稿、进入页面定位最新、智能跟随、回到最新、复制、重新生成、编辑后重问、错误重试提示和带 CSRF 的 POST 提交。不要再把问题放进 URL 查询参数。
- `app/static/stream_runtime.js` 统一报告分析和特征复核：原按钮在流式过程中变为“停止”，支持 `AbortController` 与流读取取消，完成、失败或停止后恢复原文案。`stream_script.html` 只负责挂载此共享组件。
- `app/static/app_interactions.js` 统一危险操作确认、表单提交中状态、具体成功/错误提示自动消失和 URL 通知参数清理。中等宽度导航改为可展开菜单，并补充全局键盘焦点、`aria-live`、`aria-busy` 和减少动画支持。
- 当前自动化验证：`.venv312/bin/python -m unittest discover -v` 通过 34 项；三个新增浏览器脚本已使用工作区 Node 运行 `--check`，Python 模块已通过 `compileall`。浏览器已验证生产未就绪阻断、模式报告隔离、问答发送/停止/恢复、报告分析停止/恢复、聊天打开定位最新消息，以及折叠导航中的账号与退出入口。

### 2026-07-27 第一阶段：合并 WeLink 重大问题巡检

- BMC 主工程现已成为“硬件运维智能工作台”的统一底座。登录后的看板可进入 `/welink`，用于配置问题通报群、问题讨论群、个人消息和报告接收方；配置、启停、删除和手工发起巡检均按当前账号保存并受到既有会话与 CSRF 保护。
- SQLite 新增 `welink_sources`、`welink_recipients`、`welink_runs` 三张表。它们只保存巡检配置和任务元数据；**不保存消息正文、WeLink 登录态、CLI 凭证或模型 Key**。消息源和接收方只能由创建者或管理员修改。
- “一键开始巡检”目前只写入审计任务。只有同时配置 `WELINK_AGENT_BRIDGE_URL` 与 `WELINK_AGENT_BRIDGE_TOKEN` 后，任务才会标为“已入队”；本阶段仍未实现桥接协议，也绝不会由网页或 FastAPI 直接执行 `welink-cli`。
- 后续内网 Agent 的下一步：先根据真实 `welink-cli` 输出和公司桥接 API 约定实现受控桥接服务，再将桥接返回的标准化消息归并为问题、证据、根因、下一步计划和参与人员；最后把问题与 `analyses`、`knowledge_cases` 建立可追溯关联。不要根据网页表单拼接 shell 命令。
- 验证：临时 SQLite 初始化已确认创建 3 张 `welink_*` 表；`.venv312/bin/python -m unittest discover -v` 共 20 项通过。真实 WeLink 读取、发送、定时 08:00 任务、流式问题追问和通报表格仍属于下一阶段。

### 2026-07-27 第二阶段：部署模式与模型档案

- WeLink 增加全局运行模式：`demo` 默认只生成本地模拟巡检结果，绝不连接 WeLink；`production` 仅由管理员切换，并只向固定的 `WELINK_AGENT_BRIDGE_URL/v1/welink/runs` 发送受令牌保护的 JSON 任务。网页和 FastAPI 不执行 shell、不保存 CLI 凭证。桥接端必须实现鉴权、命令白名单、审计与真实消息归并。
- 新增 `app_settings`，仅保存 `welink_run_mode` 和 `active_llm_profile` 等非敏感开关。它不保存 API Key、消息正文或 CLI 登录态。
- 管理员页面 `/settings/models` 可以切换 `.env` 中 `LLM_PROFILES_JSON` 声明的模型档案。每个档案的 Key 通过 `api_key_env` 引用服务器环境变量；数据库只记录档案 ID。需要改 Key 时修改受控 `.env` 并重启 systemd 服务。
- 新增 `deploy/OPEN_EULER_24_03_X86_64.md` 与 `scripts/preflight-openeuler-x86_64.sh`，目标为 openEuler 24.03 x86_64 + Python 3.11。真实部署前先在目标主机运行预检、替换 Nginx 内部域名/证书、创建管理员、完成演示验收，再进行受权测试群的生产桥接验收。

### 0.6.0-local 本次更新：访问保护基线

- 数据库会自动为既有 `users` 增加 `role`；旧账号默认是 `contributor`，不会删除或改写任何日志、案例、特征或工具数据。
- 生产默认关闭 `/register`。首位管理员和后续角色调整使用 `scripts/manage_users.py`；如历史账号需要立即成为管理员，可先在受控 `.env` 设置一次 `ADMIN_USERNAMES=历史用户名` 后启动，随后移除该设置，或直接使用 `set-role`。
- 访问控制目前是平台级角色模型，不是项目/客户级隔离。后续接入项目组 ACL 前，不应把不同客户或保密等级的日志混放在同一实例。
- CSRF 中间件只检查前 64 KiB 内最先出现的表单 Token，并把已读取的 ASGI 数据原样回放给 FastAPI；因此不会把最大 200 MB 的日志上传整体读进内存。不要把 Token 字段从表单开头移走。

### 2026-07-24 当前交接状态：给后续 AI Agent 的执行清单

当前代码已完成本地 MVP 验收；**没有部署到 openEuler 服务器，也没有接入公司内部真实 BMC 规则或真实生产日志**。后续 Agent 应先通读本文件、`docs/BMC_SKILL_INTERFACE.md` 和 `README.md`，然后严格按下面顺序推进，不要跳步：

1. **先保护数据。** 不把 `.env`、`data/`、`uploads/`、`examples/`、公司规则、原始 BMC 日志或 API Key 提交到 Git、压缩包、截图或外部模型。Git 忽略策略已写在仓库根目录 `.gitignore`。
2. **接入公司 BMC Skill。** 收到经过授权的内部规则后，先为每条规则准备至少一份命中与一份不命中的脱敏样本；复杂逻辑实现为受控服务器模块，并通过 `BMC_SKILL_ADAPTER` 接入，接口和返回格式见 `docs/BMC_SKILL_INTERFACE.md`。Skill 失败时必须保持特征库分析和日志留存可用。
3. **建立首批知识。** 用已确认的故障日志录入高频特征（建议先覆盖风扇、PSU、内存、磁盘、SEL、BMC 健康告警），并为每类问题发布至少一个“背景 - 证据 - 根因 - 处理 - 验证”案例。不要只上传截图，必须关联来源日志/报告。
4. **做真实验收。** 选取正常、已知故障和容易误报三类脱敏日志，逐项验证：批量上传、证据定位、规则版本重新检查、HTML 报告导出、案例关联、流式问答、角色限制和下载权限。发现误报时先收紧文件路径/组合条件，再保存新规则版本。
5. **再部署到 openEuler。** 按“部署前检查与 openEuler AArch64”章节准备 Python 3.10+、Nginx、systemd、HTTPS、生产 `.env` 和首位管理员；部署前后都备份 `data/` 与 `uploads/`，不要把 Uvicorn 直接暴露到公网。
6. **建立运维闭环。** 上线后至少按月做恢复演练（恢复数据库、下载原日志、导出 HTML 报告），定期检查需求板，按团队流程把有效需求实现为小版本并更新本 Handoff。

本地已经提供一份面向新同事的图文手册：`docs/build_user_guide.py`（可编辑 Word 版生成器）、`docs/build_user_guide_pdf.py`（中文字体稳定的 PDF 版生成器）和 `docs/assets/user-guide/`（配图）。最终文件仅作为本地交付物放在 `deliverables/`，默认不上传 Git；若团队希望在仓库中直接下载，应由负责人确认后单独提交该 PDF/DOCX。

截至本次交接，Python 单元测试共 **20 项通过**；真实生产验收和服务器部署仍未开始。每次实质修改后，后续 Agent 必须更新本节的日期、已完成工作、验证命令/结果、风险和下一步，避免只写“已完成”。

## 已实现的产品能力

| 模块 | 行为 |
| --- | --- |
| 批量日志 | 一次可上传多个 `.tar.gz`、`.tgz`、`.tar`、`.zip`、`.gz` 或文本日志；提交前显示文件清单、数量、总体积和本地格式/大小预检，每个文件独立保存为一份报告。 |
| 自动分析 | 每份上传日志都会自动执行当前特征库比对；如配置受控的公司 BMC Skill，还会并行运行复杂、结构化的内部解析。两类结果独立保存并汇总到同一报告。 |
| 安全解析 | 压缩包不落地解压、不执行文件；限制文件与总读取大小；忽略 macOS 元数据文件。 |
| 特征库 | 特征含名称、严重程度、关键字、标签、描述、诊断、建议和多条日志条件；支持创建、编辑、删除。每次保存生成不可覆盖的规则版本。 |
| 关联 | 自动命中特征会关联报告；可在报告详情手动关联更多特征。关系存储在 `feature_log_links`，支持多对多。自动匹配记录带规则版本，旧证据保留、当前报告仅显示当前版本命中。 |
| 案例库 | 每位登录用户可发布富文本或 Markdown 案例，也可同时上传多份日志；默认富文本带标题、加粗、列表、引用和代码工具栏，Markdown 模式提供语法说明与实时预览，提示模板使用真实换行显示。还可一键导入 DOCX、PPTX、Markdown 或文本资料为待发布草稿；草稿在导入页可恢复编辑或取消，校对后才会创建正式案例。旧版 DOC/PPT 在服务器安装 LibreOffice 后本地转换。原始导入资料长期保留并可下载。两种输入均安全转换为 Markdown 存入 `knowledge_cases.body`，因此现有渲染、检索、问答和历史案例完全兼容。日志会各自形成报告并与案例关联；案例通过标题/关键字与日志自动命中关联特征，也可从特征表单手动关联。 |
| 特征来源复核 | 新建/编辑特征时可上传多份来源日志。复核页会从实际来源日志按每条当前规则重新提取受限片段（文件、行号、原文），再由模型提出追问；维护人员最终确认或驳回。 |
| 看板 | 展示累计上传、完成分析、特征、高风险特征、最新报告与规则，并按用户发布的特征数 + 案例数生成知识贡献榜。 |
| 需求板 | 登录用户可提交功能、流程、界面、知识或其他需求。需求状态为待评审、已采纳、规划中、已实现、暂不处理；每次评审状态变更都会留下时间线。 |
| LLM | 报告、问答与特征来源复核均走流式 HTTP 输出；模型提示词要求 Markdown，浏览器用本地安全渲染器边接收边渲染；问答同时检索特征和案例，无 Key 时使用内部知识生成可读的降级建议。 |
| HTML 报告与留存 | 报告详情可下载原始归档（`/reports/{id}/download`）及导出独立 HTML 问题分析报告（`/reports/{id}/export.html`）；报告含 Skill/特征结论、原文证据与处置建议。 |
| 报告处置闭环 | 报告列表支持关键字、状态和命中情况筛选及分页；有权限的维护人员可从报告详情携带受控上下文继续问答、沉淀特征或发布案例，并追加原始报告关系。 |
| 问答历史 | 当前账号的用户问题和助手回答保存在 `chat_messages`，以对话气泡形式在问答页显示；历史助手回答会重新渲染 Markdown。 |
| 工具中心 | 保留工具发布、版本、下载计数和反馈；详情页使用分层液态玻璃布局和高对比下载按钮，支持深浅色与 Windows 窄窗口自动重排。 |
| 编辑快捷键 | 案例正文的富文本和 Markdown 均使用同一格式工具栏。Markdown 工具栏会插入或移除语法；选中文字按 Command+B 或 Ctrl+B 可切换加粗。富文本工具栏会缓存并恢复选区后再格式化，避免点击按钮后选区丢失。 |
| UI | iOS 液态玻璃风格、深浅色切换、全局帮助对话框；主导航会以更明显的玻璃胶囊与扩大阴影标识当前页面，窄屏使用抽屉导航；全局表单提供防重复提交、站内确认和长表单本地草稿；空列表提供明确下一步；深色模式统一提升低对比文本可读性；帮助署名“作者：江小伟 00983211”。 |
| 访问保护 | 所有业务页面均要求登录；匿名访问首页 `/` 会重定向到 `/login`，避免浏览器直接显示原始 `401`。`users.role` 支持 `contributor`、`reviewer`、`admin`。原始日志只允许上传者、审核者和管理员下载；原始案例资料只允许导入人、案例作者、审核者和管理员下载。特征来源复核只允许特征创建者、审核者和管理员完成。 |
| 会话安全 | 所有写操作经过 CSRF Token 校验；登录/注册成功会轮换会话和 CSRF Token。生产环境必须设置随机 `APP_SECRET` 与 `SESSION_HTTPS_ONLY=true`，否则应用拒绝启动。网页自助注册默认关闭。 |
| 数据一致性 | 编辑规则后自动重新检查所有已完成报告；特征详情也可手动触发重新检查。删除特征会级联清理当前和历史自动匹配、关联和版本记录，但不会删除原始报告。 |

## 本地验收记录

实际验证通过：

1. 文本日志和 tar.gz 同时上传，生成两份独立报告。
2. tar.gz / 文本日志都命中“风扇 3 转速异常”特征。
3. 新建“电源模块告警”特征，并在报告中手动关联它。
4. 报告 LLM 与智能问答的流式接口在无 Key 模式下输出本地特征建议。
5. 深色模式切换和页面帮助对话框可用。
6. 实际 R220KV2 BMC dump 的外层 tar.gz 与内部轮转 `.gz` 日志可展开并搜索。
7. DeepSeek OpenAI 兼容接口的真实流式调用已验证成功（使用 `deepseek-v4-flash`）；密钥仅保留在本机 `.env`。
8. `tests/test_feature_integrity.py` 已覆盖：有自动命中时删除特征、规则版本更新后的历史报告重新计算、从实际来源日志按条件提取证据。
9. `tests/test_bmc_skill_adapter.py` 已覆盖：公司 BMC Skill 的标准化、持久化、配置错误降级及 HTML 报告模板渲染。
10. `tests/test_case_editor_template.py` 已覆盖：案例发布页同时提供富文本、Markdown、预览和 Markdown 语法说明入口，并保留富文本转 Markdown 的提交路径。
11. `tests/test_case_importer.py` 已覆盖：DOCX 的标题/段落/表格/列表提取、PPTX 的逐页文字提取、待发布导入草稿的账号隔离，以及导入草稿发布后与案例/原始资料的持久关联。

12. tests/test_case_editor_template.py 已覆盖：Markdown 的 Command/Ctrl+B 加粗路径、Markdown/富文本共用格式工具栏，以及富文本选区缓存与恢复入口。
13. `tests/test_access_control.py` 已覆盖：匿名看板拒绝、原始日志和案例原文件的角色限制、特征来源复核限制、CSRF 拒绝与 ASGI 请求体回放、生产会话密钥校验。

## 关键文件与职责

| 文件 | 作用 |
| --- | --- |
| `app/main.py` | 路由、批量分析调度、报告、特征 CRUD/关联、流式 LLM、看板、账号和工具中心。 |
| `app/log_parser.py` | 读取压缩日志、过滤元数据、在文件路径中按文本或正则查找证据。 |
| `app/bmc_skill_adapter.py` | 加载受控公司内网 BMC Skill，校验/限制返回结果，并使其与特征库并行而不互相阻断。 |
| `app/case_importer.py` | 本地安全提取 DOCX、PPTX、Markdown、TXT；限制 Open XML 归档成员、解压大小和提取字数。旧版 DOC/PPT 仅通过受控的 LibreOffice 本地转换，不调用外部服务。 |
| `docs/BMC_SKILL_INTERFACE.md` | 公司 Skill 的环境配置、函数签名、返回格式、安全边界和后续 AI Agent 接手步骤。 |
| `app/database.py` | SQLite schema、增量列迁移、旧自动命中记录回填。 |
| `app/templates/` | 深浅色液态玻璃 UI；`knowledge_case_*.html` 为案例库（发布页可切换富文本/Markdown），`feature_assist.html` 为来源日志 AI 复核；`stream_script.html` 消费报告/复核流，`ask.html` 消费问答流。 |
| `app/static/case-editor.css` | 发布案例的编辑器切换、富文本工具栏、Markdown 预览与语法说明对话框；包含深浅色模式的对比度样式。 |
| `app/static/case-import.css` | 案例导入入口、待发布草稿提示、来源资料和深浅色样式。 |
| `app/templates/tool_detail.html` / `app/static/tool-detail.css` | 工具详情、版本历史、下载、发布和反馈的分层液态玻璃界面；不得绕过原有权限、计数和历史留存路由。 |
| `app/static/llm_markdown.js` | 无外部 CDN 的安全 Markdown 渲染器；先转义模型内容，再渲染标题、列表、强调、引用、代码和 HTTPS 链接。 |
| `app/static/app_interactions.js` | 全局表单锁定、站内确认框、长表单本地草稿、通知和窄屏抽屉导航；不得把密码、文件或 CSRF 写入草稿。 |
| `app/static/upload_runtime.js` / `app/static/workflow.css` | 日志上传文件清单与前端预检，以及报告筛选、上下文卡、空状态、草稿提示和响应式样式。 |
| `tests/test_workflow_interactions.py` | 报告筛选、从报告创建特征/案例关系，以及上传、草稿、抽屉和空状态的回归测试。 |
| `requirement_requests` / `requirement_review_events` | 需求原文、当前状态和不可覆盖的评审历史。 |
| `feature_versions` / `analysis_matches.feature_version` | 特征版本快照与规则命中版本；只把与当前 `cases.rule_version` 相同的命中作为当前结果，旧记录用于追溯。 |
| `.env` | 仅部署环境保存 APP_SECRET、环境、HTTPS Cookie、注册开关、上传上限和 LLM 配置。 |
| `scripts/manage_users.py` | 受控创建账号、查看账号和调整角色；密码只经终端交互输入。 |
| `deploy/` | openEuler systemd 与 Nginx 基线。 |

## 后续 AI 接入公司内部规则：必读

公司内部日志或规则不应离开受控环境。后续 AI Agent 收到规则后按以下顺序工作：

1. 先取得经过脱敏授权的正常日志、故障日志和预期结论，放入本地受控测试目录；不要提交到 Git 或交付包。
2. 如果规则能描述成“文件路径 + 关键字/正则 + AND/OR”，通过 Web 的“特征库”页面录入即可，无需改代码。
3. 如果规则需要错误码解析、时间关联、数值阈值、多文件上下文或厂商私有格式，在 `app/log_parser.py` 增加纯函数解析器，再由 `scan_features()`（在 `app/main.py`）调用。解析器应返回与 `find_evidence()` 相同的证据结构：`file`、`line`、`excerpt`。
4. 为每一条公司规则增加至少一个命中与一个不命中的脱敏样本，验证后才录入生产特征库。
5. 更新本文件：规则来源、支持机型、测试样本位置、变更日期、已知误报条件和回滚方式。

### 公司内网 BMC Skill 接口（0.5.0 起）

- Skill 接口说明在 `docs/BMC_SKILL_INTERFACE.md`，可复制 `app/skills/company_bmc_example.py` 为受控模块后实现。模块的唯一入口为 `analyze_log_bundle(*, files, archive_path)`。
- 部署环境设置 `BMC_SKILL_ADAPTER=模块路径:函数名` 后，每次上传会在基础归档读取和特征库比对后自动运行该 Skill。它返回的结论写入 `analysis_skill_findings`，并带 `skill_name`、`skill_version`、`rule_id`、严重程度、建议及文件/行号证据。
- Skill 未配置、配置错误或执行异常时，上传不会失败；平台仍保存原始日志并完成特征库比对，报告中会显示提示。不要把公司 Skill 说明、样本或规则直接写进本仓库或交付包。
- 后续 AI Agent 得到公司内网 Skill 后，应先为每条规则建立命中/不命中脱敏测试，再实现模块并更新本 handoff。

### 规则版本与重新检查（0.4.0 起）

- `cases.rule_version` 是当前规则版本；`feature_versions` 保存每一次保存后的规则快照（含条件）。不要直接改 SQLite 中的规则条件，应通过特征编辑页产生新版本。
- 编辑特征后会读取所有状态为 `completed` 的历史报告，并在 `analysis_matches` 写入新的 `feature_version` 结果。旧版本命中不会被删除；报告、看板和问答相关当前计数只以 `analysis_matches.feature_version = cases.rule_version` 计算。
- 特征详情的“重新检查历史日志”适用于修复上传附件、补充后再跑，或需要重新确认当前版本结果的场景。当前实现同步执行，日志数量很大时后续应迁移为后台任务队列。
- 旧数据库启动时会自动重建 `analysis_matches` 的外键，补齐 `feature_version` 并给既有特征创建当前版本快照。升级前仍应按部署章节备份 `data/` 与 `uploads/`。
- 删除特征会级联删除其所有版本和自动匹配记录；`analyses` 与原始上传附件不删除。

## 已检查的 R220KV2 日志格式

- 样本：`examples/R220KV2_71012327A001_20251227-0204.tar.gz`，约 6.2 MB、451 个归档成员。
- 根路径：`dump_info/`。重点可建立规则的目录包括：
  - `dump_info/LogDump/`：`bmc_health.log`、`cooling_control.log`、`linux_kernel_log`、`framework.log`、`app.log`、`security.log`、`maintenance.log`。
  - `dump_info/RTOSDump/`：`sysinfo/dmesg_info`、`sysinfo/journalctl.log`、驱动和网络信息。
  - `dump_info/AppDump/`：`bmc_health`、`hwdiscovery`、`firmware_mgmt`、`frudata` 等组件运行记录。
  - `dump_info/SpLogDump/version.json`：BMC / OS 版本信息。
  - `dump_info/LogDump/storage/`：磁盘 SMART、SATA、PCIe PHY 错误计数等存储相关数据。
- 外层 tar.gz 内存在 `framework.log.*.gz`、`app.log.*.gz`、`ps_black_box.log.*.gz` 等轮转日志。`app/log_parser.py` 现在会继续解压这些内嵌 gzip 成员，并以去掉 `.gz` 后的完整路径参与规则匹配。
- 建议公司规则首先用精确文件路径，例如 `dump_info/LogDump/bmc_health.log`，避免只用 `*` 扫描全部文件造成误报。

## 补充：S920X20 样例格式

- 样本：`S920X20_2102315RRH10RC100531_20260212-1027.tar.gz` 与 `S920X20_2102315RRH10RC102660_20260303-0830.tar.gz`；各约 3.5 MB、分别有 492 / 494 个归档成员。
- 两份 S920 与 R220KV2 使用相同的 `dump_info/` 总体层级，三类样例共有 271 个核心文件。因此可复用一套基础规则，优先覆盖：
  - `dump_info/LogDump/bmc_health.log`
  - `dump_info/LogDump/cooling_control.log`
  - `dump_info/LogDump/framework.log` 与 `framework.log.*.gz`
  - `dump_info/LogDump/app.log` 与 `app.log.*.gz`
  - `dump_info/LogDump/linux_kernel_log`
  - `dump_info/RTOSDump/sysinfo/journalctl.log`
  - `dump_info/3rdDump/error_log`
  - `dump_info/SpLogDump/version.json`
- R220KV2 样本版本为 1.9.0.23；S920X20 样本版本为 1.11.0.26。录入特征时建议将版本范围写入标签或关键字，避免跨版本误报。
- S920X20 新增或更丰富的组件级资料包括 `dump_info/AppDump/*/rpc_records.log`、`skynet_info.json` 以及 BIOS、账户、BMC 健康、网络、散热等组件目录。后续复杂规则可将这些目录作为“仅 S920X20 / 1.11+”的补充条件。
- 这些样例是公司内部日志，只能留在本地受控工作区；发布脚本已排除 R220KV2 和 S920X20 样例压缩包。

## LLM 移交与 API Key 配置

后续 AI Agent 获得授权后，仅修改部署环境的 `.env`，不修改源码：

```ini
LLM_API_KEY=实际密钥
LLM_BASE_URL=https://实际兼容服务地址/v1
LLM_MODEL=实际模型名
BMC_SKILL_ADAPTER=app.skills.company_bmc:analyze_log_bundle
```

- 接口必须兼容 `/chat/completions` 且支持 `stream: true`，响应格式为 OpenAI SSE `data:` 分段。
- 报告流地址为 `/reports/{analysis_id}/llm/stream`；问答流地址为 `/ask/stream?question=...`。
- 模型提示词位于 `app/main.py` 的 `llm_stream()`、`analyze_report_with_llm()` 和 `ask_stream()`。
- 严禁在浏览器表单、SQLite、源码、截图、handoff 或压缩包中存储真实 API Key。
- 发送到外部模型前必须按公司要求脱敏日志；若不允许出网，只接入公司内网模型。
- `BMC_SKILL_ADAPTER` 是本地受控解析接口，不是 LLM Key；它只能指向已审核的服务器端 Python 模块，严禁让用户通过网页填写模块路径。

## 案例库与来源日志复核：后续 AI 必读

- Markdown 快捷键与工具栏逻辑位于发布案例页面脚本。Markdown 格式工具栏直接改写 textarea 选区；富文本工具栏会保存 Range、在点击按钮后恢复 Range，再执行浏览器格式命令。不要把两种模式重新拆成仅一方可用的工具栏。
- 案例表为 `knowledge_cases`，正文 `body` 统一是 Markdown；发布页的富文本模式在浏览器提交前仅转换标题、段落、加粗、强调、列表、引用、代码块和 HTTPS 链接等受支持结构为 Markdown，不保存任意 HTML。Markdown 示例提示由 JavaScript 设置真实换行，避免 HTML 属性把 `\n` 显示为一行文本。`case_log_links` 将案例和独立分析报告关联。文章创建时会按案例标题/关键字与现有特征建立关联；案例所附日志的自动命中特征也会同步关联案例。
- 已导入资料存于 `case_imports`，先以 `knowledge_case_id IS NULL` 和 `extracted_body` 作为待发布草稿；仅 `imported_by` 本人可在 `/cases/import` 恢复编辑或取消。正式发布时原子地关联到新案例，并清空仅用于恢复的 `extracted_body`；详情页可下载原文件。取消草稿会删除对应原文件；已发布资料不得通过该接口删除。
- `app/case_importer.py` 不执行导入文件：DOCX/PPTX 只读取固定的 XML 成员，并限制归档成员数、解压总量和可提取文字数。DOC/PPT 仅在 `CASE_IMPORT_SOFFICE` 指向受控 LibreOffice 时，以无 shell 的本地子进程转换；未配置时提示用户另存为 DOCX/PPTX。不要为了“支持更多格式”把文件上传到外部文档转换网站。
- 问答检索函数是 `related_knowledge()`，返回 `(features, knowledge_cases)`。若新增新的知识来源，必须同时更新该函数、`ask_stream()` 的提示词和无 Key 降级输出。
- `feature_case_links` 是特征与案例的多对多关联；不要复用旧的 `cases` 表名来表示维护案例，旧表仍是“问题特征”。
- 来源日志的人工判定状态在 `feature_log_reviews`：`pending`、`confirmed`、`rejected`。`confirmed` 会把 `feature_log_links` 更新为人工确认；`rejected` 仅表示不把该日志视为来源证据，不会删除原始日志或其自动规则匹配记录。
- AI 复核流地址为 `/features/{feature_id}/assist/stream`。模型的建议仅用于引导人工检查，不能自动变更确认状态。
- 复核流的 `local_rule_evidence` 来自请求时对实际来源归档的本地重新读取，仅包含规则指定文件的命中片段、行号、未命中条件和读取失败状态；它不应被视为整包日志外发授权。接外部模型前仍要依公司要求脱敏或改接内网模型。

## 需求板评审配置

- 需求板路由：`/requests`（列表）、`/requests/new`（提交）、`/requests/{id}`（详情与评审）。所有登录用户可提交和查看；只有评审人可改变状态。
- 环境变量 `REQUEST_REVIEWERS` 是逗号分隔的用户名白名单；本地默认值是 `demo-maintainer`，生产部署必须替换为公司指定的评审账号。不要把“所有登录用户可评审”作为默认策略。
- 环境变量 `REQUEST_REVIEW_CADENCE` 仅展示团队评审节奏，默认 `每周`；公司按半月评审时设置为 `每两周`。实际会议/提醒由公司流程或外部日历管理，当前系统不自行发送通知。
- 评审状态更新会同时更新 `requirement_requests.status`，并向 `requirement_review_events` 追加一条记录。不要只更新当前状态而跳过历史记录。

### 当前本地验证模型（可替换）

```ini
LLM_BASE_URL=https://api.deepseek.com
LLM_MODEL=deepseek-v4-flash
```

`deepseek-v4-pro` 也可直接替换 `LLM_MODEL`；无需改动代码。真实 API Key 只允许写入部署环境的 `.env`。

## 部署前检查与 openEuler AArch64

1. 使用交付包，不携带 `data/`、`uploads/`、`.env` 或 `.venv*`。
2. 确认 `python3 --version` 不低于 3.10，`uname -m` 为 `aarch64`。
3. 原生依赖建议：`python3 python3-pip python3-devel gcc nginx firewalld policycoreutils-python-utils`。需要导入旧版 DOC/PPT 时，额外安装 LibreOffice，并通过 `CASE_IMPORT_SOFFICE` 指向 `soffice`。
4. 生产 `.env` 必须设置 `APP_ENV=production`、随机 `APP_SECRET`、`SESSION_HTTPS_ONLY=true` 与 `ALLOW_SELF_REGISTRATION=false`。应用会拒绝默认密钥或非 HTTPS Cookie。
5. 先运行 `.venv/bin/python scripts/manage_users.py create --username bmc-admin --role admin` 创建首位管理员；再按需用 `set-role` 分配审核者。除非临时本地演示，否则不要开启网页自助注册。
6. 使用 `deploy/nginx-bmc-hub.conf` 前，替换其中内部域名、证书和私钥路径；配置必须通过 `nginx -t`，并仅暴露 HTTPS。Uvicorn 保持绑定 `127.0.0.1`。
7. 备份 `data/` 和 `uploads/` 后再升级；代码升级后运行 `pip install -r requirements.txt`、重启 `bmc-hub`、检查 `journalctl -u bmc-hub -n 100`。
8. 升级后运行 `.venv/bin/python -m unittest discover -v`；再用一份脱敏日志验证特征编辑、重新检查和来源日志复核。
9. 长期留存时，把 `data/`（SQLite、报告元数据）与 `uploads/`（原始日志）作为同一备份单元，备份到公司受控存储；至少按月抽检一次“恢复数据库 + 下载原始日志 + 导出 HTML 报告”流程。

## 已知限制

### WeLink 重大问题巡检（本轮恢复与校验）

- 巡检页已恢复原版的核心闭环：消息源与接收方增删改查、全部启用/暂停/仅讨论群、通报群时间窗口与讨论群全量规则、问题卡片、证据、行动项、Markdown 巡检报告、流式连续问答和会话历史。
- 相关 SQLite 表：`welink_sources`、`welink_recipients`、`welink_runs`、`welink_issues`、`welink_issue_evidence`、`welink_issue_actions`、`welink_reports`、`welink_chat_messages`、`app_settings`。`init_db()` 会为既有数据库补建新表。
- 演示模式的三张问题卡明确标记 `is_demo=1`；切换至生产模式时页面和报告会自动排除这些模拟卡片，避免模拟告警混入真实通报。生产桥接尚未返回问题数据时，报告只会说明“未收到台账”，不会编造结论。
- `/welink/chat/stream` 使用服务器端当前激活的模型档案；会话按登录用户保存，回答支持 Markdown 表格。无 Key 或模型不可用时沿用本地台账降级输出。不得把 Key 写入数据库、前端或交接文档。
- `/welink/schedule` 目前仅保存启用状态和时间规则（默认 08:00 Asia/Shanghai），**不含后台调度器**。公司内网接入时需要由受控 systemd timer / 企业调度器调用巡检桥接，并读取这些规则；在此之前不能声称会自动执行。
- 生产读取与发送唯一入口是 `WELINK_AGENT_BRIDGE_URL` + `WELINK_AGENT_BRIDGE_TOKEN` 的固定 `/v1/welink/runs` 合约；网页与 Python 均不得直接调用 WeLink CLI 或 shell。桥接需补充“返回问题、证据、行动项、报告投递结果”的受控写回合约，才能形成真实数据闭环。
- `app/static/llm_markdown.js` 已支持 GitHub 风格 Markdown 表格（表头、分隔行、对齐、转义竖线）；`base.html` 用版本查询串刷新缓存。不要把流式输出直接使用 `innerHTML`，必须继续经此转义渲染器。
- `/ask` 与 `/welink#chat` 已统一为同一套对话样式（`chat-shell`、`chat-head`、`chat-history`、`chat-bubble`、`chat-composer`）：蓝紫用户气泡、玻璃助手气泡、相同的 Markdown/表格样式、Enter 发送与 Shift+Enter 换行。两处均显示“运维助手”；区别只保留在回答上下文（知识库或 WeLink 巡检台账）。
- 问答流支持带思考过程的 OpenAI 兼容模型：`llm_stream(..., include_reasoning=True)` 识别流式 `delta.reasoning_content`（兼容 `delta.reasoning`），并用 `[[BMC_REASONING_START]]` / `[[BMC_REASONING_END]]` 分隔后保存到各自的历史记录。普通报告分析仍默认不输出思考过程。
- `BmcMarkdown.renderAssistantTo()` 负责问答专用渲染：推理尚在流式返回时 `<details>` 默认展开并显示“正在思考…”；最终答案开始后自动折叠为“思考过程（点击展开）”；用户之后仍可手动展开。标记和推理文本都不得直接拼入 `innerHTML`，必须继续经过本地转义后的 Markdown 渲染。
- 两个问答入口同时支持 Enter、Ctrl+Enter 和 macOS ⌘+Enter 发送，Shift+Enter 换行。输入区只保留一个操作按钮：空闲时显示“发送”，流式请求开始后原位切换为红色“停止”，结束或中止后恢复“发送”，不再额外显示第二个停止按钮。点击“停止”后通过 `AbortController.abort()` 和 `ReadableStream.cancel()` 中止浏览器读取，保留已生成内容并显示“已停止生成”。
- 服务端流生成器使用 `try/finally` 保存已经产生的部分回答。若客户端中途断开，会补齐未闭合的思考标记并追加“回答生成已中断”，因此刷新页面后仍可追溯部分结果；在尚未返回任何字符时只保留用户问题，不创建空助手记录。
- 最终拓扑已确认为“Windows Edge/Chrome 客户端 → 公司 HTTPS 域名/Nginx → openEuler 24.03 x86_64 + Python 3.11/FastAPI”。`127.0.0.1:8000` 只用于服务器内部 Nginx 反代，不能发给 Windows 用户作为访问地址；浏览器不安装 Python、WeLink CLI，也不依赖 Google 登录。
- Nginx 的四类 LLM 流接口必须保持 `proxy_buffering off`、`proxy_cache off`、`gzip off` 和 300 秒读写超时，保证 Windows 上流式输出与手动停止及时生效。`browser_compat.js` 会检测 Fetch、ReadableStream、AbortController 和 TextDecoder；缺失时提示升级到公司批准的 Edge/Chrome。
- 本轮本地验证：全量 `.venv312/bin/python -m unittest discover -v` 通过 34 项；浏览器验证了报告生成、Markdown 表格渲染、流式追问、生产模式隐藏演示卡片与演示报告、所有 AI 按钮“开始/发送 → 停止 → 恢复”的状态切换、聊天定位最新消息和折叠导航。最终页面无控制台错误，验收产生的临时对话已从本地数据库清理。

- SQLite 适合当前本地 MVP 和小团队；多人高并发时迁移 PostgreSQL。
- 工具和日志附件尚未集成企业杀毒/白名单扫描。
- 当前仅支持“文本/正则”特征条件；复杂厂商规则需要按“后续规则接入”步骤扩展。
- 已有基础 RBAC 与来源日志审核权限，但尚无项目组/客户级 ACL、企业 SSO、MFA 或账号锁定；不能直接暴露公网。
- 历史报告重新检查当前在 Web 请求内同步执行；日志量或用户量增长后应引入后台队列与进度通知。
- 当前下载权限按上传者/审核者/管理员划分；公司部署前仍应补充项目组/客户级 ACL、数据分类和留存期限。
- DOCX/PPTX 导入当前提取文字而非保真还原页面版式；图片、复杂表格、动画、流程图和演讲者备注需在草稿中人工补充。若需要企业级保真转换，后续可在受控内网增加审核后的转换服务，但仍应保留“导入草稿、人工发布”的流程。
