#!/usr/bin/env python3

# Raspberry Pi用赤外線送受信、データ解析ライブラリ
# Indoor Corgi, https://www.indoorcorgielec.com
# Version 2020/9/3

import pigpio
import time
import json
import os

# 定数
FORMAT_UNKNOWN = "Unknown"  # フォーマット不明
FORMAT_AEHA = "AEHA"  # AEHAフォーマット
FORMAT_NEC = "NEC"  # NECフォーマット
FORMAT_SONY = "SONY"  # SONYフォーマット

REC_SUCCESS = 0  # 受信成功
REC_NO_DATA = 1  # 受信失敗 データなし, タイムアウト
REC_SHORT = 2  # 受信失敗 データが短いかリピートコード
REC_ERR_PIGPIO = 3  # pigpio接続失敗

_T_MAX_GAP = 30000  # recordでこれ以上間隔が空いたらそれ以降は受信しない[us]
_T_AEHA = 425  # AEHAフォーマットの基準周期[us]
_T_NEC = 560  # NECフォーマットの基準周期[us]
_T_SONY = 600  # SONYフォーマットの基準周期[us]
_T_WAIT = 10000  # encode, decodeで使用するフレーム間の時間[us]

# 赤外線の送受信とデータ解析用クラス
#   共通のデータ型
#     code
#       赤外線データを時間で表したもの
#       Mark (38kHzパルス送信), Space (待機)の時間をus単位で記録したリスト
#       [Mark#1, Space#1, Mark#2, Space#2, ... ]
#
#     frames
#       赤外線データをバイト列で表したもの. フレーム数とバイト数は可変.
#       [
#         [Byte#1, Byte#2, Byte#3, ... ] # Frame#1のバイト列
#         [Byte#1, Byte#2, Byte#3, ... ] # Frame#2のバイト列
#         ...
#       ]
#       SONYフォーマットの場合はバイト単位ではなく以下のbit数.
#       [
#         [7bitデータ, 13bitデータ] # Frame#1のデータ
#         ...
#       ]


class Infrared:

  # 初期化
  #   Parameters
  #     gpio_send  : 赤外線LEDのGPIO番号
  #     gpio_rec   : 赤外線受信機のGPIO番号
  #     codes_path : 登録済みcode一覧を保存するファイル名
  def __init__(self, gpio_send=13, gpio_rec=4, codes_path='codes.json'):
    self.gpio_send = gpio_send
    self.gpio_rec = gpio_rec
    self.codes_path = codes_path
    self.codes = {}  # 保存済codeを管理する辞書

  # gpio_sendで指定したGPIOから赤外線データを送信
  #   Return
  #     True  : 成功
  #     False : pigpioに接続失敗
  def send(self, code):
    pi = pigpio.pi()
    if not pi.connected:
      return False

    pi.set_mode(self.gpio_send, pigpio.OUTPUT)

    # 生成できる波形の長さには制限があるので、種類とcodeの長さごとにまとめて節約する
    mark_wids = {}  # Mark(38kHzパルス)波形, key:長さ, value:ID
    space_wids = {}  # Speace(待機)波形, key:長さ, value:ID
    send_wids = [0] * len(code)  # 送信する波形IDのリスト

    pi.wave_clear()

    for i in range(len(code)):
      if i % 2 == 0:
        # 同じ長さのMark波形が無い場合は新しく生成
        if code[i] not in mark_wids:
          pulses = []
          n = code[i] // 26  # 38kHz = 26us周期の繰り返し回数
          for j in range(n):
            pulses.append(pigpio.pulse(1 << self.gpio_send, 0, 8))  # 8us highパルス
            pulses.append(pigpio.pulse(0, 1 << self.gpio_send, 18))  # 18us lowパルス
          pi.wave_add_generic(pulses)
          mark_wids[code[i]] = pi.wave_create()
        send_wids[i] = mark_wids[code[i]]
      else:
        # 同じ長さのSpace波形が無い場合は新しく生成
        if code[i] not in space_wids:
          pi.wave_add_generic([pigpio.pulse(0, 0, code[i])])
          space_wids[code[i]] = pi.wave_create()
        send_wids[i] = space_wids[code[i]]

    pi.wave_chain(send_wids)
    pi.wave_clear()
    pi.stop()

    return True

  # 赤外線を受信してcodeを返す
  #   Return
  #     (result, code)
  #     result : 結果. REC_SUCCESS / REC_NO_DATA / REC_SHORT / REC_PIGPIO
  #     code   : codeデータ
  def record(self):
    self._pi = pigpio.pi()
    if not self._pi.connected:
      return REC_ERR_PIGPIO, []

    self._pi.set_mode(self.gpio_rec, pigpio.INPUT)
    self._pi.set_glitch_filter(self.gpio_rec, 100)
    self._code = []
    self.last_tick = 0

    self._pi.callback(self.gpio_rec, pigpio.EITHER_EDGE, self._call_back)

    self._recording = True  # 受信処理中のフラグセット

    i = 0
    while self._recording:
      time.sleep(0.1)
      i += 1
      if i >= 100:
        return (REC_NO_DATA, [])  # タイムアウト

    self._pi.set_watchdog(self.gpio_rec, 0)  # watchdog解除
    self._pi.set_glitch_filter(self.gpio_rec, 0)
    self._pi.stop()

    # codeが短い場合は戻り値を変える
    if len(self._code) > 10:
      result = REC_SUCCESS
    else:
      result = REC_SHORT

    return (result, self._code)

  # nをm単位で丸め処理を行う
  def _round(self, n, m):
    return (n + m // 2) // m * m

  # 受信波形の立ち上がり、立ち下がりエッジで呼ばれるコールバック
  def _call_back(self, gpio, level, tick):
    # 受信処理中のフラグが解除されている場合
    if not self._recording:
      return

    # エッジを検出した場合
    if level == 0 or level == 1:
      if self.last_tick == 0:
        self._pi.set_watchdog(self.gpio_rec, 100)  # watchdog設定
      else:
        length = pigpio.tickDiff(self.last_tick, tick)

        # 一定以上長い場合は受信終了
        if length > _T_MAX_GAP:
          self._recording = False  # 受信処理中のフラグ解除
          return

        # 長さがばらつくので丸め処理
        if length < 1000:
          length = self._round(length, 10)
        elif length < 2000:
          length = self._round(length, 50)
        else:
          length = self._round(length, 200)

        self._code.append(length)
      self.last_tick = tick

    # Watchdogで呼ばれた場合
    else:
      self._recording = False  # 受信処理中のフラグ解除

  # frames(バイト列データ)とフォーマットからcodeを生成する
  #   Return
  #     code
  #   Parameters
  #     ir_format : フォーマット. FORMAT_で始まる定数
  #     frames    : バイト列データ
  def encode(self, ir_format, frames):
    code = []

    if ir_format == FORMAT_AEHA:
      t = _T_AEHA
    elif ir_format == FORMAT_NEC:
      t = _T_NEC
    elif ir_format == FORMAT_SONY:
      t = _T_SONY
    else:
      return []

    first_frame = True

    for frame in frames:
      try:
        if len(frame) == 0:
          return []
      except:
        return []

      # Wait部
      if not first_frame:
        if ir_format == FORMAT_AEHA:
          code.append(_T_WAIT)
        elif ir_format == FORMAT_NEC:
          code.append(self._round(108000 - t * t_count, 100))
        elif ir_format == FORMAT_SONY:
          code.append(self._round(45000 - t * t_count, 100))

      t_count = 0

      # Leader
      if ir_format == FORMAT_AEHA:
        code.append(t * 8)
        code.append(t * 4)
        t_count += 12
      elif ir_format == FORMAT_NEC:
        code.append(t * 16)
        code.append(t * 8)
        t_count += 24
      elif ir_format == FORMAT_SONY:
        code.append(t * 4)
        t_count += 4
      else:
        return code

      # Data
      if ir_format == FORMAT_AEHA or ir_format == FORMAT_NEC:
        for byte in frame:
          d = byte
          for i in range(8):
            bit = d & 1
            if bit == 0:
              code.append(t)
              code.append(t)
              t_count += 2
            else:
              code.append(t)
              code.append(t * 3)
              t_count += 4
            d = d >> 1
      elif ir_format == FORMAT_SONY:
        d = frame[0] + (frame[1] << 7)
        if frame[1] >= 0x100:
          bits = 20
        elif frame[1] >= 0x20:
          bits = 15
        else:
          bits = 12

        for i in range(bits):
          bit = d & 1
          if bit == 0:
            code.append(t)
            code.append(t)
            t_count += 2
          else:
            code.append(t)
            code.append(t * 2)
            t_count += 3
          d = d >> 1

      # Stop bit
      if ir_format == FORMAT_AEHA or ir_format == FORMAT_NEC:
        code.append(t)

      first_frame = False

    return code

  # codeを解析してフォーマットとframes(バイト列)を返す
  #   対応しているのはAEHA, NECフォーマット
  #   先頭は必ずデータを含むフレームで、リピートコードは不可
  #   Return
  #     (ir_format, frames)
  #     ir_format : フォーマット. FORMAT_で始まる定数
  #     frames    : バイト列データ
  #   Parameters
  #     code : codeデータ
  def decode(self, code):
    ir_format = FORMAT_UNKNOWN

    # codeが短いか偶数の場合はエラーとする
    if len(code) < 10 or len(code) // 2 == 0:
      return FORMAT_UNKNOWN, []

    # Leader
    if self._cl(code[0], _T_AEHA * 8) and self._cl(code[1], _T_AEHA * 4):
      ir_format = FORMAT_AEHA
      t = _T_AEHA
    elif self._cl(code[0], _T_NEC * 16) and self._cl(code[1], _T_NEC * 8):
      ir_format = FORMAT_NEC
      t = _T_NEC
    elif self._cl(code[0], _T_SONY * 4) and self._cl(code[1], _T_SONY):
      ir_format = FORMAT_SONY
      t = _T_SONY
    else:
      return FORMAT_UNKNOWN, []

    frames = []
    byte_list = []
    byte = 0
    bit_counter = 0
    end_of_frame = False

    if ir_format == FORMAT_AEHA or ir_format == FORMAT_NEC:
      for i in range(2, len(code), 2):
        # 新しいフレームの開始
        if end_of_frame:
          # Last index
          if i == len(code) - 1:
            return FORMAT_UNKNOWN, []

          # フォーマットに合ったLeaderか確認
          if ir_format == FORMAT_AEHA:
            # Leader
            if self._cl(code[i], _T_AEHA * 8) and self._cl(code[i + 1], _T_AEHA * 4):
              end_of_frame = False
              continue
            # Repeat
            elif self._cl(code[i], _T_AEHA * 8) and self._cl(code[i + 1], _T_AEHA * 8):
              end_of_frame = False
              continue
            else:
              return FORMAT_UNKNOWN, []
          elif ir_format == FORMAT_NEC:
            # Leader
            if self._cl(code[i], _T_NEC * 16) and self._cl(code[i + 1], _T_NEC * 8):
              end_of_frame = False
              continue
            # Repeat
            elif self._cl(code[i], _T_NEC * 16) and self._cl(code[i + 1], _T_NEC * 4):
              end_of_frame = False
              continue
            else:
              return FORMAT_UNKNOWN, []

        # フレームの途中
        else:
          # Last index
          if i == len(code) - 1:
            # Stopの長さとデータのbit数がByte単位か確認
            if self._cl(code[i], t) and bit_counter == 0:
              frames.append(byte_list)
              return ir_format, frames
            else:
              return FORMAT_UNKNOWN, []

          # Stopの後に長いSpaceがある場合は次のフレームがあると解釈
          if self._cl(code[i], t) and code[i + 1] > _T_WAIT * 0.5:
            frames.append(byte_list)
            byte_list = []
            byte = 0
            end_of_frame = True
            continue

          # Data 0
          if self._cl(code[i], t) and self._cl(code[i + 1], t):
            bit_counter = (bit_counter + 1) % 8
            if bit_counter == 0:
              byte_list.append(byte)
              byte = 0
          # Data 1
          elif self._cl(code[i], t) and self._cl(code[i + 1], t * 3):
            byte = byte + (1 << bit_counter)
            bit_counter = (bit_counter + 1) % 8
            if bit_counter == 0:
              byte_list.append(byte)
              byte = 0

          # 不明なbit
          else:
            return FORMAT_UNKNOWN, []

    elif ir_format == FORMAT_SONY:
      for i in range(1, len(code), 2):
        # 長いSpaceの後にLeaderがある場合は次のフレームと解釈
        if code[i] > _T_WAIT * 0.5 and self._cl(code[i + 1], t * 4) and i <= len(code) - 3:
          byte_list.append(byte & 0x7F)
          byte_list.append(byte >> 7)
          frames.append(byte_list)
          byte_list = []
          byte = 0
          bit_counter = 0
          continue

        # Data 0
        elif self._cl(code[i], t) and self._cl(code[i + 1], t):
          bit_counter += 1
        # Data 1
        elif self._cl(code[i], t) and self._cl(code[i + 1], t * 2):
          byte = byte + (1 << bit_counter)
          bit_counter += 1

        # 不明なbit
        else:
          return FORMAT_UNKNOWN, []

        # 最後のbit
        if i == len(code) - 2:
          if bit_counter == 12 or bit_counter == 15 or bit_counter == 20:
            byte_list.append(byte & 0x7F)
            byte_list.append(byte >> 7)
            frames.append(byte_list)
            return ir_format, frames
          else:
            return FORMAT_UNKNOWN, []

  # Mark, Spaceの長さが目標値+/-許容範囲と一致するか確認する
  #   Return
  #     True  : 一致
  #     False : 不一致
  #   Parameters
  #     length : 長さ
  #     target : 目標値
  #     tol    : 許容範囲の割合
  def _cl(self, length, target, tol=0.35):
    if length > target * (1 - tol) and length < target * (1 + tol):
      return True
    else:
      return False

  # frames(バイト列データ)を文字列に整形する
  #   Return
  #     文字列
  #   Parameters
  #     ir_format : フォーマット. FORMAT_で始まる定数
  #     frames    : バイト列データ
  def frames2str(self, ir_format, frames):
    if ir_format == FORMAT_AEHA:
      s = 'Format AEHA\n'
    elif ir_format == FORMAT_NEC:
      s = 'Format NEC\n'
    elif ir_format == FORMAT_SONY:
      s = 'Format SONY\n'
    else:
      return 'Format Unknown\n'

    first_frame = True
    for i in range(len(frames)):
      if not first_frame:
        s = s + '\n'
      s = s + 'Frame#' + str(i + 1) + ' '
      for j in range(len(frames[i])):
        s = s + '0x{:02X}'.format(frames[i][j])
        if j != len(frames[i]) - 1:
          s = s + ', '

      if len(frames[i]) == 0:
        s = s + 'Repeat\n'

      first_frame = False
    return s

  # 登録済みcode一覧をファイルに保存する
  #   Return
  #     True  : 成功
  #     False : 失敗
  #   Parameters
  #     path : 保存ファイルのパス
  def save_codes(self):
    try:
      with open(self.codes_path, 'w') as f:
        f.write(json.dumps(self.codes, ensure_ascii=False).replace('], ', '],\n'))
      return True
    except:
      return False

  # 登録済みcode一覧をファイルから読み出す
  #   Return
  #     True  : 成功
  #     False : 失敗
  #   Parameters
  #     path : 保存ファイルのパス
  def load_codes(self):
    try:
      with open(self.codes_path, 'r') as f:
        self.codes = json.load(f)
        return True
    except:
      pass
    self.codes = {}
    return False
