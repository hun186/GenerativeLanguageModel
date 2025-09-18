#from PackageImport import PackageImporter
#PackageImporter.proc()

from tulip import tlp
try:
    from tulipgui import tlpgui
except:
    pass
import time
import sys
import os

from array import array

from utils.utilities import ListFill
from utils.utilities import ShowElapsedTime
from utils.utilities import ShowPartDict
from utils.utilities import MemUsage
from utils.utilities import SortedDictWithValLen
'''
def ShowElapsedTime(start_time):
    elapsed_time = time.time() - start_time
    print("It has been passed for {:.4f} seconds".format(elapsed_time))
    return elapsed_time
'''
def ExtractNodes(Edges):
    nodeset= []
    #UserPairInput format: (src, tar), a dictionary
    #or UserPairInput format: (src, tar, date), a dictionary
    for ed in Edges:
        nodeset.append(ed[0])
        nodeset.append(ed[1])
    return sorted(set(nodeset))

def find_id_src_tar(src, tar, NodeLabeltoIdTable): #(node Label (address code) -> id)
    return find_id_of_viewLabel(src, NodeLabeltoIdTable), find_id_of_viewLabel(tar, NodeLabeltoIdTable)

def find_id_of_viewLabel(label, NodeLabeltoIdTable):
    if type(NodeLabeltoIdTable) == array:
        index = int(label)
    elif type(NodeLabeltoIdTable) == dict:
        index = label
    return tlp.node(NodeLabeltoIdTable[index])

def BuildEdges(graph, Edges, label2id):
    #print("The DataCounted keys are", DataCounted.keys())
    for ed in Edges:
        src, tar = find_id_src_tar(ed[0], ed[1], label2id)
        newEdge = graph.addEdge(src, tar) 
        #multiple edges are allowed and will be counted repeated for degree
        if len(ed) >= 3:
            graph['viewLabel'][newEdge] = str(ed[2])
    print(f"there are {graph.numberOfEdges()} different edges.")
    return graph

def NodeLabeltoIdTable(graph,start_time=0):
    if start_time>0:
        ShowElapsedTime(start_time)
    Method = "dict"
    #Method = "array"
    if Method == "array":
        #Nodes = list(graph.getNodes())
        NLS = CountNodeLabelSize(graph)
        label2id = array("i")
        for x in range(NLS):
            label2id.append(-1)
            #print(label2id[0])
            #print("node id     Address")
        for node in graph.getNodes():
            label2id[int(graph['viewLabel'][node])] = node.id
        print("The first 100 of label2id", label2id[0:100])
    elif Method == "dict":
        label2id = {}
        for node in graph.getNodes():
            label2id[graph['viewLabel'][node]] = node.id
        ShowPartDict(label2id, 30, "label2id")
    print("Finihed constructing inverse search list for nodes.")
    ShowElapsedTime(start_time)
    print("the memory size of label2id is", sys.getsizeof(label2id))
    ShowID = []
    if type(label2id) == array:
        ShowID = [int(x) for x in ShowID]
    for label in ShowID:
        print("The Node id of ", label, " is ", label2id[label])
    print("The type of label2id is ", type(label2id))
    return label2id



def graph_global_references(graph):
    # Get references to some view properties
    global viewLayout, viewSize, viewBorderWidth, viewLabelBorderWidth, viewColor
    global viewLabelColor, viewLabelBorderColor, viewBorderColor, viewLabel, viewShape
    global viewSize
    #global degree, degreeParams
    global degreeParams
    viewLayout = graph.getLayoutProperty("viewLayout")
    viewSize = graph.getSizeProperty("viewSize")
    viewBorderWidth = graph.getDoubleProperty("viewBorderWidth")
    viewLabelBorderWidth = graph.getDoubleProperty("viewLabelBorderWidth")
    viewColor = graph.getColorProperty("viewColor")
    viewLabelColor = graph.getColorProperty("viewLabelColor")
    viewLabelBorderColor = graph.getColorProperty("viewLabelBorderColor")
    viewBorderColor = graph.getColorProperty("viewBorderColor")
    viewLabel = graph.getStringProperty("viewLabel")
    viewShape = graph.getIntegerProperty("viewShape")
    #viewIcon = graph.getStringProperty("viewIcon")
    #viewTexture = graph.getStringProperty("viewTexture")
    #viewSelection = graph.getBooleanProperty("viewSelection")
    
    #degree = tlp.DoubleProperty(graph)
    #degree = graph.getDoublePropertyy("degree")
    degreeParams = tlp.getDefaultPluginParameters("Degree")
    
    #nodelinkView = tlpgui.createNodelinkDiagramView(graph)
    #renderingParameters = nodelinkView.getRenderingParameters()
    
    
def BuildGraph(WeightEdgeList, start_time=0):
    graph = tlp.newGraph()
    print("Start extracting nodes.")
    nodeset = ExtractNodes(WeightEdgeList)
    
    node_digit = len(nodeset)
    if len(nodeset) == 0:
        print("Warning! THERE ARE NO NODES! TERMINATE!")
        print("Check Time Period Setting!")
        return None, None
    
    print("The non-repeated-nodeset is completed. There are", len(nodeset), "nodes.")
    print("The first 30 nodes are", nodeset[0:30])
    True_node_0_ID_code = nodeset[0]
    for node in nodeset:
        n = graph.addNode()
        graph['viewLabel'][n] = node

    Original_nnodes = graph.numberOfNodes()
    #viewLabel = graph.getStringProperty("viewLabel")
    #ShowElapsedTime(start_time)
    print("Start to construct inverse search list for nodes.")
    #Construct the inverse search table
    label2id = NodeLabeltoIdTable(graph)
    #ShowElapsedTime(start_time)
    
    print("Start to load edges in Time Period.")
    #load_edges(graph, data, data_format)
    
    graph = BuildEdges(graph, WeightEdgeList, label2id)
    #degree, MaxDegree = Compute_degree_of_graph(graph)
    if start_time >0:
        ShowElapsedTime(start_time)
    
    return graph

def Compute_degree_of_graph(graph):
    #Compute an anonymous degree property
    #degree = tlp.DoubleProperty(graph)
    degree = graph.getDoubleProperty("degree")
    degreeParams = tlp.getDefaultPluginParameters("Degree")
    graph.applyDoubleAlgorithm("Degree", degree, degreeParams)
    print("Degree has been computed.")
    MaxDegree = degree.getNodeMax()
    print("Max degree is ", MaxDegree)
    return degree, MaxDegree

def set_groupID_Property(graph, LabelType = 'ZMA IDCode'):
    '''
    for node in graph.getNodes():
        StringSP = graph['viewLabel'][node].split(".")
        if len(StringSP) == 4:
            for x in StringSP:
                if 0 <= int(x) <= 255:
                    continue
                else:
                    ISIPCheck = False
        if ISIPCheck != False:
            LabelType = 'IP'
        break
    '''
    groupID = graph.getStringProperty("groupID")
    groupID_INT = graph.getIntegerProperty("groupID_INT")
    if LabelType == 'ZMA IDCode':
        for node in graph.getNodes():
            graph['groupID'][node] = graph['viewLabel'][node][0:5]
            #graph['groupID_INT'][node] = int(graph['groupID'][node])
    elif LabelType == 'IP':
        for node in graph.getNodes():
            StringSP = graph['viewLabel'][node].split(".")
            #graph['groupID'][node] = '.'.join(StringSP[0:2])
    print("Label Type is ", LabelType, ".")
    return groupID#, groupID_INT

def ClusterMetaNodeGraph(graph, ClusterMethod):
    graph_global_references(graph)
    graphProperty = graph.getDoubleProperty(ClusterMethod)
    ClusterMethodParams = tlp.getDefaultPluginParameters(ClusterMethod)
    
    graph.applyDoubleAlgorithm(ClusterMethod, graphProperty, ClusterMethodParams)
    ColorParams = tlp.getDefaultPluginParameters('Color Mapping')
    ColorParams['result'] = viewColor
    ColorParams['input property'] = graphProperty
    print("ColorParams:", ColorParams)
    graph.applyColorAlgorithm('Color Mapping', viewColor, ColorParams)
    
    graph_meta = graph.addCloneSubGraph("graph_meta")
    graph_ori = graph.addCloneSubGraph("graph_ori")
    PossibleNodeValue = []
    CMP = {}
    for node in graph.getNodes():
        PossibleNodeValue.append(graphProperty.getNodeValue(node))
    
    
    for x in sorted(set(PossibleNodeValue)):
        #print(x,list(set(graphProperty.getNodesEqualTo(x))))
        Comm = list(set(graphProperty.getNodesEqualTo(x)))
        MetaN = graph_meta.createMetaNode(Comm)
        CMP[int(x)]=[graph['viewLabel'][node] for node in Comm]
        graph['viewLabel'][MetaN] = graphProperty.getName() + " " + str(x).replace(".0", "")
        graph['viewColor'][MetaN] = tlp.Color.White
        #graph['viewBorderColor'][MetaN] = tlp.Color.White
        graph['viewLabelSize'][MetaN] = 500
    #print("ClusteringCMPList",ClusteringCMPList)
    #params_specified = {'number of passes': 15, 'x border':100.0, 'y border':1000.0}
    #ApplyLayoutEffect(graph_meta, "Fast Overlap Removal", params_specified)
    #Create_Node_Link_Diagram_view(graph, degree, node_size_property, show_setting = False, method = None, Apply_3D_layout = True, params_specified = None, Coloring_with = "degree", change_edge_label_pos = None, IDAddressAppNodes = None)
    #nodeLinkView = tlpgui.createView('Node Link Diagram view' graph_meta)
    #snap_height = 3000
    #snap_width = snap_height * 1.3
    #OptimizedSnapsave(graph, MFN, snap_width)
    
    
    CMP = SortedDictWithValLen(CMP, dsc = True)
    '''
    CMP = {k: v for k, v in sorted(
        CMP.items(), key=lambda item: len(item[1]),reverse = True)}
    temp = {}
    for i,ke in list(enumerate(CMP)):
        temp[i] = CMP.pop(ke)
    CMP = temp
    #for ke in CMP:
        #for node in CMP[ke]:
            #NIC[node] = ke
    '''
    return CMP
    

def Create_Node_Link_Diagram_view(
        graph, node_size_property, show_setting = False, 
        method = None, Apply_3D_layout = True, 
        params_specified = dict(), Coloring_with = "degree", 
        change_edge_label_pos = None, IDAddressAppNodes = None,
        ShowEdgeLabelSwitch = True,
        EdgeLabelPosDisRateFromSource = None):
    
    #print(dir(node_size_property))
    #print(node_size_property.getName())
    if node_size_property.getName() == "degree" or Coloring_with == "degree":
        degree, MaxDegree = Compute_degree_of_graph(graph)
    
    #Map the node sizes to their degree
    sizeMappingParams = tlp.getDefaultPluginParameters("Size Mapping", graph)
    #print(sizeMappingParams)
    #node_size_property = degree
    sizeMappingParams["property"] = node_size_property
    #print("node_size_property.maxvalue is", node_size_property.getNodeMax())
    #print("node_size_property.minvalue is", node_size_property.getNodeMin())
    #if node_size_property.getNodeMax() == 0:
        #return
    if Apply_3D_layout == True:
        sizeMappingParams["depth"] = True #3rd size of 3-dimensional Size
    sizeMappingParams["min size"] = 12
    #if node_size_property.getNodeMax() < 100:
    if method == "GEM (Frick)":
        sizeMappingParams["max size"] = 30
    else:
        sizeMappingParams["max size"] = 100
    graph.applySizeAlgorithm("Size Mapping", viewSize, sizeMappingParams)
    # Apply an FM^3 Layout on it
    fm3pParams = tlp.getDefaultPluginParameters("FM^3 (OGDF)", graph)
    fm3pParams["Unit edge length"] = 100
    fm3pParams["New initial placement"] = False
    #print("fm3p", fm3pParams)
    
    #graph.applySizeAlgorithm("Size Mapping", viewSize, sizeMappingParams)
    #Method_Params = tlp.getDefaultPluginParameters(method, graph)
    #print(Method_Params)
    #graph.applyLayoutAlgorithm(method, viewLayout, Method_Params)
    
    #Create a heat map color scale
    heatMap = tlp.ColorScale([tlp.Color.Green, tlp.Color.Black, tlp.Color.Red])
    
    # Map the node colors to their degree using the heat map color scale
    # Also set the nodes labels to their id
    print("Coloring", graph.getName(), "with", Coloring_with)
    if Coloring_with == "degree":
        
        print("max degree is", degree.getNodeMax())
        color_factor = max(degree.getNodeMax()-degree.getNodeMin(),1)
        #print("color_factor is ", color_factor)
        for n in graph.getNodes():
            pos = (degree[n] - degree.getNodeMin())/color_factor
            viewColor[n] = heatMap.getColorAtPos(pos)
        
    elif Coloring_with == "groupID":
        groupID_set = []
        for n in graph.getNodes():
            groupID_set.append(viewLabel[n][0:4])
        '''
        if LabelType == 'ZMA IDCode':
            for n in graph.getNodes():
                groupID_set.append(viewLabel[n][0:4])
        elif LabelType == 'IP':
            for n in graph.getNodes():
                StringSP = graph['viewLabel'][n].split(".")
                groupID_set.append('.'.join(StringSP[0:2]))
        '''
        #print(dir(tlp.Color)[0:79])
        #tlp_Color_table = [tlp.Color.Amaranth, tlp.Color.Amber, ...]
        tlp_Color_table = dir(tlp.Color)[0:79] #color name str list
        #transform the str list to tlp.Color List
        tlp_Color_table = [getattr(tlp.Color, x) for x in tlp_Color_table]
        groupID_set = sorted(set(groupID_set))
        ColorList = ListFill(len(groupID_set), tlp_Color_table)
        #print(ColorList, ColorList)
        color_table = dict(zip(groupID_set, ColorList))
        LabelType = 'ZMA IDCode'
        if LabelType == 'ZMA IDCode':
            for n in graph.getNodes():
                #pos = (int(viewLabel[n][0:4])-min_groupID)/5
                viewColor[n] = color_table[(viewLabel[n][0:4])]

        elif LabelType == 'IP':
            for n in graph.getNodes():
                StringSP = graph['viewLabel'][n].split(".")
                ColorIndex = ".".join(StringSP[0:2])
                viewColor[n] = color_table[ColorIndex]
        
    # Set border colors values
    viewBorderColor.setAllNodeValue(tlp.Color.Black)
    viewLabelColor.setAllNodeValue(tlp.Color.Black)
    viewLabelBorderColor.setAllNodeValue(tlp.Color.Black)
    
    #Add a border to nodes/edges
    viewBorderWidth.setAllNodeValue(1)
    viewBorderWidth.setAllEdgeValue(1)
    
    #Set nodes shapes
    #viewShape.setAllNodeValue(tlp.NodeShape.Circle)
    #viewShape.setAllNodeValue(tlp.NodeShape.GlowSphere)
    viewShape.setAllNodeValue(tlp.NodeShape.Sphere)
    #print("tlp.NodeShape", dir(tlp.NodeShape))
    
    #Create a Node Link Diagram view and set some rendering parameters
    nodeLinkView = tlpgui.createNodeLinkDiagramView(graph, show = show_setting)
    renderingParameters = nodeLinkView.getRenderingParameters()
    renderingParameters.setViewArrow(True)
    renderingParameters.setViewEdgeLabel(ShowEdgeLabelSwitch)
    renderingParameters.setEdge3D(True)
    renderingParameters.setEdgeColorInterpolate(True)
    renderingParameters.setLabelScaled(True)
    viewLabelPosition = graph.getIntegerProperty("viewLabelPosition")
    viewLabelPosition.setAllEdgeValue(tlp.LabelPosition.Bottom)
    viewLabelColor.setAllEdgeValue(tlp.Color.Red)
    #viewLabelBorderWidth.setAllEdgeValue(10)
    renderingParameters.setMinSizeOfLabel(5)
    graph.applyLayoutAlgorithm("FM^3 (OGDF)", viewLayout, fm3pParams)\

    #method = 'Fast Overlap Removal'
    #method = 'Improved Walker (OGDF)'
    #method = 'Balloon (OGDF)'
    #method = 'Circular (OGDF)'
    #method = 'GRIP'
    #method = 'Hierarchical Tree (R-T Extended)'
    #params_specified['edge length'] = node_size_property
    method = 'Sugiyama (OGDF)'
    #params_specified['transpose vertically'] = False
    params_specified['node distance'] = 5
    #method = 'Dominance (OGDF)' #Can't Use
    #method = 'Hierarchical Graph' #Can't Use
    #method = 'Visibility (OGDF)' #Can't Use
    #method = 'GEM (Frick)'
    #if method == 'GEM (Frick)':
        #edge_length_GEM = Compute_edge_length_GEM(graph)
        #params_specified["edge length"] = edge_length_GEM
    if method != None:
        ApplyLayoutEffect(graph, method, params_specified)
    if change_edge_label_pos != None:
        if method == None:
            fm3pParams["Unit edge length"] = 30
        #renderingParameters.setLabelScaled(False)
        renderingParameters.setMinSizeOfLabel(30)
        #viewFontSize.setAllNodeValue(30)
        #viewFontSize.setAllEdgeValue(25)
        #print(dir(renderingParameters))
        renderingParameters.setLabelsDensity(1000)
        print("Label density", renderingParameters.getLabelsDensity())
        graph.applyLayoutAlgorithm("FM^3 (OGDF)", viewLayout, fm3pParams)
        #print("change_edge_label_pos:", change_edge_label_pos)
        for edge in change_edge_label_pos:
            viewLabelPosition.setEdgeValue(edge, tlp.LabelPosition.Top)
    nodeLinkView.setRenderingParameters(renderingParameters)
    if EdgeLabelPosDisRateFromSource != None:
        SetEdgeLabelPosbyRate(graph, EdgeLabelPosDisRateFromSource)
        
def load_params_specified(params, params_specified):
    result = params
    if params_specified != None:
        for key in params_specified.keys():
            params[key] = params_specified[key]
    return result

def ApplyLayoutEffect(graph, method, params_specified):
    params = tlp.getDefaultPluginParameters(method, graph)
    params = load_params_specified(params, params_specified)
    print(params)
    #params["3D layout"] = True
    #params["edge length"] = 1000
    #print("ApplyLayoutEffect", params, ", method:", method)
    #resultLayout = graph.getLayoutProperty('resultLayout')
    #success = graph.applyLayoutAlgorithm(method, resultLayout, params)
    success = graph.applyLayoutAlgorithm(method, params)    
    #nodeLinkView.setRenderingParameters(renderingParameters)
    return success

def ShowViews(graph,SpreadsheetViewSwitch=True):    
    nodeLinkView = tlpgui.getOpenedViewsWithName('Node Link Diagram view')[0]
    nodeLinkView.setVisible(True)
    nodeLinkView.draw()
    if SpreadsheetViewSwitch == True:
        tlpgui.createView('Spreadsheet view', graph, {'show_nodes': False, 'show_edges': True}) #OK
    #tlpgui.createView('Histogram view', graph_empty)
    #tlpgui.createView('Scatter Plot 2D view', graph_empty)
    #tlpgui.createView('Self Organizing Map view', graph_empty) #OK
    #tlpgui.createView('Parallel Coordinates view', graph_empty) #OK
    #tlpgui.createView('Adjaceny Matrix view', graph_empty)

    
    
if __name__ == '__main__':
    start_time = time.time()
    SimilarityList = [('世卫组织将召开会议评估新型冠状病毒疫情', '越南等四国发生严重洪水导致100多人死亡  联合国正向灾区提供援助物资', 0.71), ('联合国庆祝“全球契约”成立１５周年', '埃塞俄比亚__7名联合国官员被告知在72小时内离开该国', 0.74), ('数千名缅甸罗兴亚人居住在缅孟边境“无人地带”_ 难民署表达关注', '越南等四国发生严重洪水导致100多人死亡  联合国正向灾区提供援助物资', 0.88), ('沙特常驻联合国代表：伊朗如停止干涉别国内政 沙特将保持同其正常关系', '喀麦隆：全球最受忽视的人道主 义危机之一', 0.78), ('联合国秘书长古特雷斯：莫桑比克是气候变化的受害者  有权要求国际社会给予支持', '潘基文秘书长就南苏丹建国在《纽约时报》发表专栏文章', 0.74), ('联合国秘书长古特雷斯：莫桑比克是气候变化的受害者  有权要求国际社会给予支持', '中非共和国大选前暴力持续升级 三名联合国维和人员在袭击中牺牲', 0.74), ('联合国秘书长古特雷斯：莫桑比克是气候变化的受害者  有权要求国际社会给予支持', '潘基文访问肯尼亚：见证非洲可持续交通转型计划诞生  发起结束女性生殖器切割全球媒体运动', 0.74), ('联合国秘书长古特雷斯：莫桑比克是气候变化的受害者  有权要求国际社会给予支持', '联合国副秘书长访问刚果民主共和国 呼吁确保决策层中的性别平等', 0.74), ('联大特别会议关注新冠大流行后的恢复', '埃塞俄比亚__7名联合国官员被告知在72小时内离开该 国', 0.8), ('联合国人权专家敦促刚果（金）恢复互联网服务', '联合国副秘书长访问刚果民主共和国 呼吁确保决策层中的性别平等', 0.93), ('联合国人权专家敦促刚果（金）恢复互联网服务', '南北苏丹恢复和谈 南苏丹欢迎苏丹开始从阿卜耶伊撤军', 0.77), ('联 合国人权专家敦促刚果（金）恢复互联网服务', '环境署：肯尼亚动乱使旅游业损失严重', 0.86), ('联合国人权专家敦促刚果（金）恢复互联网服务', '潘基文秘书长就南苏丹建国在《纽约时报》发表专栏文章', 0.93), ('联合国人权专家敦促刚果（金）恢复互联网服务', '世卫组织：马达加斯加报告1800多例鼠疫相关病例、127人死亡', 0.8), ('联合国人权专家敦促刚果（金）恢复互联网服务', '中非共和国大选前暴力持续升级 三名联合国维和人员在袭击中牺牲', 0.93), ('联合国人权专家敦促刚果（金）恢复互联网服务', '联合国 人权专家谴责针对苏丹人权活动家的恐吓、骚扰和不公指控', 0.82), ('联合国人权专家敦促刚果（金）恢复互联网服务', '联合国宣布索马里脊髓灰质炎传播正式结束 但预防措施仍然必要', 0.8), ('联合国人权专家敦促刚果（金）恢复互联网服务', '潘基文访问肯尼亚：见证非洲可持续交通转型计划诞生  发起结束女性生殖器切割全球媒体运动', 0.93), ('联合国人权专家敦促刚果（金）恢复互联网服务', '安理会决议延长达尔富尔问题专家小组任期十三个月', 0.88), ('联合国人权专家敦促刚果（金）恢复互联网服务', '联合国植树纪念已故诺贝尔和平奖得主、联合国和平使者马塔伊', 0.8), ('联合国人权专家敦促刚果（金）恢复互联网服务', '难民署大力援助索 马里境内外逃难饥民', 0.77), ('联合国人权专家敦促刚果（金）恢复互联网服务', '联合国达尔富尔特使赞赏中国对他工作的支持', 0.71), ('特别代表库比什：解放摩苏尔战役稳步取得胜利 伊拉克人道危机急需国际救援', '联合国秘书长古特雷斯呼吁中亚国家加强多 层面区域反恐合作', 0.71), ('特别代表库比什：解放摩苏尔战役稳步取得胜利 伊拉克人道危机急需国际救援', '联合国高级顾问：大 规模撤离叙利亚平民是“绝望时期的绝望措施”', 0.8), ('特别代表库比什：解放摩苏尔战役稳步取得胜利 伊拉克人道危机急需国际救援', '联合国：叙利亚人道危机应对行动难以满足与日俱增的救援需求', 0.71), ('特别代表库比什：解放摩苏尔战役稳步取得胜利 伊 拉克人道危机急需国际救援', '叙利亚难民大量涌入伊拉克  联合国机构专机运送救援物资', 0.8), ('联合国人权专家：白俄罗斯必须 停止对和平抗议者的攻击', '特别代表库比什：解放摩苏尔战役稳步取得胜利 伊拉克人道危机急需国际救援', 0.78), ('联合国秘书长 古特雷斯呼吁中亚国家加强多层面区域反恐合作', '难民署预计今年全球被迫背井离乡人数将超过6000万', 0.71), ('联合国秘书长古特雷斯呼吁中亚国家加强多层面区域反恐合作', '旧金山70周年纪念仪式：  潘基文强调《联合国宪章》将继续指引世界走向更加美好未来', 0.71), ('联合国秘书长古特雷斯呼吁中亚国家加强多层面区域反恐合作', '欧洲和中亚唯一保留死刑国家白俄罗斯继续执行死刑  联合国人权专家表示谴责', 0.77)]
    #print("SimilarityList",SimilarityList)
    
    graph = BuildGraph(SimilarityList)
    set_groupID_Property(graph)
    os.system("pause")
    '''
    ConstructClusterMetaNodeGraph = True
    if ConstructClusterMetaNodeGraph == True:
        ClusterMethod = 'Louvain'
        ClusterMetaNodeGraph(graph, ClusterMethod)
    Create_Node_Link_Diagram_view(
        graph, 
        #node_size_property = degree, 
        node_size_property = graph.getDoubleProperty(ClusterMethod),
        show_setting = False, method = None, 
        Apply_3D_layout = True, params_specified = dict(), 
        Coloring_with = "groupID", change_edge_label_pos = None, 
        IDAddressAppNodes = None)
    #Create_Node_Link_Diagram_view(
        #graph, degree, True, None, True, {"3D layout": False}, global_coloring, None)
    ShowViews(graph)
    '''