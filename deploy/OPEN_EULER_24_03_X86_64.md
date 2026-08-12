# openEuler 24.03 x86_64 / Python 3.11 部署

目标：将“硬件运维智能工作台”部署到受控内网 x86_64 服务器。服务仅监听 `127.0.0.1:8000`，由 Nginx 提供 HTTPS 入口。

最终使用拓扑：

```text
Windows 电脑上的 Edge/Chrome
        │  HTTPS（公司内网域名）
        ▼
openEuler 24.03 x86_64 服务器上的 Nginx
        │  http://127.0.0.1:8000
        ▼
Python 3.11 / FastAPI
        ├── SQLite、上传文件、模型 Key（只在服务器）
        └── WeLink 任务 API（服务器不保存个人 CLI 登录态）
Windows 用户电脑上的本地连接器
        └── 用户自己的 WeLink CLI 和登录态
```

Windows 用户不能访问文档中的 `127.0.0.1:8000`；该地址在 Windows 上只代表用户自己的电脑。最终入口必须是公司 DNS 域名，例如 `https://bmc-hub.internal.example`。

## 1. 服务器前置检查

```bash
uname -m                         # 必须为 x86_64
cat /etc/os-release
python3.11 --version             # 必须为 Python 3.11.x
```

在公司软件源中安装 Python 3.11、编译依赖、Nginx 与 SELinux 管理工具。不同镜像的软件包名可能略有不同，应先使用 `dnf search python3.11` 确认：

```bash
sudo dnf install -y python3.11 python3.11-pip python3.11-devel gcc nginx firewalld policycoreutils-python-utils
```

如需导入旧版 DOC/PPT，再安装受控的 LibreOffice；仅 DOCX/PPTX/Markdown/TXT 不需要它。

## 2. 安装交付包

1. 创建低权限运行账号：`sudo useradd --system --home /opt/bmc-hub --shell /sbin/nologin bmc-hub`。
2. 将由 `scripts/package-release.sh` 生成的源码包上传到 `/opt/bmc-hub` 并解压；不要上传 `.env`、`data/`、`uploads/` 或虚拟环境。
3. 创建 Python 3.11 虚拟环境并安装依赖：

```bash
sudo chown -R bmc-hub:bmc-hub /opt/bmc-hub
sudo -u bmc-hub python3.11 -m venv /opt/bmc-hub/.venv
sudo -u bmc-hub /opt/bmc-hub/.venv/bin/python -m pip install --upgrade pip
sudo -u bmc-hub /opt/bmc-hub/.venv/bin/python -m pip install -r /opt/bmc-hub/requirements.txt
```

4. 复制 `.env.example` 为 `/opt/bmc-hub/.env`，执行 `chmod 600` 并由 `bmc-hub` 所有。生产必填：

```ini
APP_ENV=production
APP_SECRET=使用受控密码库生成的至少 32 位随机值
SESSION_HTTPS_ONLY=true
ALLOW_SELF_REGISTRATION=false
WELINK_DEFAULT_MODE=demo
WELINK_CONNECTOR_ENABLED=0
```

先保持 `WELINK_DEFAULT_MODE=demo`。如果采用每人自己的 Windows 连接器，先设置 `WELINK_CONNECTOR_ENABLED=1`，配对测试设备后再由管理员切换为生产模式；服务器不会登录或保存任何个人 WeLink 账号。

## 3. WeLink 桥接/本地连接器契约

生产模式仅向 `WELINK_AGENT_BRIDGE_URL/v1/welink/runs` 发起 `POST`，携带 `Authorization: Bearer <WELINK_AGENT_BRIDGE_TOKEN>`。请求包含启用消息源和接收方的标识、类型、回看天数及备注；桥接端返回：

```json
{"status":"queued","summary":"任务已接受"}
```

如果公司已有受控桥接服务，可继续使用上述合约；否则启用 `docs/WELINK_CONNECTOR_MVP.md` 的 Windows 本地连接器：用户在网页生成一次性令牌，连接器通过心跳、租约和结果接口主动领取任务。`connector/windows_connector.py` 默认 dry-run/fail-closed，拿到公司 CLI 版本、命令白名单和 JSON 样例后再由内部 Agent 完成适配和签名打包。网页服务不得执行 shell 或接收任意 CLI 参数。

启用调度器：

```bash
sudo install -m 0644 deploy/bmc-welink-scheduler.service deploy/bmc-welink-scheduler.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now bmc-welink-scheduler.timer
systemctl list-timers bmc-welink-scheduler.timer
```

## 4. AI 模型档案

密钥仅放在 `/opt/bmc-hub/.env`。示例：

```ini
LLM_PROFILES_JSON=[{"id":"deepseek-flash","name":"DeepSeek Flash","base_url":"https://api.deepseek.com","model":"deepseek-v4-flash","api_key_env":"LLM_DEEPSEEK_FLASH_KEY"},{"id":"deepseek-pro","name":"DeepSeek Pro","base_url":"https://api.deepseek.com","model":"deepseek-v4-pro","api_key_env":"LLM_DEEPSEEK_PRO_KEY"}]
LLM_DEEPSEEK_FLASH_KEY=仅服务器保存
LLM_DEEPSEEK_PRO_KEY=仅服务器保存
```

管理员在“AI 模型”页面切换档案。SQLite 只保存档案 ID，不保存 Key；更换 Key 后重启服务。

## 5. systemd、Nginx 与 SELinux

```bash
sudo install -m 0644 deploy/bmc-hub.service /etc/systemd/system/bmc-hub.service
sudo systemctl daemon-reload
sudo systemctl enable --now bmc-hub
sudo install -m 0644 deploy/nginx-bmc-hub.conf /etc/nginx/conf.d/bmc-hub.conf
sudo nginx -t && sudo systemctl enable --now nginx
sudo setsebool -P httpd_can_network_connect 1
```

替换 Nginx 中的内部域名与公司证书路径，再开放 HTTPS 所需的内网访问策略。不要把 8000 端口直接暴露给用户网段。

Nginx 模板已对问答流接口关闭 `proxy_buffering`、`proxy_cache` 与 `gzip`，并把流式读取超时提高到 300 秒。不要删除这些配置，否则 Windows 浏览器可能积攒一批字符后才显示，停止按钮也不能及时中断。

## 6. Windows 浏览器验收

- 支持公司批准的新版 Microsoft Edge 或 Google Chrome，建议保持自动更新；不支持 Internet Explorer。
- Windows 需要信任公司签发的 HTTPS 根证书。地址栏出现证书警告时不得直接忽略，应由 IT 导入正确证书链。
- 浏览器必须允许本站 JavaScript 与同站 Cookie；系统不依赖 Google 登录、浏览器插件、macOS 文件路径或本机 WeLink CLI。
- 在 Windows 上逐项验证：登录、深浅色切换、中文字体、200 MB 内授权日志上传、Markdown 表格、问答流式输出、Ctrl+Enter、停止生成、刷新后的历史记录。
- 浏览器开发者工具 Network 中，`/ask/stream` 和 `/welink/chat/stream` 应持续接收分块响应；不能等请求结束后一次性出现全文。
- 文件选择器只把用户选中的文件内容上传到服务器，页面不得保存或依赖 `C:\...` 本地路径。

## 7. 验收与回滚

```bash
sudo journalctl -u bmc-hub -n 100 --no-pager
curl -I http://127.0.0.1:8000/login
sudo -u bmc-hub /opt/bmc-hub/.venv/bin/python -m unittest discover -v
```

验收顺序：登录、BMC 日志上传、模型档案切换、WeLink 演示任务、桥接生产任务（仅使用授权测试群）、数据备份恢复。升级或回滚前同时备份 `/opt/bmc-hub/data` 和 `/opt/bmc-hub/uploads`。
