#!/bin/bash

unalias -a
cd $(dirname $(readlink -f "${BASH_SOURCE:-$0}"))

set -eux -o pipefail +o posix

srcdir=../src
vardir=../var

[[ -d $vardir ]] || mkdir -p ${vardir}

export PYTHONPATH="${srcdir}/lib"
export PYTHONDONTWRITEBYTECODE=1

python ${srcdir}/prefork.py --chdir=${srcdir} --app-path=buffering1.py --pid-path=${vardir}/pyfastcgi.pid "$@"

exit 0
