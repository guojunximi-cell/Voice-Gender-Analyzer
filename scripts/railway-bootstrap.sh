#!/usr/bin/env bash
# Railway bootstrap — 把 Voice-Gender-Analyzer 的三服务结构（worker + Redis +
# Engine C sidecar）一次性在 Railway 拉起来。
#
# 前置：
#   - 安装 Railway CLI：https://docs.railway.app/develop/cli
#   - `railway login` 已完成
#   - 当前工作目录是本仓库根
#
# 约定：脚本幂等——重复跑只会补齐缺失的服务/变量，不会覆盖已有的值。
# Railway CLI 对"用 GitHub repo 创建 service"的支持在版本间有差异，遇到
# 需要在 UI 里手工点的步骤会打印明显提示，不会静默失败。

set -euo pipefail

# ── 配置（按需修改）──────────────────────────────────────────
PROJECT_NAME="${PROJECT_NAME:-voice-gender-analyzer}"
WORKER_SERVICE="${WORKER_SERVICE:-worker}"
SIDECAR_SERVICE="${SIDECAR_SERVICE:-keen-balance}"
ENGINE_C_ENABLED="${ENGINE_C_ENABLED:-true}"
SIDECAR_PORT="${SIDECAR_PORT:-8001}"

# ── 辅助函数 ─────────────────────────────────────────────────
log() { printf "\033[1;36m▶\033[0m %s\n" "$*"; }
warn() { printf "\033[1;33m!\033[0m %s\n" "$*" >&2; }
die() { printf "\033[1;31m✗\033[0m %s\n" "$*" >&2; exit 1; }

need() { command -v "$1" >/dev/null 2>&1 || die "缺少命令：$1"; }

# ── 前置检查 ─────────────────────────────────────────────────
need railway
need openssl

if ! railway whoami >/dev/null 2>&1; then
    die "Railway CLI 未登录，先执行 \`railway login\`"
fi

if [[ ! -f railway.toml ]] || [[ ! -f railway.sidecar.toml ]]; then
    die "请在 Voice-Gender-Analyzer 仓库根目录运行本脚本"
fi

# ── 1. 项目 ──────────────────────────────────────────────────
if [[ -f .railway/config.json ]] || railway status >/dev/null 2>&1; then
    log "检测到当前目录已 link 到 Railway 项目，沿用它"
else
    log "创建 Railway 项目：$PROJECT_NAME"
    railway init --name "$PROJECT_NAME"
fi

PROJECT_ID="$(railway status --json 2>/dev/null | sed -n 's/.*"projectId"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p')"
[[ -n "${PROJECT_ID:-}" ]] || warn "无法解析 projectId，后续步骤可能需要手动在 UI 里完成"

# ── 2. Redis 插件 ────────────────────────────────────────────
log "添加 Redis 数据库（已存在则跳过）"
railway add --database redis 2>&1 | grep -vi 'already' || true

# ── 3. Worker service（当前目录指向的那个）──────────────────
# Railway CLI 的服务创建命令多次改名（service create / service add / add ...service）。
# 优先尝试常见组合，失败则打印手动提示。
log "确保 worker service 存在：$WORKER_SERVICE"
if ! railway service "$WORKER_SERVICE" >/dev/null 2>&1; then
    if ! railway add --service "$WORKER_SERVICE" 2>/dev/null \
        && ! railway service create "$WORKER_SERVICE" 2>/dev/null; then
        warn "无法通过 CLI 创建 '$WORKER_SERVICE'——请在 Railway UI：
    New Service → GitHub Repo → 选本仓库，服务名改成 '$WORKER_SERVICE'
    然后重跑本脚本补齐变量。"
    fi
fi

# ── 4. Sidecar service（Engine C）─────────────────────────────
if [[ "$ENGINE_C_ENABLED" == "true" ]]; then
    log "确保 sidecar service 存在：$SIDECAR_SERVICE"
    if ! railway service "$SIDECAR_SERVICE" >/dev/null 2>&1; then
        if ! railway add --service "$SIDECAR_SERVICE" 2>/dev/null \
            && ! railway service create "$SIDECAR_SERVICE" 2>/dev/null; then
            warn "无法通过 CLI 创建 '$SIDECAR_SERVICE'——请在 Railway UI 手动创建，
    Config-as-Code Path 设为 'railway.sidecar.toml'，然后重跑本脚本。"
        fi
    fi
fi

# ── 5. 密钥（如无则生成）─────────────────────────────────────
TOKEN_EXISTS="$(railway variables --service "$WORKER_SERVICE" --json 2>/dev/null \
    | grep -c '"ENGINE_C_SIDECAR_TOKEN"' || true)"
if [[ "$TOKEN_EXISTS" == "0" ]]; then
    SHARED_TOKEN="$(openssl rand -hex 32)"
    log "生成 ENGINE_C_SIDECAR_TOKEN 并写入 worker"
    railway variables --service "$WORKER_SERVICE" --set "ENGINE_C_SIDECAR_TOKEN=$SHARED_TOKEN"
else
    log "ENGINE_C_SIDECAR_TOKEN 已存在，跳过"
fi

# ── 6. Worker 端引用变量 ─────────────────────────────────────
log "Worker: 写入跨服务引用变量（画布上的线靠这些画出来）"
railway variables --service "$WORKER_SERVICE" \
    --set "REDIS_URL=\${{Redis.REDIS_URL}}" \
    --set "ENGINE_C_ENABLED=$ENGINE_C_ENABLED" \
    --set "ENGINE_C_SIDECAR_URL=http://\${{${SIDECAR_SERVICE}.RAILWAY_PRIVATE_DOMAIN}}:${SIDECAR_PORT}" \
    --set "ENGINE_C_SIDECAR_TIMEOUT_SEC=60"

# ── 7. Sidecar 端引用 ────────────────────────────────────────
if [[ "$ENGINE_C_ENABLED" == "true" ]]; then
    log "Sidecar: 引用 worker 的 TOKEN（保证两端共享同一个值）"
    railway variables --service "$SIDECAR_SERVICE" \
        --set "ENGINE_C_TOKEN=\${{${WORKER_SERVICE}.ENGINE_C_SIDECAR_TOKEN}}" \
        --set "ENGINE_C_MAX_AUDIO_MB=50" || warn "sidecar 变量写入失败——服务可能还没创建"
fi

# ── 8. 触发部署 ──────────────────────────────────────────────
log "触发 worker 重新部署"
railway redeploy --service "$WORKER_SERVICE" || warn "redeploy 失败，UI 里点一下 Deploy 即可"

if [[ "$ENGINE_C_ENABLED" == "true" ]]; then
    log "触发 sidecar 重新部署（首次约 10 分钟，需要下载 MFA 模型）"
    railway redeploy --service "$SIDECAR_SERVICE" || warn "sidecar redeploy 失败，UI 里点一下 Deploy"
fi

# ── 9. 收尾提示 ──────────────────────────────────────────────
cat <<EOF

\033[1;32m✓ Bootstrap 完成\033[0m

下一步手动检查（CLI 覆盖不到的）：
  1. 两个服务 → Settings → Networking → 确认 Private Networking 已启用
  2. Worker 服务 → Settings → Networking → 点 'Generate Domain' 暴露公网端口
  3. 画布页 → 应看到 Worker → Redis、Worker → $SIDECAR_SERVICE 两条紫线
  4. 打开公网 URL，上传音频验证 Engine C 数字是否出现在右栏

文档：docs/RAILWAY_DEPLOY.md
EOF
