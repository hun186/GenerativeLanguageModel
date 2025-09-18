from PackageImport import PackageImporter
PackageImporter.proc()
import sys
import glob
ModPaths = []
ModPaths.extend(glob.glob("C:/Users/*/Documents/PythonModule"))
ModPaths.extend([
    "D:/shared/PythonModule",
    "Z:/shared/PythonModule"
    "D:/shared/TopicClassification/PythonModule",
    "Z:/shared/TopicClassification/PythonModule",
    ])
for ModulePath in ModPaths:
    sys.path.append(ModulePath)
import os
import re
import sys


from utils.utilities import textReader
from utils.utilities import MKDIR
from utils.utilities import getFNFromFullPath
from utils.MP_utils import MPlogger


def Extract_Header(InputFN = None, OutputROOTPATH = "../EmailOutput"):
    if InputFN is None:
        MES = "As the InputFN is None, Email header extractor aborted."
        MPlogger.logW(MES,logFile="Email_utils_log.txt")
        return
    if not os.path.isdir(OutputROOTPATH):
        MKDIR(OutputROOTPATH)    
        
    src = InputFN
    #print("OutputROOTPATH",OutputROOTPATH)
    #print("InputFN",InputFN)
    des = os.path.join(OutputROOTPATH,getFNFromFullPath(InputFN))
    #print("des",des)
    with open(des,'wt',encoding='utf-8') as ouf:
        with open(src,'rt',encoding='utf-8',errors='ignore') as inf:
            result = ""
            for line in inf.readlines():
                #print("line",line)
                #print("len(line.replace(" ",""))",len(line.replace(" ","")))
                if len(line.rstrip().replace(" ",""))>0:
                    result += line
                else:
                    break
            #text = textReader(
                #file=src,encoding="utf-8").run()
            #ouf.write(inf.read(20000000).split("\n\n")[0])
            #ouf.write(text.split("\n\n")[0])
            ouf.write(result)
        #print(inf.read())
        #for y in sorted(set([LabelConvertDict[x] for x in DNTags])):
        #for y in sorted(set([LabelConvertDict[x] for x in LabelList])):
            #f.write(y+"\n")


