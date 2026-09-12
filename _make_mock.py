# -*- coding: utf-8 -*-
import os

base = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                    "_mock_logs", "Ultrasonicwelding2")
os.makedirs(base, exist_ok=True)

samples = {
    "WCF/2026-07-20_09_12.txt": """[2026-07-20 11:14:05]请求开始 - CommandId: WipOrderRequest, MessageGuid: b4a66851-dc68-4199-8dc4-22851ed0db22, 请求时间: 2026-07-20 11:14:05.567, 请求数据: {"Software":"YFJG","EquipmentCode":"P08F2CHJI01"}
[2026-07-20 11:14:05]请求成功 - CommandId: WipOrderRequest, MessageGuid: b4a66851-dc68-4199-8dc4-22851ed0db22, 耗时: 124.00ms, 响应数据: {"ResultFlag":true,"MOMMessage":"OK","WipOrder":[{"WipOrderNo":"00007000216203"}]}
[2026-07-20 11:15:36]请求开始 - CommandId: EqptWipOrder, 请求数据: {"Software":"YFJG","EquipmentCode":"P08F2CHJI01","EmployeeNo":"T040598","WipOrderNo":"00007000216203"}
[2026-07-20 11:15:36]请求成功 - CommandId: EqptWipOrder, 耗时: 154.01ms, 响应数据: {"ResultFlag":false,"MOMMessage":"上料失败:库存不足"}
""",
    "设备心跳接口/2026-07-20_09_12.txt": "\n".join(
        '[2026-07-20 {:02d}:17:54]上传Json：{{"Software":"YFJG","EquipmentCode":"P08F2CHJI01"}}\n[2026-07-20 {:02d}:17:54]返回数据：{{"ResultFlag":true,"MOMMessage":"OK","KeyFlag":"0"}}'.format(h, h)
        for h in range(11, 14)),
    "条码校验/2026-07-23_13_16.txt": """[2026-07-23 16:50:58]条码【C33F2WAJI012671601015】品种：A
[2026-07-23 16:51:14]条码【C33F2WBJI022671600747】品种：B
[2026-07-23 16:54:23]条码【C33F2WAJI012671601014】品种：A
""",
    "电芯入站接口/2026-07-23_13_16.txt": """[2026-07-23 16:50:58]上传Json：{"Software":"YFJG","EquipmentCode":"P08F2CHJI01","SerialNos":[{"SerialNo":"C33F2WAJI012671601015","GetProductTypeFlag":true}]}
[2026-07-23 16:50:58]返回数据：{"ResultFlag":true,"MOMMessage":"OK","SerialNos":[{"SerialNo":"C33F2WAJI012671601015","Result":true,"ProductType":"A"}]}
""",
    "sys/2026-07-20_09_12.txt": """[2026-07-20 11:12:55]在地址ns=4;s=A_MES_Code_Send读取
[2026-07-20 11:12:55]在地址ns=4;s=A_MES_Check_Results1写入2
""",
}

for p, content in samples.items():
    d = os.path.join(base, os.path.dirname(p))
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(base, p), "w", encoding="utf-8") as f:
        f.write(content)
print("mock created")
