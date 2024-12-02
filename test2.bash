#!/bin/bash -xv
# SPDX-FileCopyrightText: 2024 Hiroaki Ohmatsu
# SPDX-License-Identifier: BSD-3-Clause

ng () {
	echo ${1}行目が違う
	res=1
}

res=0

out=$(seq 1 5 | ./median)
[ "${out}" = 3.0 ]  || ng "$LINENO"


out=$(echo あ | ./median)
[ "$?" = 1 ]      || ng "$LINENO"
[ "${out}" = "" ] || ng "$LINENO"

out=$(echo | ./median)
[ "$?" = 1 ]      || ng "$LINENO"
[ "${out}" = "" ] || ng "$LINENO"

[ "$res" = 0 ] && echo OK
exit $res


