#!/bin/bash -xv
# SPDX-FileCopyrightText: 2024 Hiroaki Ohmatsu 　　　　　
# SPDX-License-Identifier: BSD-3-Clause

ng () {
	echo ${1}行目違う！
	res=1
}


res=0

out=$(seq 5 | ./plus)
++ seq 5
++ ./plus
+ out=15
[ "${out}" = 15.0 ] || ng "$LINENO"
+ '['15 = 15 ' ]'

out=$(echo あ | ./plus)
[ "$?" = 1 ]        || ng "$LINENO"
[ "${out}" = "" ]   || ng "$LINENO"

out=$(echo | ./plus)
[ "$?" = 1 ]        || ng "$LINENO"
[ "${out}" = "" ]   || ng "$LINENO"

[ "${res}" = 0 ] && echo OK 
+ '[' 0 = 0 ']'
+ echo OK
OK
exit $res
+ exit 0
