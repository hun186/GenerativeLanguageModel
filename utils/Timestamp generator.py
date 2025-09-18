from datetime import datetime
import os
from random import randrange
import datetime 
import random
import re
import locale

def MKDIR(DirName):
    #fileNameNormalizer.proc(DirName)
    os.makedirs(DirName, exist_ok=True)

def RemoveIlleagalCharForFileName(title, Mode = "FileName"):
    result = title
    if Mode == "FileName":
        IlleagalSet = ['/','\\',':','?','\"','<','>','|','\n','\xa0','\t','*']
        IlleagalMapDict = {}
        for x in IlleagalSet:
            IlleagalMapDict[x] = "_"
    if Mode == "Latex":
        IlleagalMapDict = {}
        IlleagalMapDict["_"] = " "
        IlleagalMapDict["&"] = "\&"
        IlleagalMapDict["%"] = "\%"
        IlleagalMapDict["#"] = "＃"
    for x in IlleagalMapDict.keys():
        result = result.replace(x,IlleagalMapDict[x])
    return result


def timeToFile(date_time=None, fmt="%m/%d/%Y, %H:%M:%S",
               OFMN = None,printOnScreen = False,
               Loc = None):
    if date_time == None:
        date_time = datetime.now() # current date and time
    if Loc is not None:
        locale.setlocale(locale.LC_ALL, Loc)
    ctx = date_time.strftime(fmt)
    if re.search(u'[\u4e00-\u9fff]', ctx):
        if random.randint(0,1)>0:
            repDict = {
                "時": "點"}
            for key in repDict.keys():
                ctx = ctx.replace(key, repDict[key])

    if printOnScreen == True:
        print(ctx)
    if OFMN == None:
        OutputFN = RemoveIlleagalCharForFileName(ctx[:100]+".txt")
    else:
        OutputFN = RemoveIlleagalCharForFileName(str(OFMN)+".txt")
    SubDir = "RandomTimeGeneration"
    MKDIR(SubDir)
    open(os.path.join(SubDir,OutputFN),'wt',encoding='utf-8').write(ctx)#.close()
    open(os.path.join("total.txt"),'at',encoding='utf-8').write(ctx+"\n")#.close()


def random_date(start,l):
    TimeRange = 60*24*30*12*10*60*1000000  #microseconds range
    current = start
    while l >= 0:
        #curr = current + datetime.timedelta(minutes=randrange(60))
        #curr = current + datetime.timedelta(minutes=randrange(TimeRange))
        #curr = current + datetime.timedelta(seconds=randrange(TimeRange))
        curr = current + datetime.timedelta(microseconds=randrange(TimeRange))
        yield curr
        l-=1


#printOnScreen = True
printOnScreen = False
startDate = datetime.datetime(2013, 9, 20,13,00)
    
fmtList = [
    "%c",
    "%x",
    "%X",
    "%a %b %d %H:%M:%S %Y", #default for python
    "%m/%d/%Y, %H:%M:%S",
    "%B/%d/%Y, %H:%M:%S",
    "%b/%d/%Y, %H:%M:%S",
    "%m/%d/%Y, %I:%M:%S %p",
    "%B/%d/%Y, %I:%M:%S %p",
    "%b/%d/%Y, %I:%M:%S %p",
    "%m/%d/%Y, %p %I:%M:%S",
    "%B/%d/%Y, %p %I:%M:%S",
    "%b/%d/%Y, %p %I:%M:%S",
    "%m/%d/%Y, %a,%H:%M:%S",
    "%B/%d/%Y, %a, %H:%M:%S",
    "%b/%d/%Y, %a, %H:%M:%S",
    "%m/%d/%Y, %A,%H:%M:%S",
    "%B/%d/%Y, %A, %H:%M:%S",
    "%b/%d/%Y, %A, %H:%M:%S",
    "%Y-%m-%dT%H:%M:%S-0900",
    "%Y-%b-%dT%H:%M:%S+1130",
    "%Y-%B-%dT%H:%M:%S+0300",
    "%Y %m %dT%H:%M:%S-0400",
    "%Y %b %dT%H:%M:%S+0230",
    "%Y %B %dT%H:%M:%S+0600",
    "%Y-%m-%dT%H:%M:%S-0900",
    "%Y-%b-%dT%H:%M:%S.%f-0130Z",
    "%Y-%B-%dT%H:%M:%S.%f+0030Z",
    "%Y %m %dT%H:%M:%S.%f-0500Z",
    "%Y %b %dT%H:%M:%S.%f-0730Z",
    "%Y %B %dT%H:%M:%S.%f+0800Z",
    "%m %d %Y, %H:%M:%S",
    "%B %d %Y, %H:%M:%S",
    "%b %d %Y, %H:%M:%S",
    "%m %d %Y, %a, %H:%M:%S",
    "%B %d %Y, %a, %H:%M:%S",
    "%b %d %Y, %a, %H:%M:%S",
    "%m %d %Y, %A, %H:%M:%S",
    "%B %d %Y, %A, %H:%M:%S",
    "%b %d %Y, %A, %H:%M:%S",
    "%d/%b/%Y:%H:%M:%S-0500",
    "%b %d, %Y %I:%M:%S %p",
    "%b %d, %Y %p %I:%M:%S",
    "%b %d %Y %H:%M:%S",
    "%b %d %H:%M:%S +0200",
    "%b %d %H:%M:%S",
    "%Y,%B %d, %H:%M:%S",
    "%m %d, %H:%M:%S -0700 %Y",
    "%B %d, %H:%M:%S +0800 %Y",
    "%b %d, %H:%M:%S +0030 %Y",
    "%H:%M:%S",
    "%I:%M:%S %p",
    "%p %I:%M:%S",
    "%Y年%m月%d日, %H時%M分",
    "%Y年%m月%d日, %I時%M分 %p",
    "%Y年%m月%d日, %p %I時%M分",
    "%m月%d日, %H時%M分",
    "%m月%d日, %H時%M分 %p",
    "%m月%d日, %p %I時%M分",
    "%Y年%m月%d日, %a, %H時%M分",
    "%Y年%m月%d日, %a, %I時%M分 %p",
    "%Y年%m月%d日, %a, %p %I時%M分",
    "%m月%d日, %a, %H時%M分",
    "%m月%d日, %a, %H時%M分 %p",
    "%m月%d日, %a, %p %I時%M分",
    "%H時%M分",
    "%p %I時%M分",
]

TimeZone = {
    "Los Angeles": "-8",
    "洛杉磯" : "-8",
    "San Diego" : "-8",
    "聖地牙哥" : "-8",
    "Ottawa" : "-5",
    "渥太華" : "-5",
    "New York" : "-5",
    "紐約" : "-5",
    "Brasilia" : "-3",
    "巴西利亞" : "-3",
    "London" : "+0",
    "倫敦" : "+0",
    "Paris" : "+1",
    "巴黎" : "+1",
    "Berlin" : "+1",
    "柏林" : "+1",
    "Madrid" : "+1",
    "馬德里" : "+1",
    "Jerusalem" : "+2",
    "耶路撒冷" : "+2",
    "Moscow" : "+3",
    "莫斯科" : "+3",
    "New Delhi" : "0530",
    "新德里" : "+0530",
    "Bangkok" : "+7",
    "曼谷" : "+7",
    "Taipei" : "+8",
    "臺北" : "+8",
    "Beijing":"+8",
    "北京" : "+8",
    "Tokyo" : "+9",
    "東京" : "+9",
    "Seoul" : "+9",
    "首爾" : "+9",
}

UTCExtList= []
for tz in TimeZone:
    UTCExtList.extend([
            f" UTC {TimeZone[tz]}",
            f", UTC {TimeZone[tz]}",
            f" {tz}, UTC {TimeZone[tz]}",
            f", {tz}, UTC {TimeZone[tz]}",
            f", {tz}, GMT {TimeZone[tz]}",
            f", {tz}, UTC/GMT {TimeZone[tz]}",
            ])
        
randomTimeList = list(random_date(startDate,1000))
randomLocaleList = [
    "zh_TW","zh_CN","de_DE","en_US","fr_FR","ja_JP","ko_KR","es_ES","it_IT","ru_RU","th_TH","ar_SA"]
#print(randomTimeList)
TZList = list(TimeZone.keys())

ct = 0
for x in range(5000):
    fmt = random.choice(fmtList)
    #'''
    #print("fmt",fmt)

    #else:
        #locale.setlocale(locale.LC_ALL, 'zh_TW')
    #'''
    if random.randint(0,1)>0:
        repDict = {
            "%m": "%#m",
            "%d": "%#d",
            "%H": "%#H",
            "%M": "%#M",
            "%S": "%#S",
            "%I": "%#I"
            }
        for key in repDict.keys():
            fmt = fmt.replace(key, repDict[key])
        #print("new fmt",fmt)

    RTLocale = random.choice(randomLocaleList)
    if re.search(u'[\u4e00-\u9fff]', fmt):
        locale.setlocale(locale.LC_ALL, random.choice(['zh_TW','zh_CN']))
    else:
        locale.setlocale(locale.LC_ALL, RTLocale)


    RT = random.choice(randomTimeList)
    timeToFile(date_time=RT, fmt=fmt,printOnScreen=printOnScreen)
    ct += 1
    #如果fmt本身已有時區的+0000的類似四碼字樣或不含有時分資訊，
    #則不進行額外的UTC補添產製。
    if len(re.findall("(\+|-)\d{4}",fmt))>0 or not "%M" in fmt:
        continue
    tz = random.choice(TZList)
    UTCExt = random.choice(UTCExtList)
    RT = random.choice(randomTimeList)
    tzfmt = fmt + UTCExt

    RTLocale = random.choice(randomLocaleList)
    if re.search(u'[\u4e00-\u9fff]', tzfmt):
        locale.setlocale(locale.LC_ALL, 'zh_TW')
    else:
        locale.setlocale(locale.LC_ALL, RTLocale)

    timeToFile(date_time=RT,fmt=tzfmt,printOnScreen=printOnScreen)
    ct += 1
print("="*50)
print(f"共生成{ct}筆資料")

