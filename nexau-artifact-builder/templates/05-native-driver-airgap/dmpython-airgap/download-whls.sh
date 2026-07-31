#!/usr/bin/env bash
# 从 PyPI 下载 dmpython 2.5.32 的两种 manylinux wheel:
#   - manylinux2014_x86_64  (生产 NAC / 大部分 CI runner)
#   - manylinux2014_aarch64 (ARM Linux / 鲲鹏服务器)
#
# `nexau.json` 里的 setup 命令 `uv pip install --no-index --find-links`
# 会按当前 pod 架构自动挑对应的 whl,所以两份都得有。
#
# 用法: bash download-whls.sh

set -euo pipefail
cd "$(dirname "$0")"

VERSION=2.5.32
PY=cp312

if ! command -v python3 >/dev/null 2>&1; then
  echo "[ERROR] 没有 python3。先装 Python 3.8+(任意版本都行,只用来跑 pip download)" >&2
  exit 1
fi

for ARCH in x86_64 aarch64; do
  WHL="dmpython-${VERSION}-${PY}-${PY}-manylinux2014_${ARCH}.manylinux_2_17_${ARCH}.whl"
  if [[ -f "$WHL" ]]; then
    echo "[SKIP] $WHL 已存在"
    continue
  fi
  echo "[DOWNLOAD] $WHL"
  python3 -m pip download "dmpython==${VERSION}" \
    --python-version 3.12 \
    --platform "manylinux2014_${ARCH}" \
    --platform "manylinux_2_17_${ARCH}" \
    --only-binary=:all: \
    --no-deps \
    -d . >/dev/null
done

echo
echo "[DONE] 当前目录:"
ls -lh dmpython-*.whl
