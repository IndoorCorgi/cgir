description = """
Raspberry Pi用赤外線送受信、データ解析ツール
GitHub: https://github.com/IndoorCorgi/cgir
使い方: https://www.indoorcorgielec.com/resources/raspberry-pi/python-pigpio-infrared/
"""

from argparse import ArgumentParser, RawTextHelpFormatter, RawDescriptionHelpFormatter
import time
import json
from .infrared import *


def cli():
  """
  コマンドラインツールを実行
  """

  # --helpを見やすくするための調整
  class CustomFormatter(RawTextHelpFormatter, RawDescriptionHelpFormatter):

    def __init__(self, prog, indent_increment=2, max_help_position=4, width=None):
      super().__init__(prog, indent_increment, max_help_position, width)

  parser = ArgumentParser(description=description, formatter_class=CustomFormatter)
  parser.add_argument('command',
                      choices=['rec', 'send', 'list', 'del', 'dec', 'enc'],
                      help='rec: 赤外線を受信してコードを<code_name>という名前で保存. \n'
                      'send: 保存したコードの中から, <code_name>で指定した名前の赤外線コードを送信. \n'
                      'list: 保存した赤外線コード一覧を表示.  \n'
                      'del: 保存したコードの中から, <code_name>で指定した名前の赤外線コードを削除. \n'
                      'dec: 保存したコードの中から, 赤外線コードを解析して, フォーマットとデータに変換して<file>(json形式)に保存. \n'
                      'enc: フォーマットとデータの<file>(json形式)から赤外線コードを生成して<code_name>という名前で保存. ')
  parser.add_argument('code_name', nargs='*', help='赤外線コードの名前. rec, send, delでは複数指定可能. ')

  parser.add_argument('--codes',
                      '-c',
                      type=str,
                      default='codes.json',
                      help='登録済み赤外線コードを保存, 読み出すファイル名かパス. デフォルトはcodes.json')

  parser.add_argument('--wait',
                      '-w',
                      default=1,
                      type=float,
                      help='複数のコードを送信する場合の間隔を秒数で指定. デフォルトは1.')
  parser.add_argument('--file', '-f', type=str, help='enc, decサブコマンドで使用するファイルを指定. ')
  parser.add_argument('--tx_dev',
                      '-t',
                      type=str,
                      default='/dev/lirc0',
                      help='送信に使用するLIRCデバイスファイル. デフォルトは/dev/lirc0')
  parser.add_argument('--rx_dev',
                      '-r',
                      type=str,
                      default='/dev/lirc1',
                      help='受信に使用するLIRCデバイスファイル. デフォルトは/dev/lirc1')

  args = parser.parse_args()

  ir = Infrared(dev_send=args.tx_dev, dev_rec=args.rx_dev, codes_path=args.codes)

  if args.command != 'list' and len(args.code_name) == 0:
    print('1つ以上の赤外線コード名<code_name>を指定してください. ')
    return

  # 登録済み赤外線コードを読み出す
  ir.load_codes()

  # 赤外線受信
  if args.command == 'rec':
    for cname in args.code_name:
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

  # 赤外線送信
  if args.command == 'send':
    # Wait
    if args.wait < 0 or args.wait > 1000:
      print('--waitは0から1000秒までの範囲で指定してください.')
      return

    first_time = True
    for cname in args.code_name:
      if not first_time:
        time.sleep(args.wait)
      if cname in ir.codes:
        print('赤外線コード "{}" を送信中...'.format(cname))
        ir.send(ir.codes[cname])
      else:
        print('赤外線コード "{}" が見つかりません.'.format(cname))
      first_time = False

  # 登録済みコード一覧表示
  if args.command == 'list':
    if len(ir.codes) == 0:
      print('登録済赤外線コードはありません.')
    else:
      print('登録済赤外線コード')
      for key in ir.codes:
        print(key)

  # 指定コードを削除
  if args.command == 'del':
    for cname in args.code_name:
      if cname in ir.codes:
        print('赤外線コード "{}" を削除しました.'.format(cname))
        ir.codes.pop(cname)
        ir.save_codes()
      else:
        print('赤外線コード "{}" が見つかりません.'.format(cname))

  # デコード
  if args.command == 'dec':
    cname = args.code_name[0]
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
    if args.file is not None:
      obj = {}
      obj['format'] = ir_format
      obj['data'] = frames

      try:
        with open(args.file, 'w') as f:
          f.write(json.dumps(obj, indent=2, ensure_ascii=False))
          print('\nファイル "{}" へ保存しました.'.format(args.file))
      except:
        print('\nファイルへ保存に失敗しました.')

  # エンコード
  if args.command == 'enc':
    try:
      with open(args.file, 'r') as f:
        obj = json.load(f)
    except:
      print('\nファイル "{}" の読み出しに失敗しました.'.format(args.file))
      return

    # フォーマットとデータがあるか確認
    if not ('format' in obj and 'data' in obj):
      print('\nファイル "{}" にフォーマットとデータがみつかりません.'.format(args.file))
      return

    if obj['format'] != FORMAT_AEHA and obj['format'] != FORMAT_NEC and obj['format'] != FORMAT_SONY:
      print('フォーマットが未対応か不明です.')
      return

    code = ir.encode(obj['format'], obj['data'])
    if len(code) == 0:
      print('エンコードに失敗しました.')
      return

    print('ファイル "{}" をエンコード\n'.format(args.file))
    print(code)
    cname = args.code_name[0]

    ir.codes[cname] = code
    if ir.save_codes():
      print('\n赤外線コード "{}" を登録しました.\n'.format(cname))
    else:
      print('\n赤外線コードの登録に失敗しました. {}のアクセス権を確認してください.'.format(ir.codes_path))
