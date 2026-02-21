#!/usr/bin/env python3

# 赤外線を受信して内容を表示し, さらに同じものを送信し直すプログラム例

import time
import cgir

# 赤外線送受信、データ解析クラスのインスタンス作成
ir = cgir.Infrared()

# 受信動作
print("赤外線を受信器に向けて送信してください...")

# 赤外線を受信して結果をret, 受信内容をcodeに入れる.
# タイムアウトを秒数で指定. Noneならタイムアウトなし.
ret, code = ir.record(timeout=10)

if (ret == cgir.REC_NO_DATA):
  # 受信できなかった場合
  print("タイムアウト. 赤外線を受信できませんでした. ")
  exit()

elif (ret == cgir.REC_SHORT):
  # 受信した波形が極端に短い場合
  # ノイズを受信したか, 繰り返しを意味するリピートコードの可能性
  print("受信しましたがノイズの可能性があります")
  exit()

elif (ret == cgir.REC_SUCCESS):
  # 受信成功. codeに Mark (38kHzパルス送信), Space (待機)の時間をus単位で記録したリストが格納されている
  print("受信成功")

# コードの内容を表示
print("コード: ")
print(code)

# 受信したコードは赤外線波形であり, 実際のデータは分からないため, デコードして赤外線フォーマットとデータを取得.
# データの形式はinfrared.pyを参照
format, frames = ir.decode(code)

if (format == cgir.FORMAT_AEHA):
  print("フォーマット: AEHA")
  print("データ: ")
  print(frames)
elif (format == cgir.FORMAT_NEC):
  print("フォーマット: NEC")
  print("データ: ")
  print(frames)
elif (format == cgir.FORMAT_SONY):
  print("フォーマット: SONY")
  print("データ: ")
  print(frames)
elif (format == cgir.FORMAT_UNKNOWN):
  print("フォーマット: 不明")

# 本例では受信したコードと同じものを送信する
# encodeメソッドを使えば送りたいデータをcodeに変換して送信することも可能
print("受信した赤外線と同じものを送信します...")
time.sleep(3)  # 3秒開ける
ir.send(code)
print("送信完了")
