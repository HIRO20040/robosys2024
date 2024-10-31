#!/bin/bash

ng () {
	echo うん、なるほどね。${1}行目違う！
	res=1
}


res=0
a=山田
[ "$a" = 上田 ] || ng "$LINENO"
[ "$a" = 山田 ] || ng "$LINENO"

exit $res
