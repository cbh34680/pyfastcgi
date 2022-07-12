#!/bin/bash

unalias -a
readlink_f(){ perl -MCwd -e 'print Cwd::abs_path shift' "$1";}
cd "$(dirname "$(readlink_f "${BASH_SOURCE:-$0}")")"

set -eux -o pipefail +o posix

srcdir=../../src
vardir=../../var

[[ -d $vardir ]] || mkdir -p ${vardir}

export PYTHONPATH="${srcdir}/lib"
export PYTHONDONTWRITEBYTECODE=1

python ${srcdir}/prefork.py --chdir=${srcdir} --app-path=simple.py --pid-path=../var/pyfastcgi.pid "$@"

exit 0
