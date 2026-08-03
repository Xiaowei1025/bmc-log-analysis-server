# 安全策略

## 报告安全问题

请不要在公开 Issue、Pull Request、截图或聊天记录中提交 API Key、Cookie、WeLink 凭证、原始 BMC 日志、客户信息或服务器地址。

优先使用 GitHub 仓库的私密漏洞报告入口；如果该入口不可用，请通过仓库维护者的 GitHub 私信提交最小化的复现信息。报告中请说明影响范围、复现步骤、受影响版本和建议的临时缓解方式，不要附带真实日志或密钥。

## 凭证处理

- 所有模型 Key、`APP_SECRET`、WeLink 桥接 Token 和 TLS 私钥只允许保存在部署服务器的受控环境变量或密码库中。
- 如果凭证曾经出现在聊天、终端输出、截图或日志中，应立即撤销并重新生成；不要只依赖删除提交。
- 发现疑似泄露时，先撤销/轮换凭证，再检查 Git 历史和部署主机访问日志。

## 数据边界

`data/`、`uploads/`、`examples/`、`deliverables/` 和 `.env` 已加入 Git 忽略规则。贡献代码时只能使用脱敏、最小化的测试数据；公司日志、客户信息和内部 WeLink 内容不得进入本公开仓库。

## 发布前检查

提交前运行：

```bash
.venv312/bin/python -m compileall -q app tests
.venv312/bin/python -m unittest discover -v
git diff --check
```

同时检查待提交文件和 Git 历史中没有真实密钥、数据库、上传文件或内部日志样例。
