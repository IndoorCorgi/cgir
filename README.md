## 概要
Raspberry Piで赤外線送受信、データ解析をするPythonパッケージとコマンドラインツールです。以下のことが可能になります。Raspberry Pi単体では赤外線送受信機能がないので、拡張基板(HAT)や外付け回路が必要です。赤外線は38kHzに対応しています。
- Raspberry Piからエアコン、テレビ、照明などを赤外線で操作
- リモコンで送信した赤外線データを記録する
- 記録した赤外線データを解析し、一部(エアコンの設定温度など)を変更して送信する

他のソフトウェアやセンサーと組み合わせることで、スマホから家電を操作するシステムや、室温が一定以上になったらエアコンを自動で入れる熱中症防止システムなどの応用も可能になります。

## 以前のバージョンからの変更点
以前はモジュールcgir.pyとツールcgirtool.pyを単体で配布していましたが、手動でモジュールを配置したりパスを通する必要がありました。

そこで、pipを使ってインストールできるようにパッケージ化しました。これによりインストールが簡単になったほか、`cgir`コマンドや`import cgir`によりパスを気にすることなく利用できるようになりました。

パッケージ化に伴いファイルの構成が変わっていますが、使用方法は変わりません。以前のバージョンはv2020_903タグを参照して下さい。

## 動作環境
Raspberry Pi OSの動作しているRaspberry Piと、赤外線送受信機能のある以下の拡張基板の組み合わせを想定しています。GPIO番号を変更することで他の拡張基板、HAT、自作回路でも利用可能です。

- Raspberry Pi用 温度/湿度/気圧/明るさ/赤外線 ホームIoT拡張ボード「[RPZ-IR-Sensor](https://www.indoorcorgielec.com/products/rpz-ir-sensor/)」

- Raspberry Pi用 温度/湿度/気圧/赤外線 ホームIoT拡張ボード「[RPi TPH Monitor](https://www.indoorcorgielec.com/products/rpi-tph-monitor-rev2/)」

### 動作確認済Raspberry Pi
- Raspberry Pi 4 Model B
- Raspberry Pi 3 Model B/B+
- Raspberry Pi Zero W/WH
- Raspberry Pi Zero

### 必要なソフトウェア
- Raspberry Pi OS
- Python3
- pigpioサービス

## インストール
以下のコマンドでインストール/アップグレードできます。

`sudo python3 -m pip install -U cgir`

## 前準備
本ソフトウェアはpigpioサービスを利用します。
サービスを開始するには以下のコマンドを実行します。

`sudo systemctl start pigpiod`

Raspberry Pi起動時に自動的にpigpioを開始するには、以下のコマンドを実行します。

`sudo systemctl enable pigpiod`

## 使い方

### コマンドラインツール
インストールすると、`cgir`コマンドが使用可能になり、ターミナル等から赤外線送受信が可能になります。

コマンドラインツールの使い方は`cgir -h`もしくは[解説記事](https://www.indoorcorgielec.com/resources/raspberry-pi/python-pigpio-infrared)を参照して下さい。

### Pythonパッケージ
python3のスクリプトからは`import cgir`とすることでパッケージの機能を利用できます。使い方の詳細はソースコードを参照して下さい。

### 送信しても機器が反応しない場合
一部環境で、pigpioのクロックソースがPCMの場合、意図した周波数にならず送信に失敗(機器が反応しない)する現象を確認しています。その場合は以下をお試しください。

スーパーユーザーで /lib/systemd/system/pigpiod.service ファイルを開き、ExecStart行の最後に「-t 0」を追加します。編集後にRasbperry Piを再起動します。

`ExecStart=/usr/bin/pigpio -l -t 0`

## 注意事項
赤外線送受信はメーカーや機器によって仕様が異なります。全ての機器での動作を保証するものではありません。
