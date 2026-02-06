"""
Copyright (c) 2020 Indoor Corgi
SPDX-License-Identifier: Apache-2.0
"""

import fcntl
import json
import select

# 定数
FORMAT_UNKNOWN = "Unknown"  # フォーマット不明
FORMAT_AEHA = "AEHA"  # AEHAフォーマット
FORMAT_NEC = "NEC"  # NECフォーマット
FORMAT_SONY = "SONY"  # SONYフォーマット

REC_SUCCESS = 0  # 受信成功
REC_NO_DATA = 1  # 受信失敗 データなし, タイムアウト
REC_SHORT = 2  # 受信失敗 データが短いかリピートコード

_T_AEHA = 425  # AEHAフォーマットの基準周期[us]
_T_NEC = 560  # NECフォーマットの基準周期[us]
_T_SONY = 600  # SONYフォーマットの基準周期[us]
_T_WAIT = 10000  # encode, decodeで使用するフレーム間の時間[us]

LIRC_MODE_RAW = 0x00000001
LIRC_MODE_PULSE = 0x00000002
LIRC_MODE_MODE2 = 0x00000004
LIRC_MODE_SCANCODE = 0x00000008
LIRC_MODE_LIRCCODE = 0x00000010


class Infrared:
  """
  赤外線の送受信とデータ解析用クラス
  
  共通のデータ型
    code
      赤外線データを時間で表したもの
      Mark (38kHzパルス送信), Space (待機)の時間をus単位で記録したリスト
      [Mark#1, Space#1, Mark#2, Space#2, ... ]

    frames
      赤外線データをバイト列で表したもの. フレーム数とバイト数は可変.
      [
        [Byte#1, Byte#2, Byte#3, ... ] # Frame#1のバイト列
        [Byte#1, Byte#2, Byte#3, ... ] # Frame#2のバイト列
        ...
      ]
      SONYフォーマットの場合はバイト単位ではなく以下のbit数.
      [
        [7bitデータ, 13bitデータ] # Frame#1のデータ
        ...
      ]
  
  Attributes:
    dev_send: 赤外線LEDのデバイスファイル. 例:/dev/lirc0
    dev_rec: 赤外線受信機のデバイスファイル. 例:/dev/lirc1
    codes_path: 登録済みcode一覧を保存するファイル名
    codes: 保存済codeを管理する辞書. コード名がKeyで赤外線データ(code形式)がValue
    rec_max_gap_us: 受信時, これ以上間隔が空いたら受信終了[us]
  """

  def __init__(self,
               dev_send='/dev/lirc0',
               dev_rec='/dev/lirc1',
               codes_path='codes.json',
               rec_max_gap_us=60000):
    self.dev_send = dev_send
    self.dev_rec = dev_rec
    self.codes_path = codes_path
    self.codes = {}
    self.rec_max_gap_us = rec_max_gap_us

  def send(self, code):
    """
    dev_sendで指定したデバイスから赤外線データを送信

    Args:
      code: 送信する赤外線データ
    
    Retunrs:
      bool: 成功ならTrue. 問題発生時は例外. Falseは返さないが互換性のため戻り値を残している
    """
    with open(self.dev_send, 'wb') as fd:
      features = self.lirc_get_features(fd)
      if not self.lirc_can_send_pulse(features):
        raise Exception('LIRC send device do not support pulse mode')
      self.lirc_set_send_carrier(fd, 38000)
      self.lirc_set_send_mode(fd, LIRC_MODE_PULSE)
      lirc_data = self.code2lirc_data(code)
      fd.write(lirc_data)

    return True

  def record(self, timeout=10):
    """
    赤外線を受信してcodeを返す
    REC_SUCCESS: 成功
    REC_NO_DATA: タイムアウト
    REC_SHORT: 信号が短すぎる

    Args:
      timeout: タイムアウトを秒数で指定

    Returns:
      int: 結果. REC_SUCCESS / REC_NO_DATA / REC_SHORT / REC_LIRC
      list: 赤外線データ(code)
    """
    with open(self.dev_rec, 'rb') as fd:
      features = self.lirc_get_features(fd)
      if not self.lirc_can_rec_mode2(features):
        raise Exception('LIRC receive device do not support mode2 mode')
      if not self.lirc_can_set_timeout(features):
        raise Exception('LIRC receive device do not support timeout')
      self.lirc_set_rec_timeout(fd, self.rec_max_gap_us)
      self.lirc_set_rec_mode(fd, LIRC_MODE_MODE2)

      code = []  # 受信したデータを格納

      # 受信データをLIRCドライバーから読み出すループ
      while True:
        ready = select.select([fd], [], [], timeout)
        if ready[0]:
          buf = fd.read(4)
          packet = buf[3]  # 上位8bitがパケットタイプ
          data = buf[0] | (buf[1] << 8) | (buf[2] << 16)  # 下位24bitがデータ

          if (packet == 0):
            # スペース
            if len(code) % 2 == 1:
              code.append(data)
          elif (packet == 1):
            # パルス
            if len(code) % 2 == 0:
              code.append(data)
          elif (packet == 3):
            # 間隔が空いて受信終了
            break
        else:
          return REC_NO_DATA, []

    # codeが短い場合は戻り値を変える
    if len(code) > 10:
      result = REC_SUCCESS
    else:
      result = REC_SHORT

    return (result, code)

  @classmethod
  def _round(cls, n, m):
    """
    nをm単位で丸め処理を行う

    Args:
      n: 丸める対象の値
      m: 丸める単位
    
    Returns:
      int: 結果
    """
    return (n + m // 2) // m * m

  @classmethod
  def encode(cls, ir_format, frames):
    """
    バイト列データ(frames)とフォーマットから赤外線データ(code)を生成する

    Args:
      ir_format: フォーマット. FORMAT_で始まる定数
      frames: バイト列データ
    
    Returns:
      list: 赤外線データ(code)

    Raises:
      ValueError: ir_formatの値が不明
    """
    code = []

    if ir_format == FORMAT_AEHA:
      t = _T_AEHA
    elif ir_format == FORMAT_NEC:
      t = _T_NEC
    elif ir_format == FORMAT_SONY:
      t = _T_SONY
    else:
      raise ValueError(ir_format)

    first_frame = True

    for frame in frames:
      # Wait部
      if not first_frame:
        if ir_format == FORMAT_AEHA:
          code.append(_T_WAIT)
        elif ir_format == FORMAT_NEC:
          code.append(cls._round(108000 - t * t_count, 100))
        elif ir_format == FORMAT_SONY:
          code.append(cls._round(45000 - t * t_count, 100))

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

  @classmethod
  def decode(cls, code):
    """
    赤外線データ(code)を解析してフォーマットとバイト列(frames)を返す
    対応しているのはAEHA, NEC, SONYフォーマット. 
    先頭は必ずデータを含むフレームで、リピートコードは不可. 

    Args:
      code: 赤外線データ
    
    Returns:
      int: フォーマット. FORMAT_で始まる定数
      list: バイト列データ(frames)
    """
    ir_format = FORMAT_UNKNOWN

    # codeが短いか偶数の場合はエラーとする
    if len(code) < 10 or len(code) // 2 == 0:
      return FORMAT_UNKNOWN, []

    # Leader
    if cls._cl(code[0], _T_AEHA * 8) and cls._cl(code[1], _T_AEHA * 4):
      ir_format = FORMAT_AEHA
      t = _T_AEHA
    elif cls._cl(code[0], _T_NEC * 16) and cls._cl(code[1], _T_NEC * 8):
      ir_format = FORMAT_NEC
      t = _T_NEC
    elif cls._cl(code[0], _T_SONY * 4) and cls._cl(code[1], _T_SONY):
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
            if cls._cl(code[i], _T_AEHA * 8) and cls._cl(code[i + 1], _T_AEHA * 4):
              end_of_frame = False
              continue
            # Repeat
            elif cls._cl(code[i], _T_AEHA * 8) and cls._cl(code[i + 1], _T_AEHA * 8):
              end_of_frame = False
              continue
            else:
              return FORMAT_UNKNOWN, []
          elif ir_format == FORMAT_NEC:
            # Leader
            if cls._cl(code[i], _T_NEC * 16) and cls._cl(code[i + 1], _T_NEC * 8):
              end_of_frame = False
              continue
            # Repeat
            elif cls._cl(code[i], _T_NEC * 16) and cls._cl(code[i + 1], _T_NEC * 4):
              end_of_frame = False
              continue
            else:
              return FORMAT_UNKNOWN, []

        # フレームの途中
        else:
          # Last index
          if i == len(code) - 1:
            # Stopの長さとデータのbit数がByte単位か確認
            if cls._cl(code[i], t) and bit_counter == 0:
              frames.append(byte_list)
              return ir_format, frames
            else:
              return FORMAT_UNKNOWN, []

          # Stopの後に長いSpaceがある場合は次のフレームがあると解釈
          if cls._cl(code[i], t) and code[i + 1] > _T_WAIT * 0.5:
            frames.append(byte_list)
            byte_list = []
            byte = 0
            end_of_frame = True
            continue

          # Data 0
          if cls._cl(code[i], t) and cls._cl(code[i + 1], t):
            bit_counter = (bit_counter + 1) % 8
            if bit_counter == 0:
              byte_list.append(byte)
              byte = 0
          # Data 1
          elif cls._cl(code[i], t) and cls._cl(code[i + 1], t * 3):
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
        if code[i] > _T_WAIT * 0.5 and cls._cl(code[i + 1], t * 4) and i <= len(code) - 3:
          byte_list.append(byte & 0x7F)
          byte_list.append(byte >> 7)
          frames.append(byte_list)
          byte_list = []
          byte = 0
          bit_counter = 0
          continue

        # Data 0
        elif cls._cl(code[i], t) and cls._cl(code[i + 1], t):
          bit_counter += 1
        # Data 1
        elif cls._cl(code[i], t) and cls._cl(code[i + 1], t * 2):
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

  @classmethod
  def _cl(cls, length, target, tol=0.35):
    """
    赤外線のMark, Spaceの長さが目標値+/-許容範囲と一致するか確認する

    Args:
      length: 実測長さ
      target: フォーマットなどで決まっている目標値
      tol: 許容範囲の割合. 0.35なら+/-35%まで許容. 
    
    Returns:
      bool: 範囲内に一致したらTrue. それ以外はFalse
    """
    if length > target * (1 - tol) and length < target * (1 + tol):
      return True
    else:
      return False

  @classmethod
  def frames2str(cls, ir_format, frames):
    """
    バイト列データ(frames)を文字列に整形する

    Args:
      ir_format: フォーマット. FORMAT_で始まる定数
      frames: バイト列データ
    
    Returns:
      str: 整形した文字列
    """
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

  def save_codes(self):
    """
    登録済みcode一覧(codes)をファイルcodes_pathに保存する

    Returns:
      bool: 成功ならTrue. 失敗ならFalse. 
    """
    try:
      with open(self.codes_path, 'w') as f:
        f.write(json.dumps(self.codes, ensure_ascii=False).replace('], ', '],\n'))
      return True
    except:
      return False

  def load_codes(self):
    """
    登録済みcode一覧をファイルから読み出してcodesに入れる

    Returns:
      bool: 成功ならTrue. 失敗ならFalse. 
    """
    try:
      with open(self.codes_path, 'r') as f:
        self.codes = json.load(f)
        return True
    except:
      pass
    self.codes = {}
    return False

  @classmethod
  def lirc_read(cls, fd, command):
    """
    lircドライバーから読み出す
    
    Args:
      fd: デバイスファイル/dev/lircXをopenしたstream
      command: コマンド
    
    Returns:
      int: 読み出した値 32bit

    ioctlフォーマット
      bit
      31-30: 読み出し0b10
      29-16: バイト数. 4. 
      15-8: 0x69
        7-0: コマンド
    """
    buf = bytearray(4)
    write_data = (0b10 << 30) | (4 << 16) | (0x69 << 8) | command
    fcntl.ioctl(fd, write_data, buf)
    return buf[0] | (buf[1] << 8) | (buf[2] << 16) | (buf[3] << 24)

  @classmethod
  def lirc_write(cls, fd, command, data):
    """
    lircドライバーに書き込む
    
    Args:
      fd: デバイスファイル/dev/lircXをopenしたstream
      command: コマンド
      data: データ. 32bit整数. 

    ioctlフォーマット
      bit
      31-30: 書き込み0b01
      29-16: バイト数. 4. 
      15-8: 0x69
        7-0: コマンド
    """
    buf = bytearray([data & 0xFF, (data >> 8) & 0xFF, (data >> 16) & 0xFF, (data >> 24) & 0xFF])
    write_data = (0b01 << 30) | (4 << 16) | (0x69 << 8) | command
    fcntl.ioctl(fd, write_data, buf)

  @classmethod
  def lirc_get_features(cls, fd):
    """
    lircのサポートしている機能一覧を示す値を取得
    
    Args:
      fd: デバイスファイル/dev/lircXをopenしたstream
    
    Returns:
      int: 機能一覧を示す値featuresの値
    """
    return cls.lirc_read(fd, 0)

  @classmethod
  def lirc_can_send_pulse(cls, features):
    """
    lirc送信機でPULSEモードをサポートしているか確認
    
    Args:
      features: lirc_get_featuresで取得した値
    
    Returns:
      bool: サポートしていればTrue
    """
    if 0 == (features & (0x00000002)):
      return False

    return True

  @classmethod
  def lirc_can_rec_mode2(cls, features):
    """
    lirc受信機でMODE2モードをサポートしているか確認
    
    Args:
      features: lirc_get_featuresで取得した値
    
    Returns:
      bool: サポートしていればTrue
    """
    if 0 == (features & (0x00000004 << 16)):
      return False

    return True

  @classmethod
  def lirc_can_set_timeout(cls, features):
    """
    lirc受信機でタイムアウト設定をサポートしているか確認
    
    Args:
      features: lirc_get_featuresで取得した値
    
    Returns:
      bool: サポートしていればTrue
    """
    if 0 == (features & 0x10000000):
      return False

    return True

  @classmethod
  def lirc_set_send_mode(cls, fd, mode):
    """
    lirc送信機のモードを設定
    
    Args:
      fd: デバイスファイル/dev/lircXをopenしたstream
      mode: LIRC_MODE_で始まる定数
    """
    cls.lirc_write(fd, 0x11, mode)

  @classmethod
  def lirc_set_send_carrier(cls, fd, freq):
    """
    lirc送信機のキャリア周波数を設定
    
    Args:
      fd: デバイスファイル/dev/lircXをopenしたstream
      freq: キャリア周波数[Hz]
    """
    cls.lirc_write(fd, 0x13, freq)

  @classmethod
  def lirc_set_rec_mode(cls, fd, mode):
    """
    lirc受信機のモードを設定
    
    Args:
      fd: デバイスファイル/dev/lircXをopenしたstream
      mode: LIRC_MODE_で始まる定数
    """
    cls.lirc_write(fd, 0x12, mode)

  @classmethod
  def lirc_set_rec_timeout(cls, fd, timeout):
    """
    lirc受信機のタイムアウト(これ以上の時間受信データがなければ受信終了)を設定
    
    Args:
      fd: デバイスファイル/dev/lircXをopenしたstream
      freq: タイムアウト[us]
    """
    cls.lirc_write(fd, 0x18, timeout)

  @classmethod
  def code2lirc_data(cls, code):
    """
    codeをlircドライバー書き込み用のbytearray形式に変換

    Args:
      code: 赤外線データ

    Returns:
      bytearray: lirc用bytearray形式の赤外線データ
    """
    a = bytearray()

    for item in code:
      a.append(item & 0xFF)
      a.append((item >> 8) & 0xFF)
      a.append((item >> 16) & 0xFF)
      a.append((item >> 24) & 0xFF)

    return a
