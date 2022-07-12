#!/bin/bash

unalias -a
cd $(dirname $(readlink -f "${BASH_SOURCE:-$0}"))

set -eux -o pipefail +o posix

srcdir=../src
vardir=../var

[[ -f ${vardir}/pyfastcgi.pid ]] || exit 0

kill -TERM $(cat ${vardir}/pyfastcgi.pid)

exit 0
