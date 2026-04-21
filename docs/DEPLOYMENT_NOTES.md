# Deployment Notes

## Redis URL 配置

项目同时支持两个环境变量名指向 Redis：

| 变量名 | 来源 | 场景 |
|--------|------|------|
| `REDIS_URI` | Railway 平台自动注入 | Railway 部署 |
| `REDIS_URL` | Docker Compose / 手动配置 | Docker 自建、裸机开发 |

优先级由 `voiceya/config.py` 的 `AliasChoices("REDIS_URI", "REDIS_URL")` 决定——**`REDIS_URI` 优先**。

### Docker Compose 注意事项

`docker-compose.yml` 的 `environment:` 块**必须同时覆盖两个变量名**：

```yaml
environment:
  REDIS_URL: redis://redis:6379/0
  REDIS_URI: redis://redis:6379/0
```

原因：`env_file: - .env` 会把 `.env` 中的所有变量注入容器。如果 `.env` 里写了
`REDIS_URI=redis://localhost:6379/0`（本地开发地址），而 `environment:` 只覆盖了
`REDIS_URL`，Pydantic 会优先取 `REDIS_URI` 的 localhost 值，导致容器内连不上 Redis。

### `.env` 本地开发

`.env` 不入库（`.gitignore`）。创建时以 `.env.example` 为模板：

```bash
cp .env.example .env
# 裸机开发：把 REDIS_URL 改为 redis://localhost:6379/0
# Docker：保持 redis://redis:6379/0 不动
```

建议统一使用 `REDIS_URL` 作为变量名。`REDIS_URI` 仅在 Railway 环境中由平台自动设置。

## Engine C Sidecar

`ENGINE_C_SIDECAR_URL` 没有别名问题——只有一个变量名，且 `config.py` 中有正确的默认值
`http://visualizer-backend:8001`。Docker Compose 和 `.env.example` 中的值一致。

启用 Engine C：

```bash
# .env 中设置
ENGINE_C_ENABLED=true

# 启动时带 profile
docker compose --profile engine-c up -d --build
```

sidecar 镜像约 2.5 GB，首次构建下载 MFA 模型耗时可达 10 分钟。
