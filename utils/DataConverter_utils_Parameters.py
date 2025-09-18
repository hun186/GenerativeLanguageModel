#根節點:Uncertainty,Scrap,Informative,Keyword Neg Filter
ZeroSubtreeRootList = [
    "Spacetime Singularity Of Tree", #超根節點
    "Uncertainty", #根節點
    "Uncertainty_AK4", #亞根節點
    "AK4", #根節點
    "Research Paper", #0907，根節點
    "Medicine",
    "Pharmacology", #0920
    "Pharmacy", #0920
    #"Entomology", #0906
    "Biology", #0907
    "Psychology",
    #"Telecommunication Technical Documentation",
    "Telecommunication", #0320
    #"Logistics Industry",
    "Geoscience",
    #"COVID-19 IPC-Online Learning",
    "PRC-Law",
    "Call For Papers",
    "Automotive Industry",
    "CN Hospitality Industry Development",
    "Popular Science",
    "Navigational Warning-Routine Affairs", #2022-0907
    #"COVID-19 Vaccine Clinical Report", #2022-0919
    "Community Affairs", #2022-0919
    #Routine Safety Propaganda, #移到Uncertainty
    "Keyword Filter", #2022-1103
    #"COVID-19 IPC For Community-Inspirational Story", #2022-1105
    "Aviation Safety", #2022-1109
    "Autopilot", #2022-1109
    "UKF-Uncertain Report", #2022-1111
    "CERP-Non-Key Industry", #2022-1115
    #"COVID-19 IPC-Isolation And Quarantine", #2022-1220
    "CN Equity Research Report", #2022-1226
    "Energy-Efficient Product Procurement", #2022-1229
    "Formal Science", #2023-0107
    "Artificial Intelligence Application-Non-Key AI Application", #2023-0107
    "Manufacturing Process Optimization", #2023-0107
    "CPC Party Development-Inspirational Story", #2023-0110
    "Student Exchange Program Application", #2023-0206
    "Climate Refugees", #2023-0215
    "Energy-Efficient Product Procurement", #2023-0215
    "Global Law", #2023-0220
    "CN Company Management Right", #2023-0220
    "Green Economy", #2023-0301
    "Population", #2023-0321
    "RU-UA MC-Humanitarian Crisis-Personal Story", #2023-0327
    #"Unimportant Academic Workshop", #2023-0427
    "Academic Workshop", #2023-0601
    "Africa Affairs", #2023-0917
    "Education", #2023-0917
    "Unimportant Minutes Of PRC Government Meeting", #2023-1019
    "Minutes Of PRC Government Meeting-Attendance List", #2023-1019
    "Artificial Intelligence", #2023-1108
    "Battery Technology", #2024-0424
    "Distributed Cryptocurrency", #2024-0425
    "Human Rights", #2024-0619
    "Disaster Management", #2024-0619
    "Insurance Analysis", #2024-0716
    "Insurance Industry", #2024-0815
    "Agriculture And Forestry And Fishery And Animal Husbandry", #2024-0819
    "US Treasury Bonds", #2024-1111
    "Cybersecurity", #2024-1206
    ]


GeneralBinInfoScoreSumLBD = 500

SPECNodeScoreTable = {
    "Scrap":{"NodeScore":-GeneralBinInfoScoreSumLBD//2,"ChildBonus":-10,"SPEC":True}, #根節點
    "Informative":{"NodeScore":100,"ChildBonus":10,"SPEC":True}, #根節點
    "Scrap_AK4":{"NodeScore":-GeneralBinInfoScoreSumLBD//2,"ChildBonus":-10,"SPEC":True}, #亞根節點
    "Informative_AK4":{"NodeScore":100,"ChildBonus":10,"SPEC":True}, #亞根節點
    "Keyword Neg Filter":{"NodeScore":-5*GeneralBinInfoScoreSumLBD,"ChildBonus":-10,"SPEC":True}, #根節點
    "TMKF-Positive Keyword Filter":{"NodeScore":GeneralBinInfoScoreSumLBD//2+1,"ChildBonus":10**(-6),"SPEC":True}, #2022-1103
    "TMKF-Negative Keyword Filter":{"NodeScore":-GeneralBinInfoScoreSumLBD,"ChildBonus":-10,"SPEC":True}, #2022-1103
    #"United Front":{"NodeScore":200,"ChildBonus":50,"SPEC":True},
    "Confucius Institute":{"NodeScore":GeneralBinInfoScoreSumLBD//2+1,"ChildBonus":50,"SPEC":True}, #2022-1004
    "Navigational Warning-Traditional Security":{"NodeScore":GeneralBinInfoScoreSumLBD//2+1,"ChildBonus":50,"SPEC":True}, #2022-1111
    "Navigational Warning-Non Traditional Security":{"NodeScore":GeneralBinInfoScoreSumLBD//2+1,"ChildBonus":50,"SPEC":True}, #2022-1111
    "Navigational Warning-Emergency Event":{"NodeScore":GeneralBinInfoScoreSumLBD//2+1,"ChildBonus":50,"SPEC":True}, #2024-0325
    "DMDR-CN Disaster Report":{"NodeScore":GeneralBinInfoScoreSumLBD//2+1,"ChildBonus":50,"SPEC":True},
    "CPC Meeting":{"NodeScore":150,"ChildBonus":50,"SPEC":True},
    "IP-Patent Application":{"NodeScore":-100,"ChildBonus":-10**(-6),"SPEC":True},
    "Financial Statements":{"NodeScore":-20,"ChildBonus":-10,"SPEC":True}, #2022-1024
    "Clinical Report":{"NodeScore":-20,"ChildBonus":-10,"SPEC":True}, #2022-1128
    "Shareholders Meeting":{"NodeScore":-20,"ChildBonus":-10,"SPEC":True}, #2022-1129
    "Internet Of Things":{"NodeScore":-20,"ChildBonus":-10,"SPEC":True}, #2023-0308
    "CERP-Key Industry":{"NodeScore":130,"ChildBonus":10,"SPEC":True}, #2022-1226
    "Logistics Industry":{"NodeScore":-20,"ChildBonus":-1,"SPEC":True}, #2023-0308
    "Maritime Industry":{"NodeScore":-20,"ChildBonus":-1,"SPEC":True}, #2023-0308
    "UAS-News Translation Assignment":{"NodeScore":-500,"ChildBonus":-1,"SPEC":True}, #2023-0412
    #"Important Academic Workshop":{"NodeScore":100,"ChildBonus":50,"SPEC":True}, #2023-0427
    "Important Academic Workshop":{"NodeScore":150,"ChildBonus":10,"SPEC":True}, #2023-0601
    "Cyberattack":{"NodeScore":150,"ChildBonus":10,"SPEC":True}, #2024-1206
    }