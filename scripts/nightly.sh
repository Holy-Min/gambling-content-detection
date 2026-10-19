#!/bin/zsh
# launchd 진입점. 저장소로 이동해 야간 루프를 돌리고 로그를 out/launchd.log 에 덧붙인다. 종료 코드는 crawler nightly 의 것을 그대로 돌려준다.
set -u
cd "$(dirname "$0")/.." || exit 2
mkdir -p out
echo "[$(date '+%F %T')] nightly.sh 시작 ($*)" >> out/launchd.log
caffeinate -i .venv/bin/python -m crawler nightly "$@" >> out/launchd.log 2>&1
rc=$?
echo "[$(date '+%F %T')] nightly.sh 종료 rc=$rc" >> out/launchd.log
exit $rc
