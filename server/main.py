import time
import os
import datetime
import tempfile
import math
import subprocess
import pyautogui
from mcp.server.fastmcp import FastMCP
from Quartz import (
    CGEventCreateMouseEvent, CGEventCreateScrollWheelEvent, CGEventPost, CGEventSetIntegerValueField,
    kCGEventMouseMoved, kCGEventLeftMouseDown, kCGEventLeftMouseUp,
    kCGEventLeftMouseDragged, kCGEventRightMouseDown, kCGEventRightMouseUp,
    kCGEventRightMouseDragged, kCGEventOtherMouseDown, kCGEventOtherMouseUp,
    kCGEventOtherMouseDragged, kCGEventScrollWheel,
    kCGMouseButtonLeft, kCGMouseButtonRight, kCGMouseButtonCenter,
    kCGHIDEventTap, kCGMouseEventDeltaX, kCGMouseEventDeltaY
)

# サーバーのインスタンスを作成
mcp = FastMCP("ClusterControllerMcp")

# PyAutoGUIの安全装置（マウスを画面四隅にやると停止）
pyautogui.FAILSAFE = True
# デフォルトの遅延(0.1s)を無効化し、手動で制御する
pyautogui.PAUSE = 0


def _post_mouse_event(event_type, x, y, button, dx=0, dy=0):
    """Quartzでマウスイベントを送信"""
    # 座標はfloatである必要がある
    e = CGEventCreateMouseEvent(None, event_type, (float(x), float(y)), button)
    
    # Delta値を明示的に設定 (ゲーム視点操作用)
    if dx != 0 or dy != 0:
        CGEventSetIntegerValueField(e, kCGMouseEventDeltaX, int(dx))
        CGEventSetIntegerValueField(e, kCGMouseEventDeltaY, int(dy))
        
    CGEventPost(kCGHIDEventTap, e)

def _post_scroll_event(dy):
    """Quartzでスクロールイベントを送信"""
    # dy: 正数が上(奥)、負数が下(手前)
    # createScrollWheelEventは unit数を指定。
    # wheelCount=1, wheel1=dy
    e = CGEventCreateScrollWheelEvent(None, 0, 1, dy)
    CGEventPost(kCGHIDEventTap, e)


def run_applescript(script: str) -> str:
    """AppleScriptを実行するためのヘルパー関数"""
    try:
        proc = subprocess.run(
            ['osascript', '-e', script],
            capture_output=True,
            text=True
        )
        if proc.returncode != 0:
            return f"Error: {proc.stderr}"
        return proc.stdout.strip()
    except Exception as e:
        return str(e)

# グローバル変数でフォーカスする対象のアプリ名を保持
CURRENT_APP_NAME = "cluster"

# エモートのショートカット設定 (0-9)
# キーはエモート名、値は送信するキー
EMOTE_MAP = {    
    "sit": "1",      # 座る
    "like": "2",     # いいね！
    "pachi": "3",    # パチパチ
    "waiwai": "4",   # ワイワイ
    "laugh": "5",    # 笑う
    "heart": "6",    # ハート
    "bikkuri": "7",  # びっくり
    "haten": "8",    # はて？
    "nori": "9",     # ノリノリ
    "smile": "0",    # 笑顔
}

def _get_window_bounds_impl(app_name_keyword: str):
    """内部用: 指定されたアプリのウィンドウ位置とサイズを取得 (x, y, w, h)"""
    script = f'''
    tell application "System Events"
        set procList to every process whose name contains "{app_name_keyword}"
        if (count of procList) > 0 then
            tell item 1 of procList
                -- 全てのウィンドウの位置とサイズを取得
                set winPosList to position of every window
                set winSizeList to size of every window
                return {{winPosList, winSizeList}}
            end tell
        end if
    end tell
    '''
    result = run_applescript(script)
    if result and not result.startswith("Error"):
        try:
            # Output format example: "100, 100, 200, 200, 800, 600, 300, 400"
            # AppleScript returns flattened list: x1, y1, x2, y2, ... w1, h1, w2, h2 ...
            # 実際には "100, 100, 200, 200, 800, 600" のようにカンマ区切りで返ってくるが、
            # リストのリスト {{pos1, pos2}, {size1, size2}} が返る場合、 "p1x, p1y, p2x, p2y, s1w, s1h, s2w, s2h" のような単純な並びではない可能性がある。
            # 確実性を高めるため、個別に取得してパースするアプローチに変更するのが無難だが、
            # ここではPython側でパースを頑張る。
            
            # 簡易化: AppleScriptの出力を整形して扱いやすくする
            # 結果文字列から数字を全て抽出
            import re
            nums = [int(n) for n in re.findall(r'-?\d+', result)]
            
            # データは [x1, y1, x2, y2, ..., w1, h1, w2, h2, ...] の順で来るはず
            # 半分で分割
            if len(nums) % 4 == 0 and len(nums) > 0:
                count = len(nums) // 4
                positions = nums[:count*2]
                sizes = nums[count*2:]
                
                max_area = -1
                best_bounds = None
                
                for i in range(count):
                    x = positions[i*2]
                    y = positions[i*2+1]
                    w = sizes[i*2]
                    h = sizes[i*2+1]
                    
                    area = w * h
                    if area > max_area:
                        max_area = area
                        best_bounds = (x, y, w, h)
                
                return best_bounds

        except Exception as e:
            # print(f"Parse error: {e}")
            return f"Error: Parse exception {e} on result: {result}"
    return f"Error: No result or AppleScript error. Raw: {result}"

def _focus_window_impl(app_name_keyword: str, width: int = None, height: int = None, x: int = None, y: int = None) -> str:
    """内部用: 指定されたアプリケーションをアクティブにする実装"""
    if not app_name_keyword:
        return ""
        
    # ユーザー要望: デフォルトで(0,0)に移動
    if x is None: x = 0
    if y is None: y = 0

    # サイズ・位置変更用のスクリプトパーツ
    # System Eventsのプロセス -> ウィンドウに対して操作を行う
    settings_cmds = ""
    if width is not None and height is not None:
        settings_cmds += f'set size of window 1 of item 1 of procList to {{{width}, {height}}}\n'
    
    # x, yは必ず値を持つようになったので条件変更なしで出力、ただしwidth/heightとは独立させる
    settings_cmds += f'set position of window 1 of item 1 of procList to {{{x}, {y}}}\n'

    script = f'''
    tell application "System Events"
        set procList to every process whose name contains "{app_name_keyword}"
        if (count of procList) > 0 then
            set frontmost of item 1 of procList to true
            {settings_cmds}
            return "Found"
        else
            return "NotFound"
        end if
    end tell
    '''
    
    result = run_applescript(script)
    
    if result and "NotFound" in result:
        return f"エラー: '{app_name_keyword}' を含むアプリケーションが見つかりませんでした。"
    elif result and "Error" in result:
        return f"AppleScriptエラー: {result}"
    
    time.sleep(0.5) # 切り替え待機
    
    # 成功したらマウスを中央に移動（ユーザー要望）
    bounds = _get_window_bounds_impl(app_name_keyword)
    
    if isinstance(bounds, (tuple, list)) and len(bounds) == 4:
        bx, by, bw, bh = bounds
        center_x = bx + (bw // 2)
        center_y = by + (bh // 2)
        _post_mouse_event(kCGEventMouseMoved, center_x, center_y, kCGMouseButtonLeft)
    
    return f"成功: アプリケーション '{app_name_keyword}' をアクティブにしました。"



@mcp.tool()
def focus_window(app_name_keyword: str, width: int = None, height: int = None, x: int = None, y: int = None) -> str:
    """
    指定されたアプリケーション名を検索して最前面（アクティブ）にします。
    以降のコマンドでもこのアプリがデフォルトで使用されます。
    
    Macではウィンドウタイトルではなく「アプリケーション名」で指定するのが確実です。
    例: 'Minecraft', 'Terminal', 'Google Chrome'

    Args:
        app_name_keyword: アプリケーション名
        width: ウィンドウの幅 (optional)
        height: ウィンドウの高さ (optional)
        x: 左上のX座標 (optional)
        y: 左上のY座標 (optional)
    """
    global CURRENT_APP_NAME
    CURRENT_APP_NAME = app_name_keyword
    return _focus_window_impl(app_name_keyword, width, height, x, y)

@mcp.tool()
def press_game_keys(keys: str, duration: float = 0.1, app_name: str = None) -> str:
    """
    キー入力または同時押し操作を行います。
    Args:
        keys: スペース区切りのキー (例: "w", "shift+w", "space", "command+c")
              MacのCommandキーは 'command' と指定します。
        duration: キーを押す時間
        app_name: キー入力前にアクティブにするアプリ名。指定しない場合は前回のfocus_windowまたはデフォルト("cluster")を使用。
    """
    target_app = app_name if app_name else CURRENT_APP_NAME
    focus_msg = _focus_window_impl(target_app)
    
    # Mac用にキー名を調整（必要であれば）
    # pyautoguiは一般的に 'command', 'shift', 'ctrl', 'option' などに対応
    
    key_groups = keys.lower().split()
    results = []
    
    try:
        for item in key_groups:
            # 同時押し処理 ('+'で分割)
            if '+' in item:
                combo_keys = item.split('+')
                
                # キーダウン
                for k in combo_keys:
                    pyautogui.keyDown(k)
                
                time.sleep(duration)
                
                # キーアップ（逆順）
                for k in reversed(combo_keys):
                    pyautogui.keyUp(k)
                
                results.append(f"[{item}]")

            # 単発キー処理
            else:
                pyautogui.keyDown(item)
                time.sleep(duration)
                pyautogui.keyUp(item)
                results.append(item)
            
            time.sleep(0.05)
            
        return f"{focus_msg}\n入力完了: {' -> '.join(results)}" if focus_msg else f"入力完了: {' -> '.join(results)}"
        
    except Exception as e:
        # エラー時は全てのキーをリセット試行
        return f"{focus_msg}\n入力エラー: {str(e)} (キー名が正しいか確認してください)"

@mcp.tool()
def move_mouse_relative(x: int, y: int, button: str = "right", duration: float = 2.0, app_name: str = None) -> str:
    """
    マウスを現在の位置から相対的に移動（ドラッグ）させます。視点変更用。
    
    Args:
        x: 横方向移動量
        y: 縦方向移動量
        button: ドラッグするボタン ('left', 'right', 'middle')。デフォルトは 'right' (視点移動用)。ただの移動なら None または 'none'。
        duration: かける時間 (デフォルト: 2.0秒)
        app_name: 操作前にアクティブにするアプリ名。指定しない場合は前回のfocus_windowまたはデフォルト("cluster")を使用。
    """
    target_app = app_name if app_name else CURRENT_APP_NAME
    focus_msg = _focus_window_impl(target_app)

    try:
        # Retinaディスプレイ等のスケーリング対策が必要な場合がありますが、
        # 相対移動(moveRel)なら基本的にはそのまま動作します。
        

        # 現在位置とウィンドウ範囲を取得
        current_x, current_y = pyautogui.position()
        bounds = _get_window_bounds_impl(target_app)
        
        if bounds:
            win_x, win_y, win_w, win_h = bounds
            
            # まずウィンドウ中央に移動（ユーザー要望）
            center_x = win_x + (win_w // 2)
            center_y = win_y + (win_h // 2)
            _post_mouse_event(kCGEventMouseMoved, center_x, center_y, kCGMouseButtonLeft)
            current_x, current_y = center_x, center_y
            
            # 目標座標を計算
            target_x = current_x + x
            target_y = current_y + y
            
            # ウィンドウ範囲内にクランプ
            target_x = max(win_x, min(win_x + win_w, target_x))
            target_y = max(win_y, min(win_y + win_h, target_y))
            
            # 補正後の相対移動量を再計算
            # x, y は相対移動量、current_x, current_y は絶対座標として管理
            
        else:
            # クランプなし
            target_x = current_x + x
            target_y = current_y + y

        # buttonが None または 文字列の 'none' 以外ならドラッグ
        if button and button.lower() not in ['none', '']:
            # 指定がなければ right
            btn = button.lower()
            
            down_evt = kCGEventRightMouseDown
            up_evt = kCGEventRightMouseUp
            drag_evt = kCGEventRightMouseDragged
            cg_btn = kCGMouseButtonRight
            
            if btn == 'left':
                down_evt = kCGEventLeftMouseDown
                up_evt = kCGEventLeftMouseUp
                drag_evt = kCGEventLeftMouseDragged
                cg_btn = kCGMouseButtonLeft
            elif btn == 'middle':
                down_evt = kCGEventOtherMouseDown
                up_evt = kCGEventOtherMouseUp
                drag_evt = kCGEventOtherMouseDragged
                cg_btn = kCGMouseButtonCenter
            
            # Down
            _post_mouse_event(down_evt, current_x, current_y, cg_btn)
            
            # ユーザー要望: 右クリック長押し
            time.sleep(0.3)
            
            # Drag Loop
            # 現在地から target_x, target_y へ補間
            start_x, start_y = current_x, current_y
            diff_x = target_x - start_x
            diff_y = target_y - start_y
            
            if duration > 0:
                steps = int(max(duration * 60, 1))
                dt = duration / steps
                prev_x, prev_y = start_x, start_y
                for i in range(steps):
                    # 線形補間
                    progress = (i + 1) / steps
                    next_x = start_x + (diff_x * progress)
                    next_y = start_y + (diff_y * progress)
                    
                    # Delta計算
                    dx = next_x - prev_x
                    dy = next_y - prev_y
                    
                    _post_mouse_event(drag_evt, next_x, next_y, cg_btn, dx=dx, dy=dy)
                    prev_x, prev_y = next_x, next_y
                    time.sleep(dt)
            else:
                _post_mouse_event(drag_evt, target_x, target_y, cg_btn, dx=diff_x, dy=diff_y)
                
            # Up
            _post_mouse_event(up_evt, target_x, target_y, cg_btn)
            
            action = f"{btn}ボタンドラッグ(Quartz+Delta)"
        else:
            # Move
            start_x, start_y = current_x, current_y
            diff_x = target_x - start_x
            diff_y = target_y - start_y
            
            if duration > 0:
                steps = int(max(duration * 60, 1))
                dt = duration / steps
                prev_x, prev_y = start_x, start_y
                for i in range(steps):
                    progress = (i + 1) / steps
                    next_x = start_x + (diff_x * progress)
                    next_y = start_y + (diff_y * progress)
                    
                    dx = next_x - prev_x
                    dy = next_y - prev_y
                    
                    _post_mouse_event(kCGEventMouseMoved, next_x, next_y, kCGMouseButtonLeft, dx=dx, dy=dy)
                    prev_x, prev_y = next_x, next_y
                    time.sleep(dt)
            else:
                _post_mouse_event(kCGEventMouseMoved, target_x, target_y, kCGMouseButtonLeft)
                
            action = f"マウス移動(Quartz)"

        return f"{focus_msg}\n視点操作完了: {action} (X:{x}, Y:{y})" if focus_msg else f"視点操作完了: {action} (X:{x}, Y:{y})"
    except Exception as e:
        return f"{focus_msg}\nマウス操作エラー: {str(e)}"

@mcp.tool()
def scroll_zoom(amount: int, duration: float = 0.0, app_name: str = None) -> str:
    """
    マウスホイールを回転させてスクロール操作を行います。視点の拡大縮小などに使用します。

    Args:
        amount: スクロール量。正の値で上回転（ズームイン）、負の値で下回転（ズームアウト）。
                目安として 10 程度で大きく変化します。
        duration: アニメーション時間（秒）。0の場合は瞬時にスクロールします。指定した場合は時間をかけてスクロールします。
        app_name: 操作前にアクティブにするアプリ名。指定しない場合は前回のfocus_windowまたはデフォルト("cluster")を使用。
    """
    target_app = app_name if app_name else CURRENT_APP_NAME
    focus_msg = _focus_window_impl(target_app)

    try:
        if duration > 0:
            # 連続スクロール
            steps = int(max(duration * 10, 1)) # 0.1秒に1回程度
            step_delay = duration / steps
            step_amount = int(amount / steps)
            
            # 余り対策
            remainder = amount - (step_amount * steps)
            
            for i in range(steps):
                current_amount = step_amount
                if i == steps - 1:
                    current_amount += remainder
                
                if current_amount != 0:
                    # Quartz scroll (wheelCount units)
                    # pyautoguiのamount ~10 -> Quartz 1
                    scroll_val = int(current_amount / 10)
                    if scroll_val == 0:
                        scroll_val = 1 if current_amount > 0 else -1
                    _post_scroll_event(scroll_val)
                time.sleep(step_delay)
                
            return f"{focus_msg}\nスクロール操作完了 (アニメーション): amount={amount}, duration={duration}" if focus_msg else f"スクロール操作完了 (アニメーション): amount={amount}, duration={duration}"
        else:
            # Quartz scroll
            scroll_val = int(amount / 10)
            if scroll_val == 0 and amount != 0:
                 scroll_val = 1 if amount > 0 else -1
            _post_scroll_event(scroll_val)
            return f"{focus_msg}\nスクロール操作完了: amount={amount}" if focus_msg else f"スクロール操作完了: amount={amount}"
    except Exception as e:
        return f"{focus_msg}\nスクロール操作エラー: {str(e)}"

def _copy_to_clipboard(text: str):
    """クリップボードにテキストをコピー (Mac用 pbcopy)"""
    try:
        # echo -n で改行なしで渡す
        process = subprocess.Popen(['pbcopy'], stdin=subprocess.PIPE)
        process.communicate(input=text.encode('utf-8'))
    except Exception as e:
        print(f"Clipboard Error: {e}")

@mcp.tool()
def send_comment(comment: str, app_name: str = None) -> str:
    """
    チャットコメントを送信します。
    Bキーでチャットを開き、クリップボード経由で貼り付けてエンターで送信します。
    日本語も送信可能です。
    """
    target_app = app_name if app_name else CURRENT_APP_NAME
    focus_msg = _focus_window_impl(target_app)
    
    try:
        # 1. チャットを開く (B)
        pyautogui.press('b')
        time.sleep(0.5)
        
        # 2. クリップボードにコピー
        _copy_to_clipboard(comment)
        
        # 3. 貼り付け (Cmd+V)
        pyautogui.hotkey('command', 'v')
        time.sleep(0.1)
        
        # 4. 送信 (Enter)
        pyautogui.press('enter')
        
        # 送信後に少し待ってからBキーで閉じる（ユーザー報告により追加）
        # Enterで送信後、入力モードから抜けるがウィンドウが残る場合、Bで閉じる挙動の可能性
        # さらに、クリックしてフォーカスを戻してからBを押す（ユーザー要望）
        time.sleep(1.0)
        
        bounds = _get_window_bounds_impl(target_app)
        if isinstance(bounds, (tuple, list)) and len(bounds) == 4:
            bx, by, bw, bh = bounds
            center_x = bx + (bw // 2)
            center_y = by + (bh // 2)
            _post_mouse_event(kCGEventMouseMoved, center_x, center_y, kCGMouseButtonLeft)
            _post_mouse_event(kCGEventLeftMouseDown, center_x, center_y, kCGMouseButtonLeft)
            _post_mouse_event(kCGEventLeftMouseUp, center_x, center_y, kCGMouseButtonLeft)
            time.sleep(0.5)
            
        pyautogui.press('b')
        
        return f"{focus_msg}\nコメント送信完了: {comment}" if focus_msg else f"コメント送信完了: {comment}"
        
    except Exception as e:
        return f"{focus_msg}\nコメント送信エラー: {str(e)}"

@mcp.tool()
def perform_emote(emote_name: str, app_name: str = None) -> str:
    """
    エモートを実行します。
    名前（"wave", "clap"など）またはキー（"1"など）で指定できます。
    利用可能なエモート名: wave, clap, nod, shake, heart, joy, surprise, sad, angry, special
    """
    target_app = app_name if app_name else CURRENT_APP_NAME
    
    # マップからキーを検索、無ければそのまま使用
    key = EMOTE_MAP.get(emote_name.lower(), emote_name)
    
    # 実際に入力するキーが有効か一応チェック（ここでは簡易的に）
    msg = press_game_keys(keys=key, duration=0.1, app_name=target_app)
    
    # ユーザー要望によりエモート後に1秒ウェイト
    time.sleep(1.0)
    
    return f"{msg} (1秒待機)"

@mcp.tool()
def wave_hands(side: str = "right", duration: float = 2.0, app_name: str = None) -> str:
    """
    指定した腕（CキーまたはZキー）を上げながらマウスを動かして手を振る動作を行います。
    
    Args:
        side: "right" (右手/Cキー), "left" (左手/Zキー), "both" (両手). Default: "right"
        duration: 動作時間(秒). Default: 2.0
        app_name: アプリ名.
    """
    target_app = app_name if app_name else CURRENT_APP_NAME
    focus_msg = _focus_window_impl(target_app)
    
    side_map = {
        'right': ['c'],
        'left': ['z'],
        'both': ['z', 'c']
    }
    
    keys = side_map.get(side.lower())
    if not keys:
         return f"{focus_msg}\nエラー: sideは right, left, both のいずれかを指定してください"

    try:
        # キーを押す
        for k in keys:
            pyautogui.keyDown(k)
            
        # マウスを振るループ (8の字に動かすと自然に見える)
        start_t = time.time()
        
        # 振幅と速度
        amp = 40.0
        speed = 8.0
        
        # 画面中央付近を基準にするため現在地取得
        mx, my = pyautogui.position()
        
        while time.time() - start_t < duration:
            t = time.time() - start_t
            
            # 速度成分 (Delta) を計算
            # 位置 x = sin(t), y = sin(2t) / 2 とすると
            # 速度 dx = cos(t), dy = cos(2t)
            
            dx = int(amp * math.cos(t * speed)) 
            dy = int(amp * math.cos(t * speed * 2) * 0.5)
            
            _post_mouse_event(kCGEventMouseMoved, mx, my, kCGMouseButtonLeft, dx=dx, dy=dy)
            
            time.sleep(0.05)
            
        return f"{focus_msg}\n手を振る動作完了 ({side}, {duration}秒)"
        
    except Exception as e:
        return f"{focus_msg}\nエラー: {e}"
    finally:
        # 必ずキーを離す
        for k in keys:
            pyautogui.keyUp(k)

@mcp.tool()
def take_screenshot(app_name: str = None) -> str:
    """
    現在の画面をスクリーンショット撮影し、一時ファイルのパスを返します。
    アプリ名を指定する（またはデフォルトアプリがある）場合、そのウィンドウをアクティブにしてから
    その領域だけを撮影します。
    """
    try:
        target_app = app_name if app_name else CURRENT_APP_NAME
        
        # アプリをアクティブにする
        if target_app:
            _focus_window_impl(target_app)
            # アニメーション待ちなどを考慮して少し待機
            time.sleep(0.5)

        # ウィンドウ領域を取得
        region = None
        if target_app:
            bounds = _get_window_bounds_impl(target_app)
            # boundsは (x, y, w, h) のタプルであることを期待
            if isinstance(bounds, (tuple, list)) and len(bounds) == 4:
                region = bounds
        
        temp_dir = tempfile.gettempdir()
        timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
        filename = f"mac_screenshot_{timestamp}.png"
        filepath = os.path.join(temp_dir, filename)

        # region引数があればその範囲、なければ全画面
        screenshot = pyautogui.screenshot(region=region)
        screenshot.save(filepath)

        return filepath

    except Exception as e:
        return f"撮影エラー: {str(e)}"

if __name__ == "__main__":
    mcp.run()