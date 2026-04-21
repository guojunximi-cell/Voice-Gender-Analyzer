# Railway 部署：三条路径的对比与说明

> 目标读者：第一次部署本项目到 Railway 的人，或想把现有项目"一键复刻"给别人的人。

本项目是三服务结构（worker + Redis + 可选的 Engine C sidecar），跨服务之间靠
**变量引用**（`${{Service.VAR}}` 模板语法）连接。Railway 画布上的那条紫线不是必要的——
它是变量引用的副产物，只影响"图好不好看"，不影响运行时通不通。

## 路径 A：保存为 Template（真正的一键）

**适用场景**：你已经有一个跑通的 Railway 项目，想把它变成一个"别人点一下 URL
就能复刻整套"的链接。

步骤（全程在 Railway Web UI 里）：

1. 打开已部署好的项目。
2. 右上角菜单 → **Save as Template**（有时在 Settings → General 里）。
3. 填模板元信息（名字、描述、README、封面图）。
4. 选要包含哪些 service（默认三个都勾上）。
5. 对每个 service 的 env var 选择"值"还是"需用户填"（`ENGINE_C_SIDECAR_TOKEN` 选
   "generate random"；`REDIS_URL`、`ENGINE_C_SIDECAR_URL` 这类引用变量 Railway 会
   自动识别为"引用"而不需填值）。
6. 点 **Publish**，拿到一个 `https://railway.com/new/template/xxxxx` URL。
7. 把这个 URL 贴进 README 或分享链接，任何人点开都能一键复刻。

**要点**：路径 A 的"一键"来自 Template 快照——它记录的是你当前项目的服务拓扑 + 变量
**引用关系**，不是容器状态。克隆出来的项目是全新部署、冷启动。

## 路径 B：CLI Bootstrap 脚本（仓库里就有）

**适用场景**：你想从零拉一套新环境（自己测试、给团队别的成员起第二套、
或 Template 快照过期要重建），但不想在 Web UI 里点 20 下。

仓库根目录 `scripts/railway-bootstrap.sh` 是一个幂等脚本，用 Railway CLI 依次：

1. 创建新项目（或用当前目录已 link 的项目）
2. 加 Redis 数据库插件
3. 创建 worker service，连到本仓库
4. 创建 sidecar service，连到本仓库但用 `railway.sidecar.toml`
5. 为两个 service 设置 env var（关键是跨服务引用用 `${{Service.VAR}}` 语法）
6. 触发部署

用法：

```bash
# 先装 CLI：https://docs.railway.app/develop/cli
railway login
cd /path/to/Voice-Gender-Analyzer
bash scripts/railway-bootstrap.sh
```

> 注意：Railway CLI 对"用 GitHub repo 创建 service"的支持在不同版本有差异，
> 脚本里对不支持的步骤会打印手动操作提示——不会整个卡死。

## 路径 C：纯手动 UI（保留作为兜底）

原 README 里的那 4 步就是这条路——适合你只想跑一次、或想完全理解每一步发生了什么。

## 必要变量速查

| 变量 | 放哪个 Service | 值 / 来源 | 备注 |
|---|---|---|---|
| `REDIS_URL` | worker | `${{Redis.REDIS_URL}}` | Railway 加 Redis 插件后自动存在 |
| `ENGINE_C_ENABLED` | worker | `true` / `false` | 关了则不调 sidecar，主功能不受影响 |
| `ENGINE_C_SIDECAR_URL` | worker | `http://${{keen-balance.RAILWAY_PRIVATE_DOMAIN}}:8001` | 服务名 `keen-balance` 换成你实际的 sidecar 服务名 |
| `ENGINE_C_SIDECAR_TOKEN` | worker | 强随机字符串（`openssl rand -hex 32`） | 与 sidecar 的 `ENGINE_C_TOKEN` 必须一致 |
| `ENGINE_C_TOKEN` | sidecar | `${{Worker.ENGINE_C_SIDECAR_TOKEN}}` | 引用同一个随机值，两边自动同步 |

其它限额 / 日志变量全都可选，清单见 `.env.example`。

## 关于画布上的"连线"

Railway 只在一个 service 的 env var 里用了 `${{OtherService.VAR}}` 模板引用时才画线。

- 纯字符串值（例如 `http://keen-balance.railway.internal:8001`）**运行时能通**，
  但画布上不画线——因为 Railway 不扫字符串。
- 改成 `http://${{keen-balance.RAILWAY_PRIVATE_DOMAIN}}:8001` 运行时解析出来的
  地址**一模一样**，但画布会画线。

**结论**：功能跑得通就不用管画线；想让图好看再改成引用语法。

## Private Networking 前置检查

两个 service（worker 和 sidecar）都要在 Settings → Networking 里
**启用 Private Networking**，否则 `RAILWAY_PRIVATE_DOMAIN` 这个变量不存在，
引用出来是空字符串，连接会失败。老项目默认可能是关着的。
