import os

def getTopicLabelList(output_dir): #output_dir:trained model dir
  LabelList = []
  LabelFile = os.path.join(output_dir,"TopicAnalysis_LabelList.txt")
  if os.path.isfile(LabelFile):
      with open(LabelFile,'rt',encoding='utf-8') as f:
          for line in f:
              LabelList.append(line.strip())
      #print("lab", LabelList)
      #raise Exception
      return LabelList