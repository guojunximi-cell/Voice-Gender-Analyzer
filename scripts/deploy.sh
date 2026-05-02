#!/usr/bin/env bash
# 部署 / 更新脚本——在 VPS 上跑：
#   ssh deploy@<vps> 'cd ~/apps/Voice-Gender-Analyzer && bash scripts/deploy.sh [选项]'
#
# 默认行为：
#   - 走当前分支 git pull
#   - 自动检测 已部署commit→目标commit 的差异决定 rebuild 哪个镜像
#   - 健康检查通过后清理悬挂镜像
#   - 失败时可回滚到上一版镜像 + commit
#
# 常用：
#   bash scripts/deploy.sh                       # 全自动（弹分支菜单）
#   bash scripts/deploy.sh -b main               # 指定分支
#   bash scripts/deploy.sh -r app                # 强制只 rebuild app
#   bash scripts/deploy.sh -r none               # 不 build，只 restart（适合改 .env）
#   bash scripts/deploy.sh -y                    # 全部跳过确认（用当前分支）
#   bash scripts/deploy.sh --dry-run             # 只打印动作
#   bash scripts/deploy.sh --rollback            # 回到上一版（:rollback 镜像 + 上一个 commit）
#   bash scripts/deploy.sh --status              # 只看当前状态
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

  -b, --branch <name>    切到指定分支（不传时：交互式菜单选择；
                         非交互/带 -y 时回退到当前分支）
  -r, --rebuild <scope>  rebuild 范围:
                           auto    根据 已部署→目标 的 git diff 自动判断（默认）
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
log()  { printf '%s[%s]%s %s\n' "$C_INFO" "$(date +%H:%M:%S)" "$C_END" "$*" >&2; }
warn() { printf '%s[warn]%s %s\n' "$C_WARN" "$C_END" "$*" >&2; }
err()  { printf '%s[err ]%s %s\n' "$C_ERR" "$C_END" "$*" >&2; }
ok()   { printf '%s[ok  ]%s %s\n' "$C_OK" "$C_END" "$*" >&2; }

run() {
	if [[ $DRY_RUN -eq 1 ]]; then
		printf '   %s[dry]%s %s\n' "$C_WARN" "$C_END" "$*" >&2
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

# 状态文件放到 .git/ 里（git 永远不追踪，且 worktree 隔离）
STATE_FILE="$PROJECT_ROOT/.git/deploy-prev-commit"

# ──────────── 校验环境 ────────────
[[ -f .env ]] || { err ".env 不存在；先 cp .env.example .env"; exit 1; }
docker compose version >/dev/null 2>&1 || { err "docker compose 不可用"; exit 1; }

ENGINE_C_FLAG=""
if grep -q '^ENGINE_C_ENABLED=true' .env; then
	ENGINE_C_FLAG="--profile engine-c"
fi

# 已部署 commit（可能不存在 = 第一次部署）
read_deployed_commit() {
	[[ -f "$STATE_FILE" ]] || return 1
	local c
	c=$(head -1 "$STATE_FILE" | tr -d '[:space:]')
	[[ -n "$c" ]] || return 1
	# 校验该 commit 在当前 git 库里能找到
	git rev-parse --verify --quiet "$c^{commit}" >/dev/null || return 1
	printf '%s' "$c"
}

# ──────────── 仅显示状态 ────────────
if [[ $STATUS_ONLY -eq 1 ]]; then
	echo "── git ──"
	git log --oneline -3
	echo "── 已部署 commit ──"
	if dep=$(read_deployed_commit); then
		git log --oneline -1 "$dep" 2>/dev/null || echo "$dep"
	else
		echo "(未记录——首次部署或未通过 deploy.sh 部署过)"
	fi
	echo "── compose ──"
	docker compose $ENGINE_C_FLAG ps
	echo "── 资源 ──"
	free -h | head -2
	df -h "$PROJECT_ROOT" | tail -1
	exit 0
fi

# ──────────── 回滚分支 ────────────
if [[ $ROLLBACK -eq 1 ]]; then
	if ! PREV=$(read_deployed_commit); then
		err "找不到有效的 .git/deploy-prev-commit，无法回滚"
		exit 1
	fi
	log "回滚到 commit: ${PREV:0:8}"
	git log --oneline -1 "$PREV" >&2 || true
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
	git status --short >&2
	confirm "继续？（git pull / checkout 可能与未提交改动冲突）" || exit 1
fi

CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD)

# ──────────── 先 fetch（让分支列表是新鲜的） ────────────
log "git fetch origin"
run "git fetch origin --prune"

# ──────────── 选分支：CLI 参数 > 交互菜单 > 当前分支 ────────────
# 注意：所有交互输出（菜单、提示）必须 → stderr，stdout 只允许返回值
pick_branch_interactive() {
	local current=$1
	local -a branches=("$current")
	local b found x

	# 本地其它分支
	while read -r b; do
		[[ -n "$b" && "$b" != "$current" ]] && branches+=("$b")
	done < <(git for-each-ref --format='%(refname:short)' refs/heads/)

	# 远程独有分支（不在本地的）。注意 origin/HEAD 的 short ref 是 "origin"
	while read -r b; do
		[[ "$b" == origin/* ]] || continue   # 跳过 "origin"（HEAD pointer 短名）
		b="${b#origin/}"
		[[ -z "$b" || "$b" == "HEAD" ]] && continue
		found=0
		for x in "${branches[@]}"; do [[ "$x" == "$b" ]] && { found=1; break; }; done
		[[ $found -eq 0 ]] && branches+=("$b")
	done < <(git for-each-ref --format='%(refname:short)' refs/remotes/origin/)

	{
		echo
		echo "可用分支（* = 当前）："
		for i in "${!branches[@]}"; do
			local mark=" "
			[[ "${branches[i]}" == "$current" ]] && mark="*"
			printf "  [%2d] %s %s\n" "$((i+1))" "$mark" "${branches[i]}"
		done
		echo
	} >&2

	local choice
	read -rp "选择编号（回车 = 当前 $current）: " choice
	if [[ -z "$choice" ]]; then
		printf '%s' "$current"
	elif [[ "$choice" =~ ^[0-9]+$ ]] && (( choice >= 1 && choice <= ${#branches[@]} )); then
		printf '%s' "${branches[$((choice-1))]}"
	else
		err "无效编号: $choice"
		return 1
	fi
}

if [[ -z "$BRANCH" ]]; then
	# 没有 -b：交互模式（TTY + 非 -y + 非 dry-run）下弹菜单，否则用当前分支
	if [[ -t 0 && $ASSUME_YES -eq 0 && $DRY_RUN -eq 0 ]]; then
		BRANCH=$(pick_branch_interactive "$CURRENT_BRANCH") || exit 1
	else
		BRANCH="$CURRENT_BRANCH"
	fi
fi

# ──────────── 算"已部署 commit" 和 "目标 commit"（auto 检测的真实基准）────────────
DEPLOYED_COMMIT=""
if dep=$(read_deployed_commit); then
	DEPLOYED_COMMIT="$dep"
fi

# 目标 commit：dry-run 用 origin/$BRANCH 预演；否则就是 pull 后的 HEAD
if [[ $DRY_RUN -eq 1 ]]; then
	if git rev-parse --verify --quiet "origin/$BRANCH^{commit}" >/dev/null; then
		TARGET_COMMIT=$(git rev-parse "origin/$BRANCH")
	else
		TARGET_COMMIT=$(git rev-parse HEAD)
	fi
fi
# 非 dry-run 模式下 TARGET_COMMIT 在 pull 完之后再算

# 比较基准：优先用已部署 commit，否则用当前 HEAD
COMPARE_FROM="${DEPLOYED_COMMIT:-$(git rev-parse HEAD)}"

log "分支：$CURRENT_BRANCH    目标：$BRANCH"
log "已部署 commit：${DEPLOYED_COMMIT:-(无记录)}"

# ──────────── 切分支（友好处理脏树冲突）────────────
if [[ "$BRANCH" != "$CURRENT_BRANCH" ]]; then
	log "切到 $BRANCH"
	if [[ $DRY_RUN -eq 1 ]]; then
		printf '   %s[dry]%s git checkout %s\n' "$C_WARN" "$C_END" "$BRANCH" >&2
	else
		if ! git checkout "$BRANCH" 2>&1; then
			err "git checkout 失败——大概率是工作树有未提交改动与目标分支冲突"
			warn "处理方式（任选）："
			warn "  保留改动：git stash; bash scripts/deploy.sh; git stash pop"
			warn "  丢弃改动：git restore .; bash scripts/deploy.sh"
			exit 1
		fi
	fi
fi

# ──────────── 展示将要应用的改动 ────────────
PULL_TARGET="origin/$BRANCH"
if git rev-parse --verify --quiet "$PULL_TARGET^{commit}" >/dev/null; then
	REMOTE_COMMIT=$(git rev-parse "$PULL_TARGET")
	if [[ "$COMPARE_FROM" != "$REMOTE_COMMIT" ]]; then
		echo "── 将要应用的 commits（${COMPARE_FROM:0:8} → ${REMOTE_COMMIT:0:8}）──"
		git log --oneline "$COMPARE_FROM..$REMOTE_COMMIT" 2>/dev/null | head -20 || \
			git log --oneline -10 "$REMOTE_COMMIT"
		echo "── 涉及的文件 ──"
		git diff --stat "$COMPARE_FROM..$REMOTE_COMMIT" 2>/dev/null | tail -20 || true
	else
		log "已部署 commit 与远端 $BRANCH 一致，无新内容"
	fi
else
	warn "远端没有分支 origin/$BRANCH"
fi

# ──────────── pull ────────────
log "git pull --ff-only"
if [[ $DRY_RUN -eq 0 ]]; then
	if ! git pull --ff-only 2>&1; then
		err "git pull --ff-only 失败——分支可能 force-pushed 或有冲突"
		warn "处理方式：git fetch + 手动检查"
		exit 1
	fi
	TARGET_COMMIT=$(git rev-parse HEAD)
else
	printf '   %s[dry]%s git pull --ff-only\n' "$C_WARN" "$C_END" >&2
fi

# ──────────── 子模块 ────────────
log "submodule update"
run "git submodule update --init --recursive"

# ──────────── auto 检测 rebuild 范围 ────────────
detect_rebuild() {
	local from=$1 to=$2
	if [[ "$from" == "$to" ]]; then
		echo "none"
		return
	fi
	local changed app=0 sidecar=0
	changed=$(git diff --name-only "$from" "$to" 2>/dev/null || true)
	[[ -z "$changed" ]] && { echo "none"; return; }

	# sidecar 改动：voiceya/sidecars/** 或 sidecar Dockerfile
	if echo "$changed" | grep -qE '^voiceya/sidecars/|/visualizer-backend\.Dockerfile$'; then
		sidecar=1
	fi
	# app 改动：除 sidecar / docs / tests / *.md / 部署脚本本身 外，凡涉及代码 / web / lock 都算
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
	REBUILD=$(detect_rebuild "$COMPARE_FROM" "$TARGET_COMMIT")
	log "auto 检测（${COMPARE_FROM:0:8}..${TARGET_COMMIT:0:8}）→ rebuild=$REBUILD"
fi

if [[ "$COMPARE_FROM" == "$TARGET_COMMIT" && "$REBUILD" == "none" ]]; then
	ok "已部署 commit 与目标一致，且无需 rebuild，退出"
	exit 0
fi

log "rebuild 范围：$REBUILD"
confirm "继续部署？" || exit 1

# 记录回滚点（dry-run 不写）
if [[ $DRY_RUN -eq 0 ]]; then
	echo "$COMPARE_FROM" > "$STATE_FILE"
fi

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
		sleep 3; elapsed=$((elapsed+3)); printf '.' >&2
	done; echo >&2
	[[ $elapsed -ge $timeout ]] && { err "app 健康检查超时"; return 1; }

	if [[ -n "$ENGINE_C_FLAG" ]]; then
		log "等 sidecar /healthz..."
		elapsed=0
		while [[ $elapsed -lt $timeout ]]; do
			if docker compose exec -T app python -c "import urllib.request as u; u.urlopen('http://visualizer-backend:8001/healthz', timeout=5)" >/dev/null 2>&1; then
				ok "sidecar healthy"
				break
			fi
			sleep 3; elapsed=$((elapsed+3)); printf '.' >&2
		done; echo >&2
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
echo "    commit:   ${COMPARE_FROM:0:8} → ${TARGET_COMMIT:0:8}"
echo "    rebuild:  $REBUILD"
echo
docker compose $ENGINE_C_FLAG ps
