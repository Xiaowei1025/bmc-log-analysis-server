# WeLink Windows 本地连接器 MVP

## 目标与安全边界

连接器是安装在每位使用者 Windows 电脑上的小程序/Windows Service。它使用该用户在本机已经登录的 WeLink CLI，服务器只保存分组配置、任务状态和结构化结果：

```text
Windows Connector -> 本机固定命令白名单 -> 用户自己的 WeLink CLI
        ^ HTTPS 心跳/任务租约/结果
        |
openEuler FastAPI + SQLite/PostgreSQL
```

浏览器不直接调用 `localhost`，服务器也不保存用户密码、Cookie、CLI 登录态或任意 shell 字符串。连接器令牌只在配对响应中显示一次，撤销后立即失效。

## 服务器配置

```ini
WELINK_CONNECTOR_ENABLED=1
```

重启服务后，登录用户在“重大巡检 → 自动化流程”点击“生成连接器令牌”。生产模式点击“开始巡检”会创建一个分组任务，连接器主动领取；未启用连接器时，生产巡检仍会明确提示未配置执行器。

## 协议

所有接口均使用 HTTPS 和 `Authorization: Bearer <token>`，响应为 JSON：

| 方法 | 接口 | 用途 |
| --- | --- | --- |
| POST | `/welink/connectors/pair` | 已登录网页生成一次性设备令牌；令牌只显示一次 |
| POST | `/api/welink/connectors/heartbeat` | 更新设备心跳与能力 |
| GET | `/api/welink/connectors/jobs` | 领取当前账号所属分组的一个任务；返回 5 分钟租约 |
| POST | `/api/welink/connectors/jobs/{id}/ack` | `running`、`failed`、`cancelled` 状态确认 |
| POST | `/api/welink/connectors/jobs/{id}/result` | 回传消息、问题、证据、行动项、报告和投递结果 |
| POST | `/welink/connectors/{id}/revoke` | 网页撤销设备 |

任务的 `payload` 只含结构化 `sources`、`recipients` 和回看天数。结果中建议使用以下字段：

```json
{
  "ok": true,
  "summary": "已完成读取和投递",
  "issues": [{
    "title": "风扇转速异常", "severity": "P1", "status": "处理中",
    "background": "...", "latest_progress": "...", "root_cause": "...",
    "next_step": "...", "owner": "00983211", "participants": ["00983211"],
    "evidence": [{"source_name": "问题讨论群", "author": "...", "message_time": "...", "excerpt": "...", "is_key": true}],
    "actions": [{"title": "更换风扇", "owner": "...", "due_at": "...", "status": "待执行", "priority": "高"}]
  }],
  "report": "## 巡检报告\n..."
}
```

服务器对结果做长度、类型和分组边界校验；问题、证据、行动项和报告进入当前分组，不会因为客户端提交其他 `group_id` 而越权写入。

## Windows 部署

1. 安装公司批准的 Python 3.11（或使用后续打包的单文件 exe）。
2. 将 `connector/windows_connector.py` 和 `connector/config.example.json` 复制到 `C:\ProgramData\BmcWelinkConnector\`，复制配置为 `config.json`。
3. 填写服务器 HTTPS 地址、一次性令牌和本机 WeLink CLI 的绝对路径；不要把配置提交 Git 或发给其他人。
4. 先使用 `--dry-run` 验证网络、令牌和任务往返，再注册为 Windows Service/任务计划程序。服务账号必须是已登录并获授权使用 WeLink CLI 的账号。
5. 在服务器审计台账确认任务从“等待连接器领取”变为“已完成”，再使用授权测试群做真实读写验收。

当前仓库没有公司内部 WeLink CLI 的真实命令和返回格式，因此连接器中的 `WeLinkCliAdapter` 只提供固定命令适配边界，默认不会猜测或执行命令。内部 Agent 必须先向负责人索取 CLI 可执行文件版本、读取/发送子命令、JSON 输出样例、登录态位置、命令白名单和测试群，再补齐适配器和打包签名。

## 取消、重试与运维

- 服务器以 `idempotency_key` 防止定时任务和手动任务重复创建。
- 领取任务带 5 分钟租约；连接器崩溃后任务可重新排队。
- `attempts` 达到 `max_attempts` 后由运维处理，不自动无限重试。
- 令牌泄露时在网页撤销设备，再重新配对；不要在日志中打印令牌。
- systemd timer 每分钟执行一次 `python -m app.welink_scheduler`，只创建到期分组的连接器任务，不在 Uvicorn worker 中跑常驻调度。
