from utils.utilities import MKDIR
import pandas as pd
#import plotly.io as pio; pio.renderers.default='notebook'
from plotly.offline import plot
import plotly.express as px

class LevelDVisProcessor:
    def __init__(self, df = None, VisPath = None,
                 method = "sunburst", HtmlOutput = "",
                 FolderConstrainList = []):
        self.df = df
        self.VisPath = VisPath
        self.method = method
        self.HtmlOutput = HtmlOutput
        self.FolderConstrainList = FolderConstrainList
    def show(self):
        print("VisPath:", self.VisPath)
        print("method:", self.method)
        print("HtmlOutput:", self.HtmlOutput)
        print("FolderConstrainList:", self.FolderConstrainList)
    def run(self):
    #def LevelDVis(df,VisPath,method = "sunburst",HtmlOutput = "",
                  #FolderConstrainList = []):
        #LevelDataVisulization
        #df[VisPath[0]] = df[VisPath[0]].apply(customwrap)
        #df[VisPath[1]] = df[VisPath[1]].apply(customwrap)
        #df[VisPath[2]] = df[VisPath[2]].apply(customwrap)
        # BurstPath = [Column A, Column B, Column C]
        if self.HtmlOutput == "":
            self.HtmlOutput = "{}_{}.html".format(str(self.VisPath), self.method)
        fig = getattr(px, self.method)(self.df,path= self.VisPath, color='DataSrcType')
        #fig.show()
        #plot(fig)
            
        VisOutputSubDir = "LDVisual_"
        if self.FolderConstrainList == []:
            VisOutputSubDir += "all"
        else:
            VisOutputSubDir += 'Only'
            VisOutputSubDir += '_'.join([
                x.lstrip("\\").split("\\")[0] for x in self.FolderConstrainList])
        MKDIR(VisOutputSubDir)
        self.HtmlOutput = os.path.join(VisOutputSubDir,
                                  self.HtmlOutput)
        #fig.update_layout(uniformtext=dict(minsize=10, mode='hide'))
        fig.write_html(self.HtmlOutput)
        #return True
        return fig