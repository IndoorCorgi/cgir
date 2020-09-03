# 概要
Raspberry Piで赤外線送受信、データ解析をするPythonライブラリとコマンドラインツールです。
- cgir.py : pigpioを使って赤外線の送受信、データ解析をするモジュール
- cgirtool.py : 赤外線送受信、データ解析をコマンドラインから使用できるようにしたツール

# 使い方
コマンドラインツールの使い方は`./cgirtool.py -h`もしくは[解説記事](https://www.indoorcorgielec.com/resources/raspberry-pi/python-pigpio-infrared)を参照して下さい。

# 対応ハードウェア
Raspberry Piと赤外線送受信機能のある以下の拡張基板を想定していますが、GPIO番号を変更することで他の拡張基板、HAT、自作回路でも利用可能です。

Raspberry Pi用 温度/湿度/気圧/明るさ/赤外線 ホームIoT拡張ボード「[RPZ-IR-Sensor](https://www.indoorcorgielec.com/products/rpz-ir-sensor/)」

Raspberry Pi用 温度/湿度/気圧/赤外線 ホームIoT拡張ボード「[RPi TPH Monitor](https://www.indoorcorgielec.com/products/rpi-tph-monitor-rev2/)」


# 前準備
## pigpioサービス
`sudo service pigpiod start`

`sudo systemctl enable pigpiod.service`

## docoptモジュール
`sudo pip3 install docopt`



