#!/bin/bash

unalias -a
cd $(dirname $(readlink -f "${BASH_SOURCE:-$0}"))

set -eu -o pipefail +o posix

ps -ef | fgrep 'prefork.py' | fgrep -v grep

exit 0
