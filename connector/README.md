# Windows 本地连接器

这是可审计的 Python MVP 客户端。它不包含公司 WeLink CLI，也不会猜测 CLI 命令；收到内部 CLI 版本和 JSON 合约后，再由内部 Agent 完成 `WeLinkCliAdapter.inspect()` 的固定白名单实现，并打包签名为 exe/Windows Service。

本地验证：

```powershell
py -3.11 windows_connector.py --config config.json --once
```

先将 `config.example.json` 复制为 `config.json`，把服务器地址和网页生成的一次性令牌放入受保护目录。`dry_run=true` 只验证心跳、任务租约和结果回传，不读取或发送真实 WeLink 消息。
