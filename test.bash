#!/bin/bash
# SPDX-FileCopyrightText: 2024 Hiroaki Ohmatsu 　　　　　
# SPDX-License-Identifier: GPL-3.0-only

ng () {
	echo ${1}行目違う！
	res=1
}


res=0

out=$(seq 5 | ./plus)
[ "${out}" = 15.0 ] || ng "$LINENO"

[ "${res}" = 0 ] && echo OK 
exit $res
