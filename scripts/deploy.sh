#!/usr/bin/env bash
# 部署 / 更新脚本——在 VPS 上跑：
#   ssh deploy@<vps> 'cd ~/apps/Voice-Gender-Analyzer && bash scripts/deploy.sh [选项]'
#
# 默认行为：
#   - 走当前分支 git pull
#   - 自动检测改动范围决定 rebuild 哪个镜像（app / sidecar / 都不 build）
#   - 健康检查通过后清理悬挂镜像
#   - 失败时可回滚到上一版镜像 + commit
#
# 常用：
#   bash scripts/deploy.sh                       # 全自动
#   bash scripts/deploy.sh -b main               # 切到 main 再 pull
#   bash scripts/deploy.sh -r app                # 强制只 rebuild app
#   bash scripts/deploy.sh -r none               # 不 build，只 restart（适合改 .env）
#   bash scripts/deploy.sh -y                    # 全部跳过确认
#   bash scripts/deploy.sh --dry-run             # 只打印动作
#   bash scripts/deploy.sh --rollback            # 回到上一版（标了 :rollback 的镜像 + 上一个 commit）
#   bash scripts/deploy.sh --status              # 只看当前状态，不动
set -euo pipefail

BRANCH=""
REBUILD="auto"
ASSUME_YES=0
DRY_RUN=0
ROLLBACK=0
STATUS_ONLY=0

usage() {
	cat <<'EOF'
用法: bash scripts/deploy.sh [选项]

  -b, --branch <name>    切到指定分支（默认：当前分支）
  -r, --rebuild <scope>  rebuild 范围:
                           auto    根据 git diff 自动判断（默认）
                           app     只 build app
                           sidecar 只 build visualizer-backend
                           all     两个都 build
                           none    不 build，仅重启 compose
  -y, --yes              跳过所有确认
      --dry-run          打印动作但不执行
      --rollback         回到上一版（:rollback 镜像 + 上一个 commit）
      --status           只显示当前状态
  -h, --help             显示本帮助
EOF
}

while [[ $# -gt 0 ]]; do
	case "$1" in
		-b|--branch)  BRANCH="$2"; shift 2 ;;
		-r|--rebuild) REBUILD="$2"; shift 2 ;;
		-y|--yes)     ASSUME_YES=1; shift ;;
		--dry-run)    DRY_RUN=1; shift ;;
		--rollback)   ROLLBACK=1; shift ;;
		--status)     STATUS_ONLY=1; shift ;;
		-h|--help)    usage; exit 0 ;;
		*) echo "未知选项: $1" >&2; usage; exit 2 ;;
	esac
done

case "$REBUILD" in
	auto|app|sidecar|all|none) ;;
	*) echo "无效 --rebuild: $REBUILD（auto|app|sidecar|all|none）" >&2; exit 2 ;;
esac

# ──────────── 工具函数 ────────────
C_INFO=$'\033[1;36m'
C_WARN=$'\033[1;33m'
C_ERR=$'\033[1;31m'
C_OK=$'\033[1;32m'
C_END=$'\033[0m'
log()  { printf '%s[%s]%s %s\n' "$C_INFO" "$(date +%H:%M:%S)" "$C_END" "$*"; }
warn() { printf '%s[warn]%s %s\n' "$C_WARN" "$C_END" "$*"; }
err()  { printf '%s[err ]%s %s\n' "$C_ERR" "$C_END" "$*" >&2; }
ok()   { printf '%s[ok  ]%s %s\n' "$C_OK" "$C_END" "$*"; }

run() {
	if [[ $DRY_RUN -eq 1 ]]; then
		printf '   %s[dry]%s %s\n' "$C_WARN" "$C_END" "$*"
	else
		eval "$@"
	fi
}

confirm() {
	[[ $ASSUME_YES -eq 1 ]] && return 0
	[[ $DRY_RUN -eq 1 ]] && return 0
	local ans
	read -rp "$1 [y/N] " ans
	[[ "$ans" =~ ^[Yy]$ ]]
}

# ──────────── 切到项目根 ────────────
cd "$(dirname "$0")/.."
PROJECT_ROOT="$PWD"

# ──────────── 校验环境 ────────────
[[ -f .env ]] || { err ".env 不存在；先 cp .env.example .env"; exit 1; }
docker compose version >/dev/null 2>&1 || { err "docker compose 不可用"; exit 1; }

ENGINE_C_FLAG=""
if grep -q '^ENGINE_C_ENABLED=true' .env; then
	ENGINE_C_FLAG="--profile engine-c"
fi

# ──────────── 仅显示状态 ────────────
if [[ $STATUS_ONLY -eq 1 ]]; then
	echo "── git ──"
	git log --oneline -3
	echo "── compose ──"
	docker compose $ENGINE_C_FLAG ps
	echo "── 资源 ──"
	free -h | head -2
	df -h "$PROJECT_ROOT" | tail -1
	exit 0
fi

# ──────────── 回滚分支 ────────────
if [[ $ROLLBACK -eq 1 ]]; then
	[[ -f .deploy-prev-commit ]] || { err "找不到 .deploy-prev-commit，无法回滚"; exit 1; }
	PREV=$(cat .deploy-prev-commit)
	log "回滚到 commit: ${PREV:0:8}"
	confirm "确认回滚？" || exit 1

	for img in voice-gender-analyzer-app voice-gender-analyzer-visualizer-backend; do
		if docker image inspect "${img}:rollback" >/dev/null 2>&1; then
			run "docker tag ${img}:rollback ${img}:latest"
			ok "已恢复 ${img}:latest ← :rollback"
		fi
	done
	run "git reset --hard $PREV"
	run "docker compose $ENGINE_C_FLAG up -d"
	ok "回滚完成；跑 'bash scripts/deploy.sh --status' 查看当前状态"
	exit 0
fi

# ──────────── git 状态预检 ────────────
if [[ -n "$(git status --porcelain)" ]]; then
	warn "工作树有未提交的改动："
	git status --short
	confirm "继续？（git pull 可能与未提交改动冲突）" || exit 1
fi

CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD)
[[ -z "$BRANCH" ]] && BRANCH="$CURRENT_BRANCH"
OLD_COMMIT=$(git rev-parse HEAD)
log "分支：$CURRENT_BRANCH    目标：$BRANCH    当前 commit：${OLD_COMMIT:0:8}"

# ──────────── git fetch + 展示将要更新的内容 ────────────
log "git fetch origin"
run "git fetch origin --prune"

if [[ $DRY_RUN -eq 0 ]]; then
	REMOTE_REF="origin/$BRANCH"
	if git rev-parse --verify --quiet "$REMOTE_REF" >/dev/null; then
		REMOTE_COMMIT=$(git rev-parse "$REMOTE_REF")
		if [[ "$OLD_COMMIT" != "$REMOTE_COMMIT" ]]; then
			echo "── 即将拉取的 commits ──"
			git log --oneline "$OLD_COMMIT..$REMOTE_COMMIT" | head -20 || true
			echo "── 涉及的文件 ──"
			git diff --stat "$OLD_COMMIT..$REMOTE_COMMIT" | tail -20 || true
		else
			log "远端 $BRANCH 与本地一致"
		fi
	else
		warn "远端没有分支 $REMOTE_REF"
	fi
fi

# ──────────── 切分支 + pull ────────────
if [[ "$BRANCH" != "$CURRENT_BRANCH" ]]; then
	log "切到 $BRANCH"
	run "git checkout $BRANCH"
fi
log "git pull --ff-only"
run "git pull --ff-only"

NEW_COMMIT=$(git rev-parse HEAD)

# ──────────── 子模块 ────────────
log "submodule update"
run "git submodule update --init --recursive"

# ──────────── auto 检测 rebuild 范围 ────────────
detect_rebuild() {
	if [[ "$OLD_COMMIT" == "$NEW_COMMIT" ]]; then
		echo "none"
		return
	fi
	local changed app=0 sidecar=0
	changed=$(git diff --name-only "$OLD_COMMIT" "$NEW_COMMIT")
	# sidecar 改动：voiceya/sidecars/** 或 sidecar Dockerfile
	if echo "$changed" | grep -qE '^voiceya/sidecars/|/visualizer-backend\.Dockerfile$'; then
		sidecar=1
	fi
	# app 改动：除 sidecar / docs / tests / *.md 外，凡涉及 .py/web/Dockerfile/lock 都算
	local app_files
	app_files=$(echo "$changed" \
		| grep -vE '^voiceya/sidecars/' \
		| grep -vE '^(docs/|tests/|README|\.github/|railway.*\.toml$|.*\.md$|scripts/deploy\.sh$)' || true)
	if echo "$app_files" | grep -qE '\.(py|js|jsx|ts|tsx|css|html|json|toml|lock|yaml|yml)$|^Dockerfile$|^pyproject\.toml$|^uv\.lock$|^pnpm-lock\.yaml$|^web/'; then
		app=1
	fi
	if [[ $app -eq 1 && $sidecar -eq 1 ]]; then echo "all"
	elif [[ $app -eq 1 ]]; then echo "app"
	elif [[ $sidecar -eq 1 ]]; then echo "sidecar"
	else echo "none"
	fi
}

if [[ "$REBUILD" == "auto" ]]; then
	REBUILD=$(detect_rebuild)
	log "auto 检测 → rebuild=$REBUILD"
fi

if [[ "$OLD_COMMIT" == "$NEW_COMMIT" && "$REBUILD" == "none" ]]; then
	ok "代码无更新且无需 rebuild，退出"
	exit 0
fi

log "rebuild 范围：$REBUILD"
confirm "继续部署？" || exit 1

# 记录回滚点
echo "$OLD_COMMIT" > .deploy-prev-commit

# ──────────── 标记 :rollback 镜像 ────────────
tag_rollback() {
	local img="$1"
	if docker image inspect "${img}:latest" >/dev/null 2>&1; then
		run "docker tag ${img}:latest ${img}:rollback"
		log "已标记 ${img}:rollback"
	fi
}

# ──────────── Build（串行避免 8GB 实例 OOM）────────────
case "$REBUILD" in
	app)
		tag_rollback voice-gender-analyzer-app
		log "build app"
		run "docker compose build app"
		;;
	sidecar)
		tag_rollback voice-gender-analyzer-visualizer-backend
		log "build sidecar（10+ 分钟）"
		run "docker compose $ENGINE_C_FLAG build visualizer-backend"
		;;
	all)
		tag_rollback voice-gender-analyzer-app
		tag_rollback voice-gender-analyzer-visualizer-backend
		log "build app（先）"
		run "docker compose build app"
		log "build sidecar（再，串行避免 OOM）"
		run "docker compose $ENGINE_C_FLAG build visualizer-backend"
		;;
	none)
		log "跳过 build"
		;;
esac

# ──────────── 起服务 ────────────
log "docker compose $ENGINE_C_FLAG up -d"
run "docker compose $ENGINE_C_FLAG up -d"

# ──────────── 健康检查 ────────────
health_check() {
	local timeout=120 elapsed=0
	log "等 app /api/config 200..."
	while [[ $elapsed -lt $timeout ]]; do
		if curl -fsS --max-time 5 http://localhost:8080/api/config >/dev/null 2>&1; then
			ok "app healthy"
			break
		fi
		sleep 3; elapsed=$((elapsed+3)); printf '.'
	done; echo
	[[ $elapsed -ge $timeout ]] && { err "app 健康检查超时"; return 1; }

	if [[ -n "$ENGINE_C_FLAG" ]]; then
		log "等 sidecar /healthz..."
		elapsed=0
		while [[ $elapsed -lt $timeout ]]; do
			if docker compose exec -T app python -c "import urllib.request as u; u.urlopen('http://visualizer-backend:8001/healthz', timeout=5)" >/dev/null 2>&1; then
				ok "sidecar healthy"
				break
			fi
			sleep 3; elapsed=$((elapsed+3)); printf '.'
		done; echo
		[[ $elapsed -ge $timeout ]] && { err "sidecar 健康检查超时"; return 1; }
	fi
}

if [[ $DRY_RUN -eq 0 ]]; then
	if ! health_check; then
		err "健康检查失败"
		warn "查看日志：docker compose logs --tail 50 app"
		warn "回滚：bash scripts/deploy.sh --rollback"
		exit 1
	fi
fi

# ──────────── 清理 ────────────
log "清理悬挂镜像（保留 :rollback 标签）"
run "docker image prune -f"

# ──────────── 总结 ────────────
echo
ok "部署完成"
echo "    分支:     $BRANCH"
echo "    commit:   ${OLD_COMMIT:0:8} → ${NEW_COMMIT:0:8}"
echo "    rebuild:  $REBUILD"
echo
docker compose $ENGINE_C_FLAG ps
