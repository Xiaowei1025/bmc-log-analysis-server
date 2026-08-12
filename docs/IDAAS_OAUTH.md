# 华为 UniPortal OAuth 2.0 接入说明

当前项目只使用 OAuth 2.0 授权码模式，不使用 OIDC。用户在 Windows 浏览器打开部署在 openEuler 服务器上的应用，完整链路为：

```text
1. 用户点击“华为工号登录”
   -> GET /auth/login
   -> https://uniportal.huawei.com/saaslogin1/oauth2/authorize

2. 用户在 W3 完成登录和授权
   -> https://maintain.hicomputing.huawei.com/authorize?code=...&state=...

3. FastAPI 后端校验 state，使用 code + ClientID + Client_Secret
   -> Token endpoint（client_secret_basic）
   -> access_token

4. FastAPI 后端用 Authorization: Bearer <access_token>
   -> UserInfo endpoint
   -> 工号/姓名/群组 -> 本地用户和会话
```

授权请求同时使用 `state` 防止登录 CSRF，并使用 PKCE S256 保护授权码。项目不请求或解析 `id_token`，不访问 OIDC Discovery、issuer 或 JWKS。access token 只在单次回调请求的服务器进程内使用，不写入浏览器、SQLite、日志或 Git。

## 最小配置

OAuth 应用凭据只需两项：`ClientID` 和 `Client_Secret`。页面不提供凭据配置入口，Secret 只能通过公司密码库或服务器受控 `.env` 交付。

```ini
APP_ENV=production
APP_BASE_URL=https://maintain.hicomputing.huawei.com
SESSION_HTTPS_ONLY=true
AUTH_PROVIDER=oauth2

OAUTH_CLIENT_ID=<由华为应用管理提供>
OAUTH_CLIENT_SECRET=<只写入受控服务器环境>
```

应用默认回调为 `${APP_BASE_URL}/authorize`，因此华为应用管理端必须登记：

```text
https://maintain.hicomputing.huawei.com/authorize
```

回调地址的协议、域名、端口和路径必须逐字一致。生产环境必须使用 HTTPS。

## 内置端点与 Demo 校验边界

已确认的授权端点固定为：

```text
https://uniportal.huawei.com/saaslogin1/oauth2/authorize
```

在拿到公司 Demo 的 Token/UserInfo 样例前，代码使用同一 OAuth 根路径下的可覆盖默认值：

```text
https://uniportal.huawei.com/saaslogin1/oauth2/token
https://uniportal.huawei.com/saaslogin1/oauth2/userinfo
```

这两个路径是基于已确认 OAuth 根路径的待验证默认值。如公司 Demo 不同，只在服务器覆盖：

```ini
OAUTH_TOKEN_URL=https://<Demo 指定的 Token 路径>
OAUTH_USERINFO_URL=https://<Demo 指定的 UserInfo 路径>
```

不需要修改页面、回调路由、用户开通、权限或审计代码。授权端点也可通过 `OAUTH_AUTHORIZATION_URL` 在服务器上覆盖，但只应在公司 Demo 明确要求时使用。

## 拿到公司 Demo 后只需确认的内容

1. Token 和 UserInfo 的精确 URL，以及是否需要额外 scope。
2. Token 返回中 access token 的字段名（当前按标准 `access_token`）。
3. UserInfo 中代表稳定用户 ID、华为工号、姓名、邮箱和群组的字段名。
4. 是否提供 OAuth 登出端点；没有时只清除本地会话也可以。
5. 普通用户、审核者、管理员三类测试账号的最小权限验收。

## 登录后权限与应用管理

UserInfo 返回的工号 `j00983211` 或 `j00456121` 默认映射为最高管理员。管理员登录后可从顶部“应用管理”进入 `/admin`：

- 调整其他人员为贡献者或审核者；只有最高管理员可以授予新的管理员权限；
- 最高管理员不能被其他管理员降权，管理员不能在网页上修改自己的权限；
- 查看登录、退出、权限修改和关键写操作的审计记录。

审计不保存密码、Client Secret、access token、查询参数或表单正文。

## 灰度与生产验收

1. 先保持 `AUTH_PROVIDER=local`，执行 `.venv312/bin/python -m unittest discover -s tests -q`。
2. 在内网服务器写入受控 `.env`，先使用 `AUTH_PROVIDER=hybrid` 重启。
3. 打开 `/auth/login`，确认跳转到固定 UniPortal 授权路径，URL 含 `response_type=code`、`state`、`code_challenge`，不含 Client Secret。
4. W3 登录后确认回调 `/authorize`，不出现 404；错误 state、缺少 code、Token 失败都应回到受控登录错误页。
5. 确认 UserInfo 工号映射正确，`j00983211` 和 `j00456121` 都获得 `admin`；普通用户不能访问 `/admin`。
6. 检查 SQLite 和日志：不得出现 access token 或 Client Secret，重复登录不得创建重复用户。
7. 确认 HTTPS、Secure Cookie、反向代理转发头、回调域名和防火墙策略后，再把 `AUTH_PROVIDER` 切换为 `oauth2`。

## 常见故障

- 回调 404：确认华为管理端登记的是 `https://maintain.hicomputing.huawei.com/authorize`，并检查 Nginx 将 `/authorize` 转发给 FastAPI。
- `invalid_client`：核对 ClientID、Client_Secret 和 `client_secret_basic`；Secret 不应出现在 URL。
- `invalid_grant`：授权码只能使用一次，检查服务器时间、回调地址和 PKCE verifier。
- UserInfo 401/403：按公司 Demo 核对 UserInfo URL、scope 和 Bearer 请求头。
- 缺少稳定 ID：调整 `OAUTH_SUBJECT_CLAIMS`，不要用姓名或可变昵称作为外部身份主键。
