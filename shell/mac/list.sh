#!/bin/bash

unalias -a
readlink_f(){ perl -MCwd -e 'print Cwd::abs_path shift' "$1";}
cd "$(dirname "$(readlink_f "${BASH_SOURCE:-$0}")")"

set -eu -o pipefail +o posix

ps -ef | fgrep 'prefork.py' | fgrep -v grep

exit 0
