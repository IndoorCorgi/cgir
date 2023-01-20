"""
Raspberry Pi用 赤外線送受信、データ解析モジュール
Indoor Corgi, https://www.indoorcorgielec.com
GitHub: https://github.com/IndoorCorgi/cgir
"""

import pigpio
import time
import json

# 定数
FORMAT_UNKNOWN = "Unknown"  # フォーマット不明
FORMAT_AEHA = "AEHA"  # AEHAフォーマット
FORMAT_NEC = "NEC"  # NECフォーマット
FORMAT_SONY = "SONY"  # SONYフォーマット

REC_SUCCESS = 0  # 受信成功
REC_NO_DATA = 1  # 受信失敗 データなし, タイムアウト
REC_SHORT = 2  # 受信失敗 データが短いかリピートコード
REC_ERR_PIGPIO = 3  # pigpio接続失敗

_T_MAX_GAP = 60000  # recordでこれ以上間隔が空いたらそれ以降は受信しない[us]
_T_AEHA = 425  # AEHAフォーマットの基準周期[us]
_T_NEC = 560  # NECフォーマットの基準周期[us]
_T_SONY = 600  # SONYフォーマットの基準周期[us]
_T_WAIT = 10000  # encode, decodeで使用するフレーム間の時間[us]


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
    gpio_send: 赤外線LEDのGPIO番号
    gpio_rec: 赤外線受信機のGPIO番号
    codes_path: 登録済みcode一覧を保存するファイル名
    codes: 保存済codeを管理する辞書. コード名がKeyで赤外線データ(code形式)がValue
  """

  def __init__(self, gpio_send=13, gpio_rec=4, codes_path='codes.json'):
    self.gpio_send = gpio_send
    self.gpio_rec = gpio_rec
    self.codes_path = codes_path
    self.codes = {}

  def send(self, code):
    """
    gpio_sendで指定したGPIOから赤外線データを送信

    Args:
      code: 送信する赤外線データ
    
    Returns:
      bool: 成功ならTrue. pigpio接続失敗でFalse. 
    """
    pi = pigpio.pi()
    if not pi.connected:
      return False

    pi.set_mode(self.gpio_send, pigpio.OUTPUT)

    # 生成できる波形の数には制限があるので、codeの長さごとにまとめて節約する
    # 送信する波形IDのリストの長さにも制限があるので、Mark(38kHzパルス)とSpace(待機)を1組とする
    wids = {}  # key:(Mark長さ, Space長さ), value:ID
    send_wids = []  # 送信する波形IDのリスト

    pi.wave_clear()

    for i in range(len(code)):
      if i % 2 != 0:  # MarkとSpaceをセットで処理するので奇数はスキップ
        continue

      if i == len(code) - 1:  # codeの最後のMarkの場合
        mark_length = code[i]
        space_length = 0
      else:  # 通常のMarkの場合
        mark_length = code[i]
        space_length = code[i + 1]

      # 同じ長さのMark, Space波形が無い場合は新しく生成
      if (mark_length, space_length) not in wids:
        pulses = []
        n = mark_length // 26  # 38kHz = 26us周期の繰り返し回数
        for j in range(n):
          pulses.append(pigpio.pulse(1 << self.gpio_send, 0, 8))  # 8us highパルス
          pulses.append(pigpio.pulse(0, 1 << self.gpio_send, 18))  # 18us lowパルス
        if space_length > 0:
          pulses.append(pigpio.pulse(0, 0, space_length))  # Space部
        pi.wave_add_generic(pulses)  # Mark部
        wids[(mark_length, space_length)] = pi.wave_create()
      send_wids.append(wids[(mark_length, space_length)])

    pi.wave_chain(send_wids)
    pi.wave_clear()
    pi.stop()

    return True

  def record(self, timeout=10):
    """
    赤外線を受信してcodeを返す
    REC_SUCCESS: 成功
    REC_NO_DATA: タイムアウト
    REC_SHORT: 信号が短すぎる
    REC_PIGPIO: pigpio接続失敗

    Args:
      timeout: タイムアウトを秒数で指定

    Returns:
      int: 結果. REC_SUCCESS / REC_NO_DATA / REC_SHORT / REC_PIGPIO
      list: 赤外線データ(code)
    """
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
    timeout_count = int(timeout) * 10
    while self._recording:
      time.sleep(0.1)
      i += 1
      if i >= timeout_count:
        self._recording = False  # 受信処理中のフラグ解除
        self._pi.set_watchdog(self.gpio_rec, 0)  # watchdog解除
        self._pi.set_glitch_filter(self.gpio_rec, 0)
        self._pi.stop()
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

  def _round(self, n, m):
    """
    nをm単位で丸め処理を行う

    Args:
      n: 丸める対象の値
      m: 丸める単位
    
    Returns:
      int: 結果
    """
    return (n + m // 2) // m * m

  def _call_back(self, gpio, level, tick):
    """
    受信波形の立ち上がり、立ち下がりエッジで呼ばれるコールバック

    Args:
      gpio: 対象GPIO
      level: Lowなら0, Highなら1
      tick: 時間[us]. 
    """
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

  def encode(self, ir_format, frames):
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

  def decode(self, code):
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

  def _cl(self, length, target, tol=0.35):
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

  def frames2str(self, ir_format, frames):
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
