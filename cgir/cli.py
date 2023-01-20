"""
Raspberry Pi用赤外線送受信、データ解析ツール
Indoor Corgi, https://www.indoorcorgielec.com
GitHub: https://github.com/IndoorCorgi/cgir
Version 1.2

必要環境:
1) Raspberry Pi OS, Python3
2) pigpioサービス
  sudo systemctl start pigpiod
  sudo systemctl enable pigpiod
3) 赤外線送受信に対応した拡張基板
  RPZ-PIRS https://www.indoorcorgielec.com/products/rpz-pirs/
  RPZ-IR-Sensor https://www.indoorcorgielec.com/products/rpz-ir-sensor/
  RPi TPH Monitor https://www.indoorcorgielec.com/products/rpi-tph-monitor-rev2/

Usage:
  cgir rec  [-c <path>] [-g <gpio>] <code_name>...
  cgir send [-c <path>] [-g <gpio>] [-w <wait>] <code_name>...
  cgir list [-c <path>] 
  cgir del  [-c <path>] <code_name>...
  cgir dec  [-c <path>] -f <file> <code_name>
  cgir enc  [-c <path>] -f <file> <code_name>
  cgir -h --help

Options:
  rec          赤外線を受信してコードを<code_name>という名前で保存. 
  send         保存したコードの中から, <code_name>で指定した名前の赤外線コードを送信. 
  list         保存した赤外線コード一覧を表示. 
  del          保存したコードの中から, <code_name>で指定した名前の赤外線コードを削除. 
  dec          保存したコードの中から, 赤外線コードを解析して, フォーマットとデータに変換して<file>ファイル(json形式)に保存. 
  enc          フォーマットとデータの<file>ファイル(json形式)から赤外線コードを生成して<code_name>という名前で保存. 
  <code_name>  赤外線コードの名前. rec, send, delでは複数指定可能. 
  -c <path>    登録済み赤外線コードを保存, 読み出すファイル名かパス. デフォルトはcodes.json
  -g <gpio>    送受信に使うGPIO番号. デフォルトは送信13, 受信4. 
  -w <wait>    複数のコードを送信する場合の間隔を秒数で指定. デフォルトは1. 
  -f <file>    ファイル名. 
  -h --help    ヘルプを表示
"""

from docopt import docopt
import time
import json
from .infrared import *


def cli():
  """
  コマンドラインツールを実行
  """
  args = docopt(__doc__)
  ir = Infrared()

  # 登録済み赤外線コードを読み出す
  if args['-c'] != None:
    ir.codes_path = args['-c']
  ir.load_codes()

  # 赤外線受信
  if args['rec']:
    # GPIO設定
    if args['-g'] != None:
      i = check_gpio(args['-g'])
      if -1 == i:
        print('-gで指定したGPIO番号の指定が正しくないか, 範囲外です.')
        return
      else:
        ir.gpio_rec = i

    for cname in args['<code_name>']:
      print('------------------------------------')
      print('赤外線コード"{}"を受信中...  受信機に向けて赤外線を送信して下さい.'.format(cname))
      result, code = ir.record()  # 受信開始
      if result == REC_SUCCESS:
        print('\n受信コード')
        print(code)  # 受信コードを表示

        ir_format, frames = ir.decode(code)
        print()
        print(ir.frames2str(ir_format, frames))  # デコードした結果を表示

        ir.codes[cname] = code
        if ir.save_codes():
          print('\n赤外線コード "{}" を登録しました.\n'.format(cname))
        else:
          print('\n赤外線コードの登録に失敗しました. {}のアクセス権を確認してください.'.format(ir.codes_path))
      elif result == REC_NO_DATA:
        print('受信失敗. データなし.\n')
      elif result == REC_SHORT:
        print('受信失敗. データ異常.\n')
      elif result == REC_ERR_PIGPIO:
        print('受信失敗. pigpioに接続できません.\n')
        return

  # 赤外線送信
  if args['send']:
    # GPIO設定
    if args['-g'] != None:
      i = check_gpio(args['-g'])
      if -1 == i:
        print('-gで指定したGPIO番号の指定が正しくないか, 範囲外です.')
        return
      else:
        ir.gpio_send = i

    # Wait
    wait = 1
    if args['-w'] != None:
      if args['-w'].isdecimal():
        wait = int(args['-w'])
        if wait < 0 or wait > 1000:
          print('-wで指定した秒数の範囲が正しくありません.')
          return
      else:
        print('-wで指定した秒数の指定が正しくありません.')
        return

    first_time = True
    for cname in args['<code_name>']:
      if not first_time:
        time.sleep(wait)
      if cname in ir.codes:
        print('赤外線コード "{}" を送信中...'.format(cname))
        if not ir.send(ir.codes[cname]):
          print('送信失敗. pigpioに接続できません.\n')
          return
      else:
        print('赤外線コード "{}" が見つかりません.'.format(cname))
      first_time = False

  # 登録済みコード一覧表示
  if args['list']:
    if len(ir.codes) == 0:
      print('登録済赤外線コードはありません.')
    else:
      print('登録済赤外線コード')
      for key in ir.codes:
        print(key)

  # 指定コードを削除
  if args['del']:
    for cname in args['<code_name>']:
      if cname in ir.codes:
        print('赤外線コード "{}" を削除しました.'.format(cname))
        ir.codes.pop(cname)
        ir.save_codes()
      else:
        print('赤外線コード "{}" が見つかりません.'.format(cname))

  # デコード
  if args['dec']:
    cname = args['<code_name>'][0]
    if cname not in ir.codes:
      print('赤外線コード "{}" が見つかりません.'.format(cname))
      return

    print('赤外線コード "{}" をデコード\n'.format(cname))
    code = ir.codes[cname]

    print('コード')
    print(code)
    print()
    ir_format, frames = ir.decode(code)
    print(ir.frames2str(ir_format, frames))  # デコードした結果を表示

    if ir_format == FORMAT_UNKNOWN:
      print('フォーマットが未対応か不明です. ファイルに記録せずに終了します. ')
      return

    # ファイルに保存する形式にする
    obj = {}
    obj['format'] = ir_format
    obj['data'] = frames

    try:
      with open(args['-f'], 'w') as f:
        f.write(json.dumps(obj, indent=2, ensure_ascii=False))
        print('\nファイル "{}" へ保存しました.'.format(args['-f']))
    except:
      print('\nファイルへ保存に失敗しました.')

  # エンコード
  if args['enc']:
    try:
      with open(args['-f'], 'r') as f:
        obj = json.load(f)
    except:
      print('\nファイル "{}" の読み出しに失敗しました.'.format(args['-f']))
      return

    # フォーマットとデータがあるか確認
    if not ('format' in obj and 'data' in obj):
      print('\nファイル "{}" にフォーマットとデータがみつかりません.'.format(args['-f']))
      return

    if obj['format'] != FORMAT_AEHA and obj['format'] != FORMAT_NEC and obj['format'] != FORMAT_SONY:
      print('フォーマットが未対応か不明です.')
      return

    code = ir.encode(obj['format'], obj['data'])
    if len(code) == 0:
      print('エンコードに失敗しました.')
      return

    print('ファイル "{}" をエンコード\n'.format(args['-f']))
    print(code)
    cname = args['<code_name>'][0]

    ir.codes[cname] = code
    if ir.save_codes():
      print('\n赤外線コード "{}" を登録しました.\n'.format(cname))
    else:
      print('\n赤外線コードの登録に失敗しました. {}のアクセス権を確認してください.'.format(ir.codes_path))


def check_gpio(gpio_str):
  """
  GPIO番号(文字列)の指定が正しければGPIO(数値)を, 数値でなかったり範囲外であれば-1を返す

  Args:
    gpio_str: チェックするGPIO番号の文字列
  
  Returns:
    int: 正しければGPIO番号. 数値でなかったり範囲外であれば-1
  """
  if gpio_str.isdecimal():
    gpio = int(gpio_str)
    if gpio >= 0 and gpio <= 27:
      return gpio
  return -1
