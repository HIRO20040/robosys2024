#!/bin/bash -xv
# SPDX-FileCopyrightText: 2024 Hiroaki Ohmatsu
# SPDX-License-Identifier: GPL-3.0-only

ng () {
	echo ${1}行目が違う
	res=1
}

res=0

out=$(echo "6"  | ./kadai1)

exit_code=$?
echo "Python スクリプトの終了コード: $exit_code"

if [ "$exit_code" -eq 1 ]; then
    echo "エラー発生: 正常にエラーが発生しました"
else
    echo "正常終了"
fi

    
out=$(echo "abc" | ./kadai1)

exit_code=$?
echo "Python スクリプトの終了コード: $exit_code"

if [ "$exit_code" -eq 1 ]; then
    echo "エラー発生: 正常にエラーが発生しました"
else
    echo "正常終了"
fi

out=$(echo  | ./kadai1)

exit_code=$?
echo "Python スクリプトの終了コード: $exit_code"

if [ "$exit_code" -eq 1 ]; then
    echo "エラー発生: 正常にエラーが発生しました"
else
    echo "正常終了"
fi

[ "$res" = 0 ] && echo OK
exit $res


