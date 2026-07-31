# templates/ 导航索引

本目录是**文种专属的写作模板**，共 6 份覆盖 9 个常用文种。每份的结构统一为：适用场景 → 标题格式 → 正文结构 → **JSON sections 示例** → 写作要点。
其中 JSON sections 示例可以直接照着填，交给 docx-report 的 `build render` 渲染成 Word。

| 文件 | 覆盖文种 | docx-report type | 行文方向 |
|------|---------|-----------------|---------|
| `notice.md` | 通知 / 通报 / 意见 | notice | 下行（意见可上行/平行） |
| `report.md` | 报告 | report | 上行 |
| `letter.md` | 函（商洽/询问/答复/请批/告知） | letter | 平行 |
| `resolution.md` | 请示 / 批复（一份里两节） | resolution，subtype 分请示与批复 | 请示上行 / 批复下行 |
| `minutes.md` | 会议纪要 | minutes | 无主送机关，不按普通行文处理 |
| `decision.md` | 决定 | decision | 下行 |

## 怎么用

1. 先确定文种，再只读对应的那一份，不要把 6 份都加载进来。
2. 照「正文结构」搭骨架，照「JSON sections 示例」填字段名——字段名以示例为准，别自创。
3. 「写作要点」是该文种最容易写错的地方（比如函要平等协商语气、纪要不标主送机关），动笔前扫一眼。
4. 请示与批复成对出现，二者都写时读 `resolution.md` 一份即可。
