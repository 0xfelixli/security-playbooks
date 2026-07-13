#!/usr/bin/env bash
#
# 把本仓的 security-audit playbook 与 code-security skill 部署到 workmate 发现根。
#
#   每个含 PLAYBOOK.md 的目录  ->  $ROOT/.workmate/playbooks/<name>/
#   skills/code-security       ->  $ROOT/.workmate/skills/code-security/
#
# $ROOT 默认 /workspace/workmate（pod）；用环境变量 WORKMATE_SYNCED_ROOT 覆盖。
# 用法：
#   ./deploy.sh              # 部署到默认根
#   ./deploy.sh --dry-run    # 只打印将要同步什么，不落盘
#   WORKMATE_SYNCED_ROOT=/some/root ./deploy.sh
#
set -euo pipefail

ROOT="${WORKMATE_SYNCED_ROOT:-/workspace/workmate}"
PLAYBOOKS_DEST="$ROOT/.workmate/playbooks"
SKILLS_DEST="$ROOT/.workmate/skills"

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# 空数组在 macOS bash 3.2 + set -u 下展开会报 unbound，故用字符串（单 token 无空格，安全）
DRY=""
if [[ "${1:-}" == "--dry-run" || "${1:-}" == "-n" ]]; then
  DRY="--dry-run"
  echo "[dry-run] 不会实际写入"
fi

# 排除版本控制 / 构建 / OS 噪声
EXCLUDES=(--exclude='.git' --exclude='__pycache__' --exclude='.DS_Store' --exclude='*.pyc')

echo "源:   $SRC"
echo "根:   $ROOT"
echo "  playbooks -> $PLAYBOOKS_DEST"
echo "  skills    -> $SKILLS_DEST"
echo

[ -z "$DRY" ] && mkdir -p "$PLAYBOOKS_DEST" "$SKILLS_DEST"

# 1) playbooks：顶层每个含 PLAYBOOK.md 的目录（自动发现，新增 playbook 无需改脚本）
echo "== playbooks =="
count=0
for pb in "$SRC"/*/PLAYBOOK.md; do
  [ -e "$pb" ] || continue
  d="$(dirname "$pb")"
  name="$(basename "$d")"
  rsync -a --delete $DRY "${EXCLUDES[@]}" "$d/" "$PLAYBOOKS_DEST/$name/"
  echo "  ✓ $name"
  count=$((count + 1))
done
echo "  共 $count 个 playbook"

# 2) skill：code-security（含 rules/ guides/ scripts/ SCHEMA-issue.md）
echo "== skill =="
if [ -d "$SRC/skills/code-security" ]; then
  rsync -a --delete $DRY "${EXCLUDES[@]}" \
    "$SRC/skills/code-security/" "$SKILLS_DEST/code-security/"
  echo "  ✓ code-security"
else
  echo "  ✗ 未找到 $SRC/skills/code-security" >&2
  exit 1
fi

echo
echo "完成。"
