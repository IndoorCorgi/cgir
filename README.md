## 概要
Raspberry Piで赤外線送受信、データ解析をするPythonパッケージとコマンドラインツールです。以下のことが可能になります。Raspberry Pi単体では赤外線送受信機能がないので、拡張基板(HAT)や外付け回路が必要です。赤外線は38kHzに対応しています。
- Raspberry Piからエアコン、テレビ、照明などを赤外線で操作
- リモコンで送信した赤外線データを記録する
- 記録した赤外線データを解析し、一部(エアコンの設定温度など)を変更して送信する

他のソフトウェアやセンサーと組み合わせることで、スマホから家電を操作するシステムや、室温が一定以上になったらエアコンを自動で入れる熱中症防止システムなどの応用も可能になります。

## Raspberry Pi OS TrixieおよびRaspberry Pi5対応

cgirバージョン1.4までは赤外線制御にpigpioを使用していました。しかし、Raspberry Pi5ではpigpioが動作しないほか、
2025年10月リリースのRaspberry Pi OS Trixieではpigpio自体がOSに同梱されなくなっていました。

そこで、cgirバージョン2.0でLIRCを使った赤外線制御に刷新しました。
これにより、Raspberry Pi OSが動作するRaspberry Piシリーズ(Raspberry Pi5を含む)において動作可能となりました。

## 動作環境
Raspberry Pi OSの動作しているRaspberry Piと、赤外線送受信機能のある以下の拡張基板の組み合わせを想定しています。GPIO番号を変更することで他の拡張基板、HAT、自作回路でも利用可能です。

- Raspberry Pi用 人感/明るさセンサー/赤外線 拡張基板「[RPZ-PIRS](https://www.indoorcorgielec.com/products/rpz-pirs/)」

- Raspberry Pi用 温度/湿度/気圧/明るさ/赤外線 ホームIoT拡張ボード「[RPZ-IR-Sensor](https://www.indoorcorgielec.com/products/rpz-ir-sensor/)」

- Raspberry Pi用 温度/湿度/気圧/赤外線 ホームIoT拡張ボード「[RPi TPH Monitor](https://www.indoorcorgielec.com/products/rpi-tph-monitor-rev2/)」


## インストール
以下のコマンドでインストール/アップグレードできます。

`sudo python3 -m pip install -U cgir --break-system-packages`

## 前準備
本ソフトウェアはLIRCを利用します。
/boot/firmware/config.txtをスーパーユーザーで開き, 以下の行を追記して再起動します。
1行目で指定している4が受信用のGPIO番号、2行目の13が送信用のGPIO番号です。
Indoor Corgi製以外の拡張基板、自作回路の場合は使用しているGPIO番号に変更してください。

```
dtoverlay=gpio-ir,gpio_pin=4
dtoverlay=gpio-ir-tx,gpio_pin=13
```

再起動後、/dev/lirc0および/dev/lirc1があれば設定できています。
通常lirc0が送信用、lirc1が受信用になります。

## 使い方

### コマンドラインツール
インストールすると、`cgir`コマンドが使用可能になり、ターミナル等から赤外線送受信が可能になります。

コマンドラインツールの使い方は`cgir -h`もしくは[解説記事](https://www.indoorcorgielec.com/resources/raspberry-pi/python-pigpio-infrared)を参照して下さい。

### Pythonパッケージ
pythonスクリプトからは`import cgir`とすることでパッケージの機能を利用できます。使い方の例は[examples](examples)を参照して下さい。

## バージョン1から2へ更新する場合
GPIO番号を変更せずにデフォルトで使用している場合、上記のconfig.txtの編集を行えば、
既存のプログラムやスクリプトは問題なく動作するはずです。

### コマンドラインツールとして利用している場合

GPIO番号はconfig.txtで指定するためcgirコマンドのGPIO指定用-gオプションがなくなりました。
-gオプションを使用していた場合は削除してください。


### Pythonパッケージとして利用している場合

GPIO番号はconfig.txtで指定するためcgir.InfraredクラスGPIO指定用パラメーターgpio_sendおよびgpio_recがなくなりました。
これらを使用していた場合は削除してください。

Infraredクラスのsendメソッドが失敗した場合False, recordメソッドがpigpio操作に失敗した場合は(cgir.REC_ERR_PIGPIO, [])が戻り値になっていましたが、
バージョン2ではLIRC操作に失敗して送受信できなかった場合は例外を発生させるようになりました。
バージョン1用のプログラムで動作しますが、例外を処理したい場合はtry/exceptの追加などを行ってください。
sendメソッドが成功した場合、recordメソッドで赤外線受信した場合とタイムアウトした場合の戻り値に変更はありません。

## 注意事項
赤外線送受信はメーカーや機器によって仕様が異なります。全ての機器での動作を保証するものではありません。
