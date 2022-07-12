#!/bin/bash

unalias -a
readlink_f(){ perl -MCwd -e 'print Cwd::abs_path shift' "$1";}
cd "$(dirname "$(readlink_f "${BASH_SOURCE:-$0}")")"

set -eux -o pipefail +o posix

[ "${VIRTUAL_ENV}" = "" ] && . ../../.venv/bin/activate

srcdir=../../src
vardir=../../var

[[ -f ${vardir}/pyfastcgi.pid ]] || exit 0

kill -TERM $(cat ${vardir}/pyfastcgi.pid)

exit 0
