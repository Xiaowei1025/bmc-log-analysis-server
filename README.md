# BMC 智能日志平台

面向服务器硬件维护团队的内部 Web 平台：批量 BMC 日志分析、可维护的问题特征库、Markdown 案例库、需求板、日志与特征/案例双向关联、流式 LLM 建议、贡献看板，以及内部工具分发。

## 本地体验

需要 Python 3.10+：

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
# 编辑 .env，设置随机 APP_SECRET；本地首次账号由下方脚本创建
uvicorn app.main:app --reload --port 8001
```

打开 `http://127.0.0.1:8001`。默认关闭网页自助注册；首次本地账号请执行：

```bash
.venv/bin/python scripts/manage_users.py create --username maintainer --role admin
```

脚本会在终端中安全地询问密码。只有临时本地演示时，才可在 `.env` 设置 `ALLOW_SELF_REGISTRATION=true` 并重启服务。

如要快速查看完整流程，请在启动前执行：

```bash
.venv/bin/python scripts/seed-demo.py
```

使用 `demo-maintainer` / `demo-password-please-change` 登录，在“批量分析”同时上传 `examples/fan_failure.log` 和 `examples/fan_failure.tar.gz`。它们会生成两份独立报告，并命中演示特征。演示账号和数据仅用于可丢弃的本地环境。

## 主要能力

- 支持 `.tar.gz`、`.tgz`、`.tar`、`.zip`、`.gz` 与单文件文本日志；一次可上传多个文件，每个文件生成独立报告。每次上传都会自动按当前特征库比对，无需等待或手工调用 Agent。
- 特征库包含问题名称、严重程度、关键字、描述、诊断、建议和多条文件路径/关键字/正则规则；支持创建、编辑、删除。每次保存会生成规则版本，旧命中证据保留；编辑后会按新版本重新计算已完成报告。
- 自动命中和手动关联均会保留，因此一份日志能关联多个特征，一个特征也能关联多个日志。
- 案例库支持富文本和 Markdown 两种写作方式（富文本会安全转换为 Markdown 留存），也可把既有 `.docx`、`.pptx`、`.md`、`.txt` 一键导入为待发布草稿；草稿可在导入页恢复编辑或取消，原始资料会与正式案例关联留存。案例还可关联多个日志，并会自动关联关键词或日志命中的现有特征。旧版 `.doc` / `.ppt` 在服务器安装 LibreOffice 后可本地转换导入；案例正文与特征共同成为智能问答的知识来源。
- 新建或编辑特征时可上传来源日志。AI 复核页会从实际来源日志按每一条当前规则重新提取文件、行号和原文片段，再让维护人员确认或驳回“该日志可作为此特征依据”。
- 看板展示累计上传、已完成分析、特征、高风险特征、最近报告与最新规则，并按每人发布的特征数与案例数生成知识贡献榜。
- 需求板允许每位登录用户提交功能、流程、界面或知识需求；需求从待评审进入采纳、规划中、已实现或暂不处理，并保留全部评审时间线。团队可按每周或每两周集中评审。
- 智能问答和每份报告都提供流式 LLM 输出，并实时渲染 Markdown；问答会按账号保存历史消息，未配置密钥时安全降级为本地特征与案例建议。
- 每份完成报告均可导出独立的 HTML 问题分析报告；原始日志仅上传者、审核者和管理员可下载。报告包含公司 BMC Skill（如已配置）、当前特征库结果、文件/行号证据与处置建议。
- 深浅色液态玻璃界面；主导航会明确标识当前所在页面，各页面右上角“帮助”附带操作指引与作者署名。

Markdown 编辑补充：选中文字后，富文本和 Markdown 都可使用顶部格式工具栏；在 Markdown 中按 Command+B（Windows/Linux 为 Ctrl+B）会插入或取消加粗语法。

## LLM 配置

仅在本机或服务器 `.env` 设置，绝不可把真实 Key 写入源码、交付包或数据库：

```ini
LLM_API_KEY=你的密钥
LLM_BASE_URL=https://兼容-openai-接口的地址/v1
LLM_MODEL=模型名称
```

需求评审权限与节奏同样只在本机或服务器 `.env` 中设置：

```ini
REQUEST_REVIEWERS=用户名1,用户名2
REQUEST_REVIEW_CADENCE=每周
```

本地演示默认由 `demo-maintainer` 评审；生产环境请替换为公司指定的评审账号。

系统调用 OpenAI Chat Completions 兼容接口并启用 `stream: true`。页面使用 `/ask/stream` 和 `/reports/{id}/llm/stream` 接收分段文本。提供 Key 前，可先用无 Key 模式验证完整本地流程。

当前本地验证已通过 DeepSeek OpenAI 兼容接口：`LLM_BASE_URL=https://api.deepseek.com`、`LLM_MODEL=deepseek-v4-flash`。密钥仅存在于本机 `.env`，未写入此文档或交付包。

## 账号、权限与生产安全

所有业务页面都需要登录。当前内置角色如下：

- `contributor`：创建和维护自己上传的日志、特征、案例和工具。
- `reviewer`：在贡献者基础上，可下载团队原始日志/案例源文件，并复核特征的来源日志。
- `admin`：跨账号管理特征和审核工作；仅应授予平台负责人。

特征来源日志的“确认/驳回”仅限特征创建者、审核者或管理员；原始导入 Word/PPT 文件仅限导入人、案例作者、审核者或管理员。所有修改型请求均带 CSRF Token，登录成功后会轮换会话和 CSRF Token。

账号通过受控脚本管理，避免生产环境开放注册：

```bash
# 查看账号与角色
.venv/bin/python scripts/manage_users.py list
# 创建首位管理员（密码由终端交互输入）
.venv/bin/python scripts/manage_users.py create --username bmc-admin --role admin
# 调整角色
.venv/bin/python scripts/manage_users.py set-role --username colleague --role reviewer
```

生产 `.env` 至少应包含：

```ini
APP_ENV=production
APP_SECRET=使用公司密码库或 openssl rand -hex 48 生成的随机值
SESSION_HTTPS_ONLY=true
ALLOW_SELF_REGISTRATION=false
```

## 公司内网 BMC Skill 接口

特征库用于团队维护的文本/正则规则；公司内网 BMC Skill 用于错误码、阈值、时间关联和多文件上下文等复杂解析。二者会在日志上传时并行运行，结果共同进入报告。没有配置 Skill 时不影响特征库分析。

```ini
# .env，仅限受控内网部署环境
BMC_SKILL_ADAPTER=app.skills.company_bmc:analyze_log_bundle
```

后续拿到公司 Skill 说明后，将规则实现为受控本地模块即可；完整函数签名、返回格式、测试和安全要求见 [docs/BMC_SKILL_INTERFACE.md](docs/BMC_SKILL_INTERFACE.md)。示例文件 [app/skills/company_bmc_example.py](app/skills/company_bmc_example.py) 默认不会生成任何告警。

## openEuler 24.03 AArch64（待本地调试确认后部署）

目标平台为 `aarch64`、Python 3.10+。官方 Python 基础镜像可自动选择 ARM64 架构；若原生部署，建议安装编译依赖以兼容某些 Python wheel：

```bash
sudo dnf install -y python3 python3-pip python3-devel gcc nginx firewalld policycoreutils-python-utils
```

如果团队需要直接导入旧版 `.doc` / `.ppt`，再安装 LibreOffice，并在 `.env` 设置 `CASE_IMPORT_SOFFICE=soffice`（或实际可执行文件路径）。DOCX、PPTX、Markdown 和 TXT 不依赖 LibreOffice；导入在服务器本地完成，不会把资料发送给外部模型。

部署顺序、systemd、Nginx、SELinux 和防火墙配置见 `deploy/`。`deploy/nginx-bmc-hub.conf` 是 HTTPS 模板，必须替换内部域名和公司证书路径后再启用；生产环境会拒绝默认会话密钥或非 HTTPS Cookie 配置。

## 数据、备份与规则扩展

SQLite 数据库保存在 `data/`，日志/工具/Logo 附件保存在 `uploads/`。迁移、备份或恢复时必须同时保留二者。日志报告页提供“下载原始日志”和“导出 HTML 报告”；若要保存多年，应由服务器定期将 `data/` 与 `uploads/` 一起备份到公司受控存储，并定期执行恢复演练。真实厂商日志规则接入方法、LLM 移交方法、数据库迁移和更新步骤见 [docs/HANDOFF.md](docs/HANDOFF.md)。

关键数据一致性回归测试：

```bash
.venv/bin/python -m unittest discover -v
```

创建不含生产数据、附件、密钥与本机虚拟环境的交付包：

```bash
chmod +x scripts/package-release.sh
./scripts/package-release.sh
# 如需指定版本：./scripts/package-release.sh 0.4.1-local
```
