# 旧文档说明

本文件名因历史版本保留，但当前工程**不使用 OIDC**。华为 UniPortal 接入已统一为 OAuth 2.0 Authorization Code + PKCE：授权回调为 `/authorize`，后端用 `client_secret_basic` 换取 `access_token`，再调用 UserInfo 获取工号、显示名和群组。新部署只需配置 ClientID 和 Client_Secret。

请阅读最新的 [IDAAS_OAUTH.md](IDAAS_OAUTH.md)。不要配置 `OIDC_ISSUER`、`OIDC_DISCOVERY_URL`、JWKS 或 ID Token；旧的 `OIDC_*` 环境变量只作为一次迁移期兼容输入，不应出现在新的内部部署配置中。
