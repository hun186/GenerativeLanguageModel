import os
#from czjLLM.taskConfig import taskSetting
from .taskConfig import taskSetting
#from DatasetConverter.sampleHandler import tokenization_wrap
from utils.utilities import tlog
from utils.utilities_path import fileNameNormalizer
from transformers import AutoTokenizer

class TokenizerWrapper:
    def __init__(self, model_name: str, task: str,
                 #base_path="GenerativeLanguageModel/czjLLM/tokenizers",
                 base_path="czjLLM/tokenizers",
                 max_tokens: int = None):
        self.model_name = model_name.lower()
        self.task = task
        self.base_path = base_path
        self.model_dir = self._resolve_model_dir()
        self.max_input_tokens = taskSetting.get(task, {}).get("InputCutLen", 3000)
        self.max_tokens = max_tokens or 8192  # 預設 output token 上限

    def _resolve_model_dir(self) -> str:
        model_tokenizer_map = {
            "qwen2.5": "qwen2.5_tokenizer",
            "qwen3": "qwen3_tokenizer",
            "deepseek-v3": "deepseek_v3_tokenizer",
            "deepseek": "deepseek_v3_tokenizer",  # fallback 指定
        }
        for key, folder in model_tokenizer_map.items():
            if key in self.model_name:
                return os.path.join(self.base_path, folder)
        return os.path.join(self.base_path, "deepseek_v3_tokenizer")


    def tokenize(
        self,
        text: str,
        adjust: bool = True,
        max_tokens: int = None,
        debug: bool = False,
        verbose: bool = True,
    ) -> dict:
        max_tokens = max_tokens or self.max_tokens
        nTokensToWrap = int(self.max_input_tokens * (max_tokens / 4096)) if adjust else self.max_input_tokens

        if verbose:
            print(f"📦 tokenizer path: {self.model_dir}")
            print(f"🧠 task: {self.task}")
            print(f"🔢 max tokens to wrap: {nTokensToWrap}")
    
        tokensWrap = tokenization_wrap(
            context=text,
            modelDir=self.model_dir,
            ReTks=True,
            debug=debug,
            nTokensToWrap=nTokensToWrap
        )
    
        if verbose:
            print(f"✅ ctxCut token lens: {[len(x) for x in tokensWrap['ctxCut']]}")
            print(f"✅ ReTks token lens: {[len(x) for x in tokensWrap['ReTks']]}")
        return tokensWrap



def tokenization_wrap(
        context, modelDir="", nTokensToWrap=256,
        word_analysis = False,ReTks = False,
        EarlyReturnForShortMessage = True,
        debug = False):
    #print("in tokenization_wrap, nTokensToWrap is",nTokensToWrap)
    #print("input modelDir for tokenization_wrap b4",modelDir)
    modelDir = fileNameNormalizer.proc(modelDir or "xlm-roberta-base")
    #print("input modelDir for tokenization_wrap af",modelDir)
    
    if debug == True:
        ReTks = True
    #EarlyReturnForShortMessage = False
    #print(context,len(context),nTokensToWrap)
    #如果開啓短文EarlyReturn，碰到太短的文本就直接回傳整串為一個單串。
    if all([EarlyReturnForShortMessage == True,
            len(context)+2<= nTokensToWrap,
            ]):
        if debug == True:
            print("len of context is not larger than nTokensToWrap, direct return [context] as the result of wrapping.")
        res = {
            "ctxCut":[context],
            "ReTks":[],
            }
        return res
    if not os.path.isdir(modelDir):
        print(f"WARNING! The input modelDir {modelDir} for tokenization_wrap does not exist, use xlm-roberta-base instead")
        modelDir = "xlm-roberta-base"
    
    #context = "This is a book.這是一本書。那是一枝筆"
    #nTokensToWrap = 6
    nTokensToWrap -= 3 #預留<s>、</s>及開頭補空白的位置
    #debug = True
    #context = "Все счастливые семьи похожи друг на друга, каждая несчастливая семья несчастлива по-своему. Все смешалось в доме Облонских. Жена узнала, что муж был в связи с бывшею в их доме француженкою-гувернанткой, и объявила мужу, что не мо- жет жить с ним в одном доме. Положение это продолжалось уже третий день и мучительно чувствовалось и самими супругами, и всеми членами семьи, и домочадцами. Все члены семьи и домочадцы чувствовали, что нет смысла в их сожительстве и что на каждом постоялом дворе случайно сошедшиеся люди более связаны между собой, чем они, члены семьи и домочадцы Облонских. "
    for subdir in [x[0] for x in os.walk(modelDir)]:
        if "config.json" in os.listdir(subdir):
            #model_checkpoint = subdir
            modelDir = subdir
            break
    #print("modelDir for tokenization",modelDir)
    tokenizer = AutoTokenizer.from_pretrained(
        modelDir,trust_remote_code=True)
    encoded = tokenizer(context)
    ecTks = encoded.tokens()
    if debug == True:
        print(context)
        print("encoded['input_ids']:",encoded['input_ids'])
        print(len(encoded['input_ids']))
        print("encoded.tokens():",ecTks)
        print(len(ecTks))
        print("encoded.word_ids():",encoded.word_ids())
        print(len(encoded.word_ids()))
    WrapPosList = []
    tksPos = list(range(1,len(ecTks)-1))
    indicator = [tksPos[i:i + nTokensToWrap] for i in range(0, len(tksPos), nTokensToWrap)]
    if debug == True:
        print("token分組位置清單:",indicator)
    WrapPosList = [[encoded.token_to_chars(csIntv[0]).start,
                    encoded.token_to_chars(csIntv[-1]).end] for csIntv in indicator]
    for i in range(len(WrapPosList)-1):
        if WrapPosList[i][1] == WrapPosList[i+1][0]:
            WrapPosList[i][1] -= 1
    if debug == True:
        print("WrapPosList af",WrapPosList)
    
    ctxCut = [context[st:ed+1] for st,ed in WrapPosList]
    if ReTks == True:
        ReTks = [tokenizer(x).tokens() for x in ctxCut]
    else:
        ReTks = []
    if debug == True:
        print("ctxCut",ctxCut)
        print("針對產出再次tokenized的結果:",ReTks)
        print([len(x) for x in ReTks])
    
    if word_analysis == True:
        corpora_records = context.split(' ')
        word_2_char_mapping = dict()
        char_cursor = 0
        for ind in range(len(corpora_records)):
            if(len(corpora_records[ind])>0): #the last space will not be considered
                start = char_cursor
                end = char_cursor+len(corpora_records[ind])
                word_2_char_mapping[ind] = [start,end]
                char_cursor = char_cursor+len(corpora_records[ind])+1 #consider the white
        if debug == True:
            print("word_2_char_mapping:",word_2_char_mapping)
        
        word_2_token_mapping = dict()
        for token_index in range(len(encoded.tokens())):
            this_token = encoded.word_ids()[token_index]
            if (not this_token==None):
                char_span=encoded.token_to_chars(token_index)
                if debug == True:
                    print("token_index,char_span",token_index,char_span)
                for each_word in word_2_char_mapping:
                    start = word_2_char_mapping[each_word][0]
                    end = word_2_char_mapping[each_word][1]
                    if (char_span.start)>=start and char_span.end<=end:
                        #print(batch_encoding.tokens()[token_index]) #check the
                        #print('--->')
                        #print(corpora_records[each_word])
                        if (each_word in word_2_token_mapping):
                            word_2_token_mapping[each_word].append(token_index)
                        else:
                            word_2_token_mapping[each_word]=[token_index]
        if debug == True:
            print("word_2_token_mapping:",word_2_token_mapping)
    res = dict()
    res["ctxCut"] = ctxCut
    res["ReTks"] = ReTks
    return res
