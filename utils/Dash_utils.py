import os
import time
import uuid

import dash
#import dash_table
from dash import dash_table
import dash_bootstrap_components as dbc
#import dash_core_components as dcc
from dash import dcc
#import dash_html_components as html
from dash import html
from dash.dependencies import Input, Output, State
import dash_uploader as du

import utils.reusable_components as rc  # see reusable_components.py
import plotly.express as px

import pandas as pd
#import plotly.io as pio; pio.renderers.default='notebook'
from plotly.offline import plot

from utils.utilities import MKDIR
#from utils.utilities import ListSimilarity
from utils.MP_utils import MPlogger
from utils.DB_utils import sqlite3Query
from utils.Graph_utils import ComputeComponent


from dataclasses import dataclass, field
from typing import Callable, List, Union
from dash.dependencies import handle_callback_args

def discrete_background_color_bins(df,n_bins=5,columns='all',cmap='Blues'):
    import colorlover
    '''
    ['BrBG', 'PRGn', 'PiYG', 'PuOr', 'RdBu', 'RdGy', 'RdYlBu', 'RdYlGn', 'Spectral',
     'Accent', 'Dark2', 'Paired', 'Pastel1', 'Pastel2', 'Set1', 'Set2', 'Set3',
     'Blues', 'BuGn', 'BuPu', 'GnBu', 'Greens', 'Greys', 'OrRd', 'Oranges', 'PuBu',
     'PuBuGn', 'PuRd', 'Purples', 'RdPu', 'Reds', 'YlGn', 'YlGnBu', 'YlOrBr', 'YlOrRd']
    '''
    bounds = [i * (1.0 / n_bins) for i in range(n_bins + 1)]
    if columns == 'all':
        if 'id' in df:
            df_numeric_columns = df.select_dtypes('number').drop(['id'], axis=1)
        else:
            df_numeric_columns = df.select_dtypes('number')
    else:
        df_numeric_columns = df[columns]
    df_max = df_numeric_columns.max().max()
    df_min = df_numeric_columns.min().min()
    ranges = [
        ((df_max - df_min) * i) + df_min for i in bounds
    ]
    styles = []
    legend = []
    for i in range(1, len(bounds)):
        min_bound = ranges[i - 1]
        max_bound = ranges[i]
        #backgroundColor = colorlover.scales[str(n_bins)]['seq']['Blues'][i - 1]
        backgroundColor = colorlover.scales[str(n_bins)]['seq'][cmap][i-1]
        color = 'white' if i > len(bounds) / 2. else 'inherit'

        for column in df_numeric_columns:
            styles.append({
                'if': {
                    'filter_query': (
                        '{{{column}}} >= {min_bound}' +
                        (' && {{{column}}} < {max_bound}' if (i < len(bounds) - 1) else '')
                    ).format(column=column, min_bound=min_bound, max_bound=max_bound),
                    'column_id': column
                },
                'backgroundColor': backgroundColor,
                'color': color
            })
    
        legend.append(
            html.Div(style={'display': 'inline-block', 'width': '60px'}, children=[
                html.Div(
                    style={
                        'backgroundColor': backgroundColor,
                        'borderLeft': '1px rgb(50, 50, 50) solid',
                        'height': '10px'
                    }
                ),
                html.Small(round(min_bound, 2), style={'paddingLeft': '2px'})
            ])
        )

    return (styles, html.Div(legend, style={'padding': '5px 0 5px 0'}))


class LevelDVisProcessor:
    def __init__(self, df = None, VisPath = None, color = None,
                 color_discrete_map = None,
                 method = "sunburst",
                 OptAnnotation = False,
                 OptAnnotation_Value = True,
                 VisOutputSubDir = "LDVisual_",
                 HtmlOutput = "",
                 FolderConstrainList = [],
                 MPLOGGER = None):
        self.df = df
        self.VisPath = VisPath
        if color == None:
            color = VisPath[0]
        self.color = color
        self.color_discrete_map = color_discrete_map
        self.method = method
        self.OptAnnotation = OptAnnotation
        self.OptAnnotation_Value = OptAnnotation_Value
        self.VisOutputSubDir = VisOutputSubDir
        self.HtmlOutput = HtmlOutput
        self.FolderConstrainList = FolderConstrainList
        if MPLOGGER == None:
            self.MPLOGGER = MPlogger()
        else:
            self.MPLOGGER = MPLOGGER
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
        if self.df.shape[0] == 0 :
            MES = "When trying running LevelDVisProcessor in Dash_utils.py, the dataframe is empty and abort the job."
            self.MPLOGGER.logW(MES,logFile="Exception.log")
            return None
        if self.HtmlOutput == "":
            self.HtmlOutput = "{}_{}.html".format(str(self.VisPath), self.method)
        #fig = getattr(px, self.method)(self.df,path= self.VisPath, color='DataSrcType')
        if self.method in ["sunburst", "treemap"]:
            kwargs = {
                "path": self.VisPath,
                "color": self.color,
                }
            if self.color_discrete_map != None:
                self.color_discrete_map["(?)"]="black"
                kwargs["color_discrete_map"]=self.color_discrete_map
        #elif self.method == "treemap":
            #kwargs = {}
        else:
            kwargs = {}

        fig = getattr(px, self.method)(
            self.df,
            **kwargs
            )
            #kwargs)
        if self.OptAnnotation == True:
            if self.OptAnnotation_Value == True:
                fig.data[0].textinfo= 'label+value+percent parent+percent entry'
            fig.update_layout(
                uniformtext=dict(minsize=10, mode=False),
                #uniformtext=dict(minsize=10, mode='show'),
                #uniformtext=dict(minsize=6, mode='hide'),
                margin = dict(t=50, l=25, r=25, b=25),
                height=700,
            )
        #self.VisOutputSubDir = "LDVisual_"
        if self.FolderConstrainList == []:
            self.VisOutputSubDir += "all"
        else:
            self.VisOutputSubDir += 'Only'
            self.VisOutputSubDir += '_'.join([
                x.lstrip("\\").split("\\")[0] for x in self.FolderConstrainList])
        MKDIR(self.VisOutputSubDir)
        self.HtmlOutput = os.path.join(self.VisOutputSubDir,
                                  self.HtmlOutput)
        #fig.update_layout(uniformtext=dict(minsize=10, mode='hide'))
        try:
            #fig.write_html(self.HtmlOutput)
            with open(self.HtmlOutput, "w", encoding="utf-8") as f:
                f.write(fig.to_html())
        except Exception as e:
            MES = f"When trying to write html for LevelDVisProcessor in Dash_utils.py, the following error orccurs:\n{e}"
            self.MPLOGGER.logW(MES,logFile="Exception.log")
            #pass
        #return True
        return fig
    
def create_card(card_id, title, description, fig=None):
    return dbc.Card(
        dbc.CardBody(
            [
                html.H2(id=f"{card_id}-title", children = title),
                #html.H2("100", id=f"{card_id}-value"),
                #html.P(description, id=f"{card_id}-description"),
                dcc.Graph(
                    id=f"{card_id}-graph",
                    figure=fig),
                
            ]
        )
    )

def get_button_id(ctx, funName):
    #ctx = dash.callback_context
    if not ctx.triggered:
        button_id = 'No clicks yet'
    else:
        button_id = ctx.triggered[0]['prop_id'].split('.')[0]
    #print("In table_update, button_id", button_id)
    print(f"In function {funName}, button_id is {button_id}.")
    return button_id

def get_button_id_comp(ctx, funName):
    #ctx = dash.callback_context
    if not ctx.triggered:
        button_id_comp = 'No clicks yet'
    else:
        button_id_comp = ctx.triggered[0]['prop_id']
        button_id_comp = ctx.triggered
    #print("In table_update, button_id", button_id)
    print(f"In function {funName}, button_id_comp is {button_id_comp}.")
    return button_id_comp


def DictToDataArray(dictionary, keyName='key', valueName='value'):
    result = []
    for x in dictionary.keys():
        result.append(
            {keyName:x,valueName:str(dictionary[x])})
    return result


def Build_DataArrayTable(TableID,DataArray,ShownColumns=[],
                         style_header={},
                         style_cell={},
                         style_cell_conditional=[],
                         style_data_conditional=[],
                         MPLOGGER=None):
    if MPLOGGER == None:
        MPLOGGER = MPlogger()
    print("*"*50)
    print("Running Build_VisDatatable.")
    start_time = time.time()
    MES = f"Build Table {TableID} with \n ShownColumns {ShownColumns} and \n style_cell_conditional {style_cell_conditional}"
    MPLOGGER.logW(MES=MES,logFile="Test_result_Vis.log")
    print("It cost {:.2f} seconds to Build_DataArrayTable".format(
        time.time() - start_time))
    print("Finished running Build_VisDatatable.")
    return dash_table.DataTable(
        id=TableID,
        #data=DF.to_dict('records'),
        #data = DictToDataArray(MissionDict, keyName='Mission', valueName='Topics'),
        data = DataArray,
        columns=[{'id': str(c), 'name': str(c)} for c in ShownColumns],
        #style_cell={'textAlign': 'center'},
        style_header={
            'backgroundColor': 'rgb(230, 230, 230)',
            'fontWeight': 'bold'
        },
        #style_header=style_header,
        style_cell=style_cell,
        style_cell_conditional = style_cell_conditional,
        style_data_conditional = style_data_conditional,
        row_deletable=True,
        row_selectable ='multi',
        editable=True,
        filter_action='native',
        sort_action="native",
        #sort_action="custom",
        #sort_mode="multi",
        sort_mode="single",
        sort_by=[],
    )


#要先在主程式定義
#UPLOAD_FOLDER_ROOT = r"PVT_Temp\Uploads"
#du.configure_upload(app, UPLOAD_FOLDER_ROOT)
def get_upload_component(
        id,
        max_file_size=1800,   # 1800 Mb
        filetypes=['csv', 'txt', 'tsv'],
        upload_id=""):
    if upload_id == "":
        upload_id=uuid.uuid1()
    return du.Upload(
        id=id,
        max_file_size=max_file_size,
        filetypes=filetypes,
        upload_id=upload_id,  # Unique session id
    )






@dataclass
class Callback:
    func: Callable
    outputs: Union[Output, List[Output]]
    inputs: Union[Input, List[Input]]
    states: Union[State, List[State]] = field(default_factory=list)
    kwargs: dict = field(default_factory=lambda: {"prevent_initial_call": False})


class CallbackManager:
    def __init__(self):
        self._callbacks = []

    def callback(self, *args, **kwargs):
        output, inputs, state, prevent_initial_call = handle_callback_args(
            args, kwargs
        )

        def wrapper(func):
            self._callbacks.append(Callback(func,
                                            output,
                                            inputs,
                                            state,
                                            {"prevent_initial_callback": prevent_initial_call}))

        return wrapper

    def attach_to_app(self, app):
        for callback in self._callbacks:
            app.callback(
                callback.outputs, callback.inputs, callback.states, **callback.kwargs
            )(callback.func)
            