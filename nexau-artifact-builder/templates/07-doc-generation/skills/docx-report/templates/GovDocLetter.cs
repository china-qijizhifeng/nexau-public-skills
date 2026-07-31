// GovDocLetter.cs — 信函格式模板（只读参考，不要直接修改）
// 适用于：函（商洽函、询问函、答复函、催办函、邀请函等）
// 与标准红头文件的区别：
//   - 发文机关名称后加"函"字，不加"文件"
//   - 发文字号置于武文线（红色分隔线）下方居左
//   - 无份号、密级、紧急程度
//   - 版记更简洁
//
// 用法：agent 在 cwd 下创建 Program.cs，参考本文件编写，然后执行构建

using DocumentFormat.OpenXml;
using DocumentFormat.OpenXml.Packaging;
using DocumentFormat.OpenXml.Wordprocessing;

string outputFile = args.Length > 0 ? args[0] : "letter.docx";

// ── 函件元数据 ──
string govOrg = "XX市政务服务管理局";
string docNum = "X政务函〔2025〕12号";
string docTitle = "关于协助核查政务服务事项办理情况的函";
string sendTo = "XX市大数据中心";
string docDate = "2025\u5E742\u670812\u65E5";
string ccOrgs = "市发展改革委";

const string GOV_RED = "C81414";
const string BLACK = "000000";
const uint A4W = 11906;
const uint A4H = 16838;
const int MTop = 2098;
const int MBot = 1984;
const int MLeft = 1588;
const int MRight = 1474;

using var doc = WordprocessingDocument.Create(outputFile, WordprocessingDocumentType.Document);
var mainPart = doc.AddMainDocumentPart();
mainPart.Document = new Document();
var body = new Body();

AddStyles(mainPart);

// ══════════════════════════════════════════════
// 版头：机关名称 + "函" 字（信函格式特有）
// ══════════════════════════════════════════════
body.Append(new Paragraph(
    new ParagraphProperties(
        new Justification { Val = JustificationValues.Center },
        new SpacingBetweenLines { Before = "800", After = "100" }
    ),
    new Run(
        new RunProperties(
            new RunFonts { Ascii = "FZXiaoBiaoSong-B05", HighAnsi = "FZXiaoBiaoSong-B05", EastAsia = "FZXiaoBiaoSong-B05" },
            new FontSize { Val = "44" }, new FontSizeComplexScript { Val = "44" },
            new Color { Val = GOV_RED }
        ),
        new Text(govOrg + "\u51FD")
    )
));

// ── 红色武文线（信函用细线） ──
body.Append(new Paragraph(
    new ParagraphProperties(
        new ParagraphBorders(
            new BottomBorder { Val = BorderValues.Single, Size = 4, Color = GOV_RED, Space = 1 }
        ),
        new SpacingBetweenLines { Before = "0", After = "0" }
    )
));

// ── 发文字号（信函格式：居左） ──
body.Append(new Paragraph(
    new ParagraphProperties(
        new Justification { Val = JustificationValues.Left },
        new SpacingBetweenLines { Before = "100", After = "200" }
    ),
    new Run(
        new RunProperties(
            new RunFonts { Ascii = "FangSong", HighAnsi = "FangSong", EastAsia = "FangSong" },
            new FontSize { Val = "32" }, new FontSizeComplexScript { Val = "32" }
        ),
        new Text(docNum)
    )
));

// ══════════════════════════════════════════════
// 标题
// ══════════════════════════════════════════════
body.Append(new Paragraph(
    new ParagraphProperties(
        new Justification { Val = JustificationValues.Center },
        new SpacingBetweenLines { Before = "200", After = "300", Line = "570", LineRule = LineSpacingRuleValues.Exact }
    ),
    new Run(
        new RunProperties(
            new RunFonts { Ascii = "FZXiaoBiaoSong-B05", HighAnsi = "FZXiaoBiaoSong-B05", EastAsia = "FZXiaoBiaoSong-B05" },
            new FontSize { Val = "44" }, new FontSizeComplexScript { Val = "44" }
        ),
        new Text(docTitle)
    )
));

// ══════════════════════════════════════════════
// 主送机关
// ══════════════════════════════════════════════
body.Append(CreateBodyPara(sendTo + "\uFF1A", bold: false, indent: false));

// ══════════════════════════════════════════════
// 正文
// ══════════════════════════════════════════════
body.Append(CreateBodyPara(
    "根据政务信息资源共享管理相关规定，" +
    "有关事项办理情况核查需要多部门协作。" +
    "现就有关事项函告如下："
));

body.Append(CreateBodyPara(
    "一、请协助查询示例事项的办理状态（业务编号：CASE-2025-0001）。",
    bold: false, indent: true
));

body.Append(CreateBodyPara(
    "二、请于收到本函后5个工作日内将查询结果反馈至我局业务协调处。",
    bold: false, indent: true
));

body.Append(CreateBodyPara(
    "如有疑问，请与我局业务协调处联系，" +
    "\u8054\u7CFB\u7535\u8BDD\uFF1A021-XXXXXXXX\u3002"
));

// ══════════════════════════════════════════════
// 落款
// ══════════════════════════════════════════════
body.Append(new Paragraph(new ParagraphProperties(new SpacingBetweenLines { Before = "600" })));

body.Append(new Paragraph(
    new ParagraphProperties(
        new Justification { Val = JustificationValues.Right },
        new SpacingBetweenLines { After = "100", Line = "570", LineRule = LineSpacingRuleValues.Exact }
    ),
    new Run(
        new RunProperties(
            new RunFonts { Ascii = "FangSong", HighAnsi = "FangSong", EastAsia = "FangSong" },
            new FontSize { Val = "32" }, new FontSizeComplexScript { Val = "32" }
        ),
        new Text(govOrg)
    )
));

body.Append(new Paragraph(
    new ParagraphProperties(
        new Justification { Val = JustificationValues.Right },
        new SpacingBetweenLines { After = "200", Line = "570", LineRule = LineSpacingRuleValues.Exact }
    ),
    new Run(
        new RunProperties(
            new RunFonts { Ascii = "FangSong", HighAnsi = "FangSong", EastAsia = "FangSong" },
            new FontSize { Val = "32" }, new FontSizeComplexScript { Val = "32" }
        ),
        new Text(docDate)
    )
));

// ══════════════════════════════════════════════
// 版记（信函格式简化版）
// ══════════════════════════════════════════════
body.Append(new Paragraph(
    new ParagraphProperties(
        new ParagraphBorders(
            new TopBorder { Val = BorderValues.Single, Size = 4, Color = GOV_RED, Space = 1 }
        ),
        new SpacingBetweenLines { Before = "600", After = "0" }
    ),
    new Run(
        new RunProperties(
            new RunFonts { Ascii = "FangSong", HighAnsi = "FangSong", EastAsia = "FangSong" },
            new FontSize { Val = "24" }, new FontSizeComplexScript { Val = "24" }
        ),
        new Text("\u6284\u9001\uFF1A" + ccOrgs + "\u3002")
    )
));

body.Append(new Paragraph(
    new ParagraphProperties(
        new ParagraphBorders(
            new BottomBorder { Val = BorderValues.Single, Size = 4, Color = GOV_RED, Space = 1 }
        ),
        new SpacingBetweenLines { Before = "0", After = "0" }
    )
));

// ══════════════════════════════════════════════
// 页脚 + 页面设置
// ══════════════════════════════════════════════
var footerPart = mainPart.AddNewPart<FooterPart>();
var footerId = mainPart.GetIdOfPart(footerPart);

var footerPara = new Paragraph(
    new ParagraphProperties(new Justification { Val = JustificationValues.Center })
);
footerPara.Append(new Run(
    new RunProperties(
        new RunFonts { Ascii = "FangSong", HighAnsi = "FangSong", EastAsia = "FangSong" },
        new FontSize { Val = "24" }, new FontSizeComplexScript { Val = "24" }
    ),
    new Text("\u2014 ") { Space = SpaceProcessingModeValues.Preserve }
));
footerPara.Append(new Run(new FieldChar { FieldCharType = FieldCharValues.Begin }));
footerPara.Append(new Run(new FieldCode(" PAGE ")));
footerPara.Append(new Run(new FieldChar { FieldCharType = FieldCharValues.Separate }));
footerPara.Append(new Run(new Text("1")));
footerPara.Append(new Run(new FieldChar { FieldCharType = FieldCharValues.End }));
footerPara.Append(new Run(
    new RunProperties(
        new RunFonts { Ascii = "FangSong", HighAnsi = "FangSong", EastAsia = "FangSong" },
        new FontSize { Val = "24" }, new FontSizeComplexScript { Val = "24" }
    ),
    new Text(" \u2014") { Space = SpaceProcessingModeValues.Preserve }
));
footerPart.Footer = new Footer(footerPara);

body.Append(new SectionProperties(
    new FooterReference { Type = HeaderFooterValues.Default, Id = footerId },
    new PageSize { Width = A4W, Height = A4H },
    new PageMargin { Top = MTop, Bottom = MBot, Left = (uint)MLeft, Right = (uint)MRight, Header = 720, Footer = 720 }
));

mainPart.Document.Append(body);
doc.Save();
Console.WriteLine($"\u2705 \u51FD\u4EF6\u751F\u6210\u5B8C\u6210\uFF1A{outputFile}");

// ══════════════════════════════════════════════
// 辅助方法
// ══════════════════════════════════════════════

static Paragraph CreateBodyPara(string text, bool bold = false, bool indent = true)
{
    var pProps = new ParagraphProperties(
        new Justification { Val = JustificationValues.Both },
        new SpacingBetweenLines { Line = "570", LineRule = LineSpacingRuleValues.Exact, After = "0" }
    );
    if (indent) pProps.Append(new Indentation { FirstLine = "640" });
    var rProps = new RunProperties(
        new RunFonts { Ascii = "FangSong", HighAnsi = "FangSong", EastAsia = "FangSong" },
        new FontSize { Val = "32" }, new FontSizeComplexScript { Val = "32" }
    );
    if (bold) rProps.Append(new Bold());
    return new Paragraph(pProps, new Run(rProps, new Text(text)));
}

static void AddStyles(MainDocumentPart mainPart)
{
    var stylesPart = mainPart.AddNewPart<StyleDefinitionsPart>();
    stylesPart.Styles = new Styles();

    stylesPart.Styles.Append(new Style(
        new StyleName { Val = "Normal" },
        new StyleParagraphProperties(
            new SpacingBetweenLines { Line = "570", LineRule = LineSpacingRuleValues.Exact, After = "0" },
            new Indentation { FirstLine = "640" }
        ),
        new StyleRunProperties(
            new RunFonts { Ascii = "FangSong", HighAnsi = "FangSong", EastAsia = "FangSong" },
            new FontSize { Val = "32" }, new FontSizeComplexScript { Val = "32" },
            new Color { Val = "000000" }
        )
    ) { Type = StyleValues.Paragraph, StyleId = "Normal", Default = true });
}
