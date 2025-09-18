import pandas as pd
import numpy as np
import json

class SeriesToWeiTechFormatOutputer:
    def __init__(self, seri,
                 #df,
                 OutputCols=[],OutputFN = "test.AI2"):
        self.seri = seri
        self.OutputCols = OutputCols
        self.OutputFN = OutputFN
        #self.df = df

    def proc(self):
        if self.OutputCols == []:
            #print("When running SeriesToWeiTechFormatOutputer, outputcols is empty! Abort.")
            #return
            print("When running SeriesToWeiTechFormatOutputer, outputcols is empty! Output All!")
            self.OutputCols = self.seri.keys()
        res = dict()
        for col in self.OutputCols:
            res[col] = self.seri[col]
        #self.df = pd.DataFrame(columns=list('abc'), data = np.random.randn(15,3))
        #print("self.df",self.df)
        print("res",res)
        with open(self.OutputFN, 'w') as f:
            json.dump(res, f)

df = pd.DataFrame(columns=list('abc'), data = np.random.randn(5,3))
#print("df",df)
for row in df.iterrows():
    print('-'*50)
    print("St D", row[1].to_dict())
    print('-'*50)
    SeriesToWeiTechFormatOutputer(
        seri = row[1],
        #df = df,
        OutputCols = []).proc()
        #OutputCols = ['a','c']).proc()
    
    print("="*50)
    print(row)
#print("df",df)