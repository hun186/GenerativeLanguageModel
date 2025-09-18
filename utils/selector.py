from colorama import Fore, Back, Style

class OptionSelector:
    '''
    字典格式：{
        選項值：選項說明
        }
    '''
    def __init__(self, options=dict(),question="請選擇一個選項：",default=None):
        self.options = options
        self.question = question
        self.default = default
    def proc(self, ):       
        # 提供選項給使用者
        idx_options = {
            str(i+1):(key,self.options[key])
            for i,key in enumerate(self.options.keys())}
        
        print("="*50)
        if self.default is not None and self.default in self.options.keys():
            default_shown = '(default:'+self.default+')'
            default_num = str(list(self.options.keys()).index(self.default)+1)
        else:
            default_shown = ''
            default_num = None
        #print("default_shown",default_shown)
        #print("default_num",default_num)
        print(f"{Fore.LIGHTYELLOW_EX}{self.question}{Fore.RESET} {default_shown}")
        for number, single_option in idx_options.items():
            option_value,explanation = single_option
            #如果選項有說明，則放在括號內顯示。
            print(f"{number}. {option_value} {('('+explanation+')') if explanation!='' else ''}")
                
        #讀取使用者輸入，驗證輸入並回傳對應的選項
        while(True):
            user_choice = input("輸入選項編號：") or default_num
            #print("idx_options",idx_options)
            if user_choice in idx_options:
                selected = idx_options[user_choice]
                print(f"你選擇了: {selected[0]}")
                #chosen_key = self.options[user_choice]
                #print("chosen_key",chosen_key)
                #return chosen_key
                return selected[0]
            else:
                print("無效的選項，請重新選擇正確的選項。")
                
class MultiOptionSelector:
    def __init__(self, options: dict, question: str = "請選擇：", default=None):
        """
        :param options: 以 dict 傳入，key 為選項代碼（例如 1, 2），value 為顯示文字
        :param question: 問題描述
        :param default: 預設值（可為 list）
        """
        self.options = options
        self.question = question
        self.default = default

    def proc(self):
        print("=" * 50)
        for idx, (key, label) in enumerate(self.options.items(), start=1):
            print(f"{idx}. {label}")

        print()
        if self.default:
            default_str = ",".join(str(idx + 1) for idx, key in enumerate(self.options) if key in self.default)
            prompt = f"{self.question}（可多選，逗號分隔） (default:{default_str})："
        else:
            prompt = f"{self.question}（可多選，逗號分隔）："

        user_input = input(prompt).strip()
        if not user_input and self.default:
            return self.default

        try:
            selected_indexes = [int(i.strip()) for i in user_input.split(",") if i.strip()]
            selected_keys = [list(self.options.keys())[i - 1] for i in selected_indexes]
            return selected_keys
        except Exception as e:
            print(f"⚠️ 輸入格式錯誤，請輸入有效數字，例如 1,3")
            return self.proc()  # 重新詢問
        
class InteractiveOptionSelector:
    '''
    字典格式：{
        選項值：選項說明
        }
    '''
    def __init__(self, options=dict(), question="請選擇一個選項："):
        self.options = options
        self.question = question

    def proc(self):
        # 初始化 curses
        import curses
        stdscr = curses.initscr()
        curses.noecho()
        curses.cbreak()
        stdscr.keypad(True)

        # 格式化選項並分配編號
        numbered_options = {str(i + 1): (key, self.options[key]) for i, key in enumerate(self.options)}
        option_keys = list(numbered_options.keys())

        # 計算每個選項的最大長度
        max_option_length = max(len(f"{number}. {option_value} {('(' + explanation + ')') if explanation else ''}") 
                                for number, (option_value, explanation) in numbered_options.items())

        # 顯示選項
        current_option = 0
        self.display_options(stdscr, numbered_options, current_option, max_option_length)

        # 讀取使用者輸入並驗證
        while True:
            key = stdscr.getch()
            if key == curses.KEY_UP and current_option > 0:
                current_option -= 1
            elif key == curses.KEY_DOWN and current_option < len(option_keys) - 1:
                current_option += 1
            elif key == 10:  # 10 是 Enter 鍵
                selected = numbered_options[option_keys[current_option]]
                stdscr.addstr(len(option_keys) + 2, 0, f"你選擇了: {selected[0]}")
                stdscr.refresh()
                stdscr.getch()
                curses.endwin()
                return selected

            self.display_options(stdscr, numbered_options, current_option, max_option_length)

    def display_options(self, stdscr, numbered_options, current_option, max_option_length):
        stdscr.clear()
        stdscr.addstr(0, 0, self.question)  # 顯示問題
        for i, (number, (option_value, explanation)) in enumerate(numbered_options.items()):
            prefix = '> ' if i == current_option else '  '
            # 格式化選項文本，並用 ljust 保持長度一致
            option_text = f"{prefix}{number}. {option_value} {('(' + explanation + ')') if explanation else ''}".ljust(max_option_length + 2)
            stdscr.addstr(i + 1, 0, option_text)  # 確保對齊在列的開頭
        stdscr.refresh()
