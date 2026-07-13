#!/usr/bin/env bash
#
# 把本仓的 security-audit playbook 与 code-security skill 部署到 workmate 发现根。
#
#   每个含 PLAYBOOK.md 的目录  ->  $ROOT/.workmate/playbooks/<name>/
#   skills/code-security       ->  $ROOT/.workmate/skills/code-security/
#
# 对同名目标做"精确镜像"（源里没有的旧残留会被清掉），但不碰目标根下别的
# playbook/skill。$ROOT 默认 /workspace/workmate（pod），用 WORKMATE_SYNCED_ROOT 覆盖。
#
# 用法：
#   ./deploy.sh              # 部署
#   ./deploy.sh --dry-run    # 只打印将同步什么，不落盘
#   WORKMATE_SYNCED_ROOT=/some/root ./deploy.sh
#
# 有 rsync 用 rsync；没有则自动降级到 cp（pod 上常无 rsync）。
# 设 WORKMATE_DEPLOY_NO_RSYNC=1 可强制走 cp 分支。
#
set -euo pipefail

ROOT="${WORKMATE_SYNCED_ROOT:-/workspace/workmate}"
PLAYBOOKS_DEST="$ROOT/.workmate/playbooks"
SKILLS_DEST="$ROOT/.workmate/skills"
SRC="$(dirname "${BASH_SOURCE[0]}")"

DRY=""
if [[ "${1:-}" == "--dry-run" || "${1:-}" == "-n" ]]; then
  DRY="1"
fi

USE_RSYNC=""
if [ -z "${WORKMATE_DEPLOY_NO_RSYNC:-}" ] && command -v rsync >/dev/null 2>&1; then
  USE_RSYNC="1"
fi

# mirror <src_dir> <dest_dir>：让 dest 成为 src 的精确镜像，剔除噪声。
mirror() {
  local s="$1" d="$2"
  if [ -n "$DRY" ]; then
    echo "    [dry] $s/  ->  $d/"
    return
  fi
  if [ -n "$USE_RSYNC" ]; then
    rsync -a --delete \
      --exclude='.git' --exclude='__pycache__' --exclude='.DS_Store' --exclude='*.pyc' \
      "$s/" "$d/"
  else
    rm -rf "$d"
    mkdir -p "$(dirname "$d")"
    cp -R "$s" "$d"
    # 剔除源里可能夹带的噪声
    find "$d" -name '.DS_Store' -delete 2>/dev/null || true
    find "$d" -name '*.pyc' -delete 2>/dev/null || true
    find "$d" -depth -type d -name '__pycache__' -exec rm -rf {} + 2>/dev/null || true
  fi
}

echo "源:   $SRC"
echo "根:   $ROOT  (rsync=${USE_RSYNC:-no}${DRY:+, dry-run})"
echo "  playbooks -> $PLAYBOOKS_DEST"
echo "  skills    -> $SKILLS_DEST"
echo

[ -z "$DRY" ] && mkdir -p "$PLAYBOOKS_DEST" "$SKILLS_DEST"

# 1) playbooks：顶层每个含 PLAYBOOK.md 的目录（自动发现，新增无需改脚本）
echo "== playbooks =="
count=0
for pb in "$SRC"/*/PLAYBOOK.md; do
  [ -e "$pb" ] || continue
  d="$(dirname "$pb")"
  name="$(basename "$d")"
  mirror "$d" "$PLAYBOOKS_DEST/$name"
  echo "  ✓ $name"
  count=$((count + 1))
done
echo "  共 $count 个 playbook"

# 2) skill：code-security（含 rules/ guides/ scripts/ SCHEMA-issue.md）
echo "== skill =="
if [ -d "$SRC/skills/code-security" ]; then
  mirror "$SRC/skills/code-security" "$SKILLS_DEST/code-security"
  echo "  ✓ code-security"
else
  echo "  ✗ 未找到 $SRC/skills/code-security" >&2
  exit 1
fi

echo
echo "完成。"
