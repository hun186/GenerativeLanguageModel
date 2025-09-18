# coding=utf-8
import collections
import random

try:
    from utils.utilities import flattenList
except:
    from utilities import flattenList
def ComputeComponent(edges):
    #nodes = [edge[0],edge[1] for edge in edges]
    nodes = set(flattenList(edges))
    
    CMP = {}
    NIC = {}
    nN = len(nodes)
    for i,x in enumerate(nodes):
        NIC[x] = i
        CMP[i] = [x]
    for x,y in edges:
        if NIC[x] != NIC[y]:
            if len(CMP[NIC[x]]) >= len(CMP[NIC[y]]):
                CMPDel = NIC[y]
                CMPLeft = NIC[x]
            else:
                CMPDel = NIC[x]
                CMPLeft = NIC[y]
            for node in CMP[CMPDel]:
                NIC[node] = CMPLeft
            CMP[CMPLeft].extend(CMP[CMPDel])
            del(CMP[CMPDel])
    #for edge in edges
    #print("CMP b4",CMP)
    #for ke in CMP:
        #CMP['C'+str(ke)] = CMP.pop(ke)
    #CMP = {0: ['阿富汗喀布尔发生连环爆炸造成众多记者警察死伤   联合国对袭击表示强烈谴责.txt', '难民署警告_ 阿富汗的人道主义危机迫在眉睫.txt', ' 联合国：塔利班在阿富汗选举期间制造的暴力事件导致平民死亡人数创下新高.txt'], 3: ['德米斯图拉：新一轮叙利亚和谈议程主要集中在政治过渡、政府治理和制定新宪法.txt', '独立国际调查委员会报告：叙利亚人权状况急剧恶化.txt', '俄、中行使否决权  安理会有关叙利亚化学武器问题决议草案未获通过.txt', '教科文组织总干事对冲突导致叙 利亚文化遗产进一步破坏深表震惊.txt', '联合国人口基金：加沙人口未来３０年将急剧增长并加重经济困境.txt', '联合国秘书长：巴勒斯坦宣布举行选举是走向团结的“关键 一步”.txt', '一般性辩论：伊朗总统鲁哈尼告诫不能利用极端团体来对付敌对国家.txt', '联合国特使将前往索契出席俄罗斯主持的叙利亚和谈.txt', '叙利亚300万平民受困战火之中   安理会急需团结一致以免引发“人道灾难”.txt', '扎伊德：加沙的苦难是人为且完全可避免的  实现和平的承诺已经拖了太久.txt', '联合国政治事务副秘书长：国际社会对未能结束叙利亚战争感到沮丧.txt'], 5: ['联合国人权专家呼吁让所有劳动者都能获得安全和健康的工作条件.txt', '艾滋病规划署谴责滥用紧急权力来针对边缘化和脆弱人群.txt'], 20: ['潘基文：国际社会需要解决冲突根源  结束刚果（金）暴力循环.txt', '联合国：中非共和国人道行动未来三个月需要１.５２亿美元经费.txt', '联合国驻地人道协调员：非洲萨赫勒地区２０１３年仍面临多重危机.txt', '联合国：马里大选在即\u3000执行《和平协议》仍是优先事项.txt', '人权高专皮莱：埃及冲突双方的对立做法 将导致灾难.txt', '刚果（金）埃博拉疫情暴发一周年 __联合国呼吁加大行动力度.txt', '粮食计划署_ 津巴布韦面临十年来最严重的饥饿危机.txt', '联合国欢迎非洲特别法庭对乍得前总统哈布雷做出“历史性”判决.txt', '联合国和非盟即将展开达尔富尔第二阶段混合维和部署.txt', '环境署调查欧洲危险废物非法出口科特迪瓦.txt', '人权高专痛 惜国际社会没有足够重视刚果（金）开赛地区的践踏人权暴行.txt'], 29: ['非洲新冠死亡人数比上周激增 40%多.txt', '【专题报道】“中国向世界展示了疫情的发展轨迹是可 以改变的”——专访世卫组织驻华代表高力.txt', '【专题报道】联合国的巾帼英雄——记25位来自非洲的女性高级官员.txt']}
    CMP = {k: v for k, v in sorted(
        CMP.items(), key=lambda item: len(item[1]),reverse = True)}
    temp = {}
    for i,ke in list(enumerate(CMP)):
        temp[i] = CMP.pop(ke)
    CMP = temp
    for ke in CMP:
        for node in CMP[ke]:
            NIC[node] = ke
    return CMP,NIC
'''
edges = [[0, 1], [1, 0], [3, 1], [4, 0]]
edges = [['a','b'],['b','e'],['f','g'],['h','h']]
edges = []
CMP,NIC = ComputeComponent(edges)

nDigit = len(str(max(CMP))) if len(CMP)>0 else 0
for ke in list(CMP):
    for node in CMP[ke]:
        NIC[node] = f"Group {ke:{nDigit}d}"
    #CMP[f"Group {ke}"] = CMP.pop(ke)
    CMP[f"Group {ke:{nDigit}d}"] = CMP.pop(ke)


print(CMP.keys())
print("NIC af",{k:v for k,v in NIC.items() if "Group" not in str(v)})
'''


#=======Louvain method==========================


def build_graph(WeightEdgeList):
    #edges = [(src,des,weight),...]
    G = collections.defaultdict(dict)
    for ed in WeightEdgeList:
        v_i = ed[0]
        v_j = ed[1]
        w = float(ed[2])
        #w = 1
        G[v_i][v_j] = w
        G[v_j][v_i] = w
    return G

def load_graph(path,sep=","):
    if path.endswith(".tsv"):
        sep="\t"
    elif path.endswith(".csv"):
        sep=","
    else:
        sep=","
    G = collections.defaultdict(dict)
    with open(path,'rt',encoding='utf-8') as text:
        for line in text:
            #print("line",line)
            #raise Exception
            vertices = line.strip().split(sep)
            #v_i = int(vertices[0])
            #v_j = int(vertices[1])
            v_i = vertices[0]
            v_j = vertices[1]
            w = float(vertices[2])
            #w = 1
            G[v_i][v_j] = w
            G[v_j][v_i] = w
    return G

class Vertex():
    def __init__(self, vid, cid, nodes, k_in=0):
        self._vid = vid
        self._cid = cid
        self._nodes = nodes
        self._kin = k_in  # 結點內部的邊的權重

class Louvain():
    def __init__(self, G):
        self._G = G
        self._m = 0  # 邊數量
        self._cid_vertices = {}  # 需維護的關於社區的信息(社區編號,其中包含的結點編號的集合)
        self._vid_vertex = {}  # 需維護的關於結點的信息(結點編號，相應的Vertex實例)
        for vid in self._G.keys():
            self._cid_vertices[vid] = set([vid])
            self._vid_vertex[vid] = Vertex(vid, vid, set([vid]))
            self._m += sum([1 for neighbor in self._G[vid].keys() if neighbor > vid])

    def first_stage(self):
        mod_inc = False  # 用於判斷算法是否可終止
        visit_sequence = self._G.keys()
        random.shuffle(list(visit_sequence))
        while True:
            can_stop = True  # 第一階段是否可終止
            for v_vid in visit_sequence:
                v_cid = self._vid_vertex[v_vid]._cid
                k_v = sum(self._G[v_vid].values()) + self._vid_vertex[v_vid]._kin
                cid_Q = {}
                for w_vid in self._G[v_vid].keys():
                    w_cid = self._vid_vertex[w_vid]._cid
                    if w_cid in cid_Q:
                        continue
                    else:
                        tot = sum(
                            [sum(self._G[k].values()) + self._vid_vertex[k]._kin for k in self._cid_vertices[w_cid]])
                        if w_cid == v_cid:
                            tot -= k_v
                        k_v_in = sum([v for k, v in self._G[v_vid].items() if k in self._cid_vertices[w_cid]])
                        delta_Q = k_v_in - k_v * tot / self._m  # 由於只需要知道delta_Q的正負，所以少乘了1/(2*self._m)
                        cid_Q[w_cid] = delta_Q

                cid, max_delta_Q = sorted(cid_Q.items(), key=lambda item: item[1], reverse=True)[0]
                if max_delta_Q > 0.0 and cid != v_cid:
                    self._vid_vertex[v_vid]._cid = cid
                    self._cid_vertices[cid].add(v_vid)
                    self._cid_vertices[v_cid].remove(v_vid)
                    can_stop = False
                    mod_inc = True
            if can_stop:
                break
        return mod_inc

    def second_stage(self):
        cid_vertices = {}
        vid_vertex = {}
        for cid, vertices in self._cid_vertices.items():
            if len(vertices) == 0:
                continue
            new_vertex = Vertex(cid, cid, set())
            for vid in vertices:
                new_vertex._nodes.update(self._vid_vertex[vid]._nodes)
                new_vertex._kin += self._vid_vertex[vid]._kin
                for k, v in self._G[vid].items():
                    if k in vertices:
                        new_vertex._kin += v / 2.0
            cid_vertices[cid] = set([cid])
            vid_vertex[cid] = new_vertex

        G = collections.defaultdict(dict)
        for cid1, vertices1 in self._cid_vertices.items():
            if len(vertices1) == 0:
                continue
            for cid2, vertices2 in self._cid_vertices.items():
                if cid2 <= cid1 or len(vertices2) == 0:
                    continue
                edge_weight = 0.0
                for vid in vertices1:
                    for k, v in self._G[vid].items():
                        if k in vertices2:
                            edge_weight += v
                if edge_weight != 0:
                    G[cid1][cid2] = edge_weight
                    G[cid2][cid1] = edge_weight

        self._cid_vertices = cid_vertices
        self._vid_vertex = vid_vertex
        self._G = G

    def get_communities(self):
        communities = []
        for vertices in self._cid_vertices.values():
            if len(vertices) != 0:
                c = set()
                for vid in vertices:
                    c.update(self._vid_vertex[vid]._nodes)
                communities.append(c)
        return communities

    def execute(self):
        iter_time = 1
        while True:
            iter_time += 1
            mod_inc = self.first_stage()
            if mod_inc:
                self.second_stage()
            else:
                break
        return self.get_communities()
    
def build_Louvain(WeightEdgeList=[],WeightEdgeFile=""):
    print("Start to run Louvain method")
    #自動偵測是否輸入檔名，且未指定其為檔名，並進行校正。
    if type(WeightEdgeList) == str:
        WeightEdgeFile = WeightEdgeList
        WeightEdgeList = []
    if WeightEdgeFile != "":
        G = load_graph(WeightEdgeFile)
    elif WeightEdgeList != []:
        G = build_graph(WeightEdgeList)
    else:
        MES = "There is NO input WeightEdgeFile or WeightEdgeList to build graph. ABORT!"
        print(MES)
    algorithm = Louvain(G)
    communities = algorithm.execute()
    # 按照社區大小從大到小排序輸出
    communities = sorted(communities, key=lambda b: -len(b)) # 按社區大小排序
    print("Finished running Louvain method")
    return communities


if __name__ == '__main__':
    SimilarityFile = r'SimilarityEdge.txt'
    SimilarityFile = r'Similarity.tsv'

    communities = build_Louvain(SimilarityFile)
    count = 0
    for communitie in communities:
        count += 1
        print("Group", count, " ", communitie)
    print([len(com) for com in communities])