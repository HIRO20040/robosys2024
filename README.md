# robosys2024
[![test](https://github.com/HIRO20040/robosys2024/actions/workflows/test.yml/badge.svg)](https://github.com/HIRO20040/robosys2024/actions/workflows/test.yml)


## 概要
- 大学の授業で使用



## 必要なソフトウェア
- Python
  - テスト済みバージョン: 3.7~3.10


## インストール方法

`sudo apt install git`

`git clone https://github.com/HIRO20040/robosys2024.git`

`cd robosys2024`



 
## medianコマンド

- サンプルコード
   
   import sys


   x = [float(n) for n in sys.stdin.read().split()]


   x.sort()

   n = len(x)

   if n == 1:
       median = x[0]

   elif n % 2 == 1:
       median = x[n // 2]
   else:
       median = (x[n // 2 - 1] + x[n // 2]) / 2

   print(median)
  
- 実行方法
　
  - 例1：1から5までの数字の中央値を求める場合

  `seq 5 | ./median`
  
  - 例1：1 5 4 6 8　のランダムな順番の数字の並びの中央値を求める場合
　
　
  `echo 1 5 4 6 8 | ./median`

- 出力

 - 例1の場合
　
　 3.0

 - 例2の場合
　
　 5.0

　
　


## テスト環境
- Ubuntu 24.04 LTS













- このソフトウェアパッケージは，3条項BSDライセンスの下，再頒布および使用が許可されます．
- このパッケージのコードは, 下記のスライド(CC-BY-SA 4.0 by Ryuichi Ueda)　のものを, 本人の許可を得て自身の著作としたものです.
　　- [ryuichiueda/my_slides robosys_2024](https://ryuichiueda.github.io/slides_marp/robosys2024) 
- © 2024 Hiroaki Ohmatsu
