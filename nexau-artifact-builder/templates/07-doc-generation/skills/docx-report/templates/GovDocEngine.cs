// GovDocEngine.cs — JSON 驱动的 DOCX 渲染引擎（通用文档 + 公文）
// Agent 只需生成 JSON 数据，引擎负责排版
// 用法：dotnet run -- render <type> <input.json> <output.docx>
//       dotnet run -- batch <type> <input_dir/> <output_dir/>
//
// 支持类型和别名来源：template-index.json（单一数据源）

using System.Text.Json;
using System.Text.Json.Serialization;
using DocumentFormat.OpenXml;
using DocumentFormat.OpenXml.Packaging;
using DocumentFormat.OpenXml.Wordprocessing;

if (args.Length < 1)
{
    Console.WriteLine("用法：");
    Console.WriteLine("  dotnet run -- render <type> <input.json> <output.docx>");
    Console.WriteLine("  dotnet run -- batch <type> <input_dir/> <output_dir/>");
    Console.WriteLine("类型与别名：请查看 template-index.json（或执行 scripts/build templates）");
    return 1;
}

var command = args[0];
switch (command)
{
    case "render":
        if (args.Length < 4) { Console.WriteLine("❌ render 需要: <type> <input.json> <output.docx>"); return 1; }
        GovDocRenderer.RenderSingle(args[1], args[2], args[3]);
        break;
    case "batch":
        if (args.Length < 4) { Console.WriteLine("❌ batch 需要: <type> <input_dir> <output_dir>"); return 1; }
        GovDocRenderer.RenderBatch(args[1], args[2], args[3]);
        break;
    case "diff":
        if (args.Length < 5) { Console.WriteLine("❌ diff 需要: <type> <old.json> <new.json> <output.docx>"); return 1; }
        GovDocDiff.RenderDiff(args[1], args[2], args[3], args[4]);
        break;
    default:
        Console.WriteLine($"❌ 未知命令 '{command}'");
        Console.WriteLine("   支持：render, batch, diff");
        return 1;
}

return 0;

// ══════════════════════════════════════════════
// 渲染器
// ══════════════════════════════════════════════
public static class GovDocRenderer
{
    static readonly TemplateIndexCatalog TemplateCatalog = TemplateIndexCatalog.LoadOrExit();

    static readonly JsonSerializerOptions JsonOpts = new()
    {
        PropertyNameCaseInsensitive = true,
        ReadCommentHandling = JsonCommentHandling.Skip,
        AllowTrailingCommas = true
    };

    static string NormalizeDocType(string docType)
    {
        var key = (docType ?? "").Trim();
        if (TemplateCatalog.Aliases.TryGetValue(key, out var mapped)) return mapped;
        return key.ToLowerInvariant();
    }

    static bool IsRenderableType(string type) =>
        type is "generic" or "notice" or "report" or "letter" or "resolution" or "minutes" or "decision";

    public static void RenderSingle(string docType, string inputPath, string outputPath)
    {
        if (!File.Exists(inputPath)) { Console.WriteLine($"❌ 输入文件不存在：{inputPath}"); Environment.Exit(1); }
        var json = File.ReadAllText(inputPath);
        var normalizedType = NormalizeDocType(docType);

        if (!TemplateCatalog.RequiredFieldsByType.ContainsKey(normalizedType))
        {
            Console.WriteLine($"❌ 未知文档类型：{docType}");
            Console.WriteLine($"   支持基础模板：{string.Join(", ", TemplateCatalog.TemplateTypes)}");
            Console.WriteLine("   别名请查看 template-index.json 或执行 scripts/build templates");
            Environment.Exit(1);
        }

        if (!IsRenderableType(normalizedType))
        {
            Console.WriteLine($"❌ 当前引擎尚未实现模板类型：{normalizedType}");
            Console.WriteLine("   请先在 GovDocEngine.cs 中实现对应 Render 方法后再使用");
            Environment.Exit(1);
        }

        // 预校验 JSON 结构
        var errors = ValidateInput(normalizedType, json);
        if (errors.Count > 0)
        {
            Console.WriteLine($"❌ JSON 校验失败（{errors.Count} 个错误）：");
            foreach (var e in errors) Console.WriteLine($"   • {e}");
            Console.WriteLine();
            Console.WriteLine("💡 请对照 docx-report SKILL.md 中的最小完整示例修正 JSON");
            Environment.Exit(1);
        }

        try
        {
            switch (normalizedType)
            {
                case "generic":    RenderGeneric(JsonSerializer.Deserialize<GenericInput>(json, JsonOpts)!, outputPath); break;
                case "notice":     RenderNotice(JsonSerializer.Deserialize<NoticeInput>(json, JsonOpts)!, outputPath); break;
                case "report":     RenderReport(JsonSerializer.Deserialize<ReportInput>(json, JsonOpts)!, outputPath); break;
                case "letter":     RenderLetter(JsonSerializer.Deserialize<LetterInput>(json, JsonOpts)!, outputPath); break;
                case "resolution": RenderResolution(JsonSerializer.Deserialize<ResolutionInput>(json, JsonOpts)!, outputPath); break;
                case "minutes":    RenderMinutes(JsonSerializer.Deserialize<MinutesInput>(json, JsonOpts)!, outputPath); break;
                case "decision":   RenderDecision(JsonSerializer.Deserialize<DecisionInput>(json, JsonOpts)!, outputPath); break;
                default: Console.WriteLine($"❌ 未知文档类型：{docType}"); Environment.Exit(1); break;
            }
            Console.WriteLine($"✅ 生成完成：{outputPath} ({new FileInfo(outputPath).Length} bytes)");
        }
        catch (JsonException ex)
        {
            Console.WriteLine($"❌ JSON 解析失败：{ex.Message}");
            if (ex.LineNumber.HasValue) Console.WriteLine($"   位置：行 {ex.LineNumber}，字节 {ex.BytePositionInLine}");
            Environment.Exit(1);
        }
        catch (Exception ex)
        {
            Console.WriteLine($"❌ 生成失败：{ex.Message}");
            Console.WriteLine($"   {ex.StackTrace?.Split('\n').FirstOrDefault()}");
            Environment.Exit(1);
        }
    }

    // ── JSON 预校验 ──

    // 常见错误字段名 → 正确字段名
    static readonly Dictionary<string, string> WrongFieldHints = new()
    {
        ["content"]  = "sections",
        ["body"]     = "sections（正文必须用 sections 数组）",
        ["text"]     = "paragraphs（section 内的段落字段是 paragraphs）",
        ["contents"] = "sections",
        ["paragraph"] = "paragraphs（注意是复数形式，且必须是字符串数组）",
        ["org_name"] = "gov_org（notice/letter）或 org（report）",
        ["organization"] = "gov_org 或 org",
        ["sender"]   = "gov_org",
        ["tables"]   = "kv_tables 或 data_tables（需区分键值对表格和数据表格）",
    };

    static List<string> ValidateInput(string docType, string json)
    {
        var errors = new List<string>();
        var dt = NormalizeDocType(docType);

        if (!TemplateCatalog.RequiredFieldsByType.ContainsKey(dt))
        {
            errors.Add($"不支持的文档类型 \"{docType}\"，支持基础模板：{string.Join(", ", TemplateCatalog.TemplateTypes)}");
            return errors;
        }

        JsonDocument doc;
        try { doc = JsonDocument.Parse(json); }
        catch (JsonException ex)
        {
            errors.Add($"JSON 语法错误：{ex.Message}");
            return errors;
        }

        using (doc)
        {
            var root = doc.RootElement;
            if (root.ValueKind != JsonValueKind.Object)
            {
                errors.Add("根元素必须是 JSON 对象 {{}}，不能是数组或其他类型");
                return errors;
            }

            // 检查必填字段
            if (TemplateCatalog.RequiredFieldsByType.TryGetValue(dt, out var required))
            {
                foreach (var field in required)
                {
                    if (!TryGetPropertyCI(root, field, out var val))
                    {
                        errors.Add($"缺少必填字段 \"{field}\"");
                    }
                    else if (field == "sections" || field == "agenda_items")
                    {
                        if (val.ValueKind != JsonValueKind.Array)
                            errors.Add($"\"{field}\" 必须是数组，当前是 {KindName(val.ValueKind)}");
                        else if (val.GetArrayLength() == 0)
                            errors.Add($"\"{field}\" 数组为空，至少需要一个元素");
                    }
                    else if (field == "meeting_info")
                    {
                        if (val.ValueKind != JsonValueKind.Object)
                            errors.Add($"\"{field}\" 必须是对象，当前是 {KindName(val.ValueKind)}");
                    }
                    else if (val.ValueKind == JsonValueKind.String && string.IsNullOrWhiteSpace(val.GetString()))
                    {
                        errors.Add($"\"{field}\" 不能为空字符串");
                    }
                }
            }

            // 检查 sections 内部结构
            if (TryGetPropertyCI(root, "sections", out var sectionsEl) && sectionsEl.ValueKind == JsonValueKind.Array)
            {
                ValidateSections(sectionsEl, "sections", errors);
            }

            // 检测常见错误字段名
            foreach (var prop in root.EnumerateObject())
            {
                var name = prop.Name.ToLower();
                if (WrongFieldHints.TryGetValue(name, out var hint))
                {
                    errors.Add($"发现无效字段 \"{prop.Name}\"，你是否想用 {hint}？");
                }
            }

            // report/generic 类型特有：检查 kv_tables / data_tables 结构
            if (dt == "report" || dt == "generic")
            {
                if (TryGetPropertyCI(root, "kv_tables", out var kvEl) && kvEl.ValueKind == JsonValueKind.Array)
                {
                    for (int i = 0; i < kvEl.GetArrayLength(); i++)
                    {
                        var item = kvEl[i];
                        if (!TryGetPropertyCI(item, "items", out var itemsEl))
                            errors.Add($"kv_tables[{i}] 缺少 \"items\" 字段");
                        else if (itemsEl.ValueKind != JsonValueKind.Array)
                            errors.Add($"kv_tables[{i}].items 必须是数组");
                    }
                }
                if (TryGetPropertyCI(root, "data_tables", out var dtEl) && dtEl.ValueKind == JsonValueKind.Array)
                {
                    for (int i = 0; i < dtEl.GetArrayLength(); i++)
                    {
                        var item = dtEl[i];
                        if (!TryGetPropertyCI(item, "headers", out _))
                            errors.Add($"data_tables[{i}] 缺少 \"headers\" 字段");
                        if (!TryGetPropertyCI(item, "rows", out _))
                            errors.Add($"data_tables[{i}] 缺少 \"rows\" 字段");
                    }
                }
            }
        }

        return errors;
    }

    static void ValidateSections(JsonElement arr, string path, List<string> errors)
    {
        for (int i = 0; i < arr.GetArrayLength(); i++)
        {
            var s = arr[i];
            var sp = $"{path}[{i}]";

            if (s.ValueKind != JsonValueKind.Object)
            {
                errors.Add($"{sp} 必须是对象，当前是 {KindName(s.ValueKind)}");
                continue;
            }

            if (!TryGetPropertyCI(s, "heading", out _))
                errors.Add($"{sp} 缺少 \"heading\" 字段");

            if (!TryGetPropertyCI(s, "level", out var levelEl))
                errors.Add($"{sp} 缺少 \"level\" 字段（1=一级标题 2=二级 3=三级）");
            else if (levelEl.ValueKind != JsonValueKind.Number)
                errors.Add($"{sp}.level 必须是数字（1/2/3），当前是 {KindName(levelEl.ValueKind)}");

            // paragraphs 必须是字符串数组，不能是字符串
            if (TryGetPropertyCI(s, "paragraphs", out var pEl))
            {
                if (pEl.ValueKind == JsonValueKind.String)
                    errors.Add($"{sp}.paragraphs 必须是字符串数组 [\"...\"]，不能是字符串。请改为 [\"{ Truncate(pEl.GetString() ?? "", 30) }\"]");
                else if (pEl.ValueKind != JsonValueKind.Array)
                    errors.Add($"{sp}.paragraphs 必须是字符串数组，当前是 {KindName(pEl.ValueKind)}");
            }

            // 检测 section 内的错误字段名
            foreach (var prop in s.EnumerateObject())
            {
                var name = prop.Name.ToLower();
                if (name == "content" || name == "body" || name == "text")
                    errors.Add($"{sp} 发现无效字段 \"{prop.Name}\"，section 内的段落字段应为 \"paragraphs\"（字符串数组）");
                if (name == "kv_table" || name == "kv_tables" || name == "data_table" || name == "data_tables")
                    errors.Add($"{sp} 发现 \"{prop.Name}\"：表格应放在 JSON 顶层的 kv_tables/data_tables 字段中，不要嵌套在 sections 里");
            }

            // 递归检查 children
            if (TryGetPropertyCI(s, "children", out var childEl) && childEl.ValueKind == JsonValueKind.Array)
                ValidateSections(childEl, $"{sp}.children", errors);
        }
    }

    static bool TryGetPropertyCI(JsonElement el, string name, out JsonElement value)
    {
        // 先精确匹配
        if (el.TryGetProperty(name, out value)) return true;
        // 再大小写不敏感匹配
        foreach (var prop in el.EnumerateObject())
        {
            if (string.Equals(prop.Name, name, StringComparison.OrdinalIgnoreCase))
            {
                value = prop.Value;
                return true;
            }
        }
        value = default;
        return false;
    }

    static string KindName(JsonValueKind kind) => kind switch
    {
        JsonValueKind.String => "字符串",
        JsonValueKind.Number => "数字",
        JsonValueKind.True or JsonValueKind.False => "布尔值",
        JsonValueKind.Array => "数组",
        JsonValueKind.Object => "对象",
        JsonValueKind.Null => "null",
        _ => kind.ToString()
    };

    static string Truncate(string s, int max) => s.Length <= max ? s : s[..max] + "...";

    public static void RenderBatch(string docType, string inputDir, string outputDir)
    {
        if (!Directory.Exists(inputDir)) { Console.WriteLine($"❌ 输入目录不存在：{inputDir}"); Environment.Exit(1); }
        Directory.CreateDirectory(outputDir);
        var files = Directory.GetFiles(inputDir, "*.json");
        if (files.Length == 0) { Console.WriteLine($"❌ 无 .json 文件：{inputDir}"); Environment.Exit(1); }

        Console.WriteLine($"📦 批量生成：{files.Length} 个文件");
        int ok = 0, fail = 0;
        foreach (var f in files.OrderBy(x => x))
        {
            var name = Path.GetFileNameWithoutExtension(f);
            var output = Path.Combine(outputDir, $"{name}.docx");
            try { RenderSingle(docType, f, output); ok++; }
            catch (Exception ex) { Console.WriteLine($"❌ {name}: {ex.Message}"); fail++; }
        }
        Console.WriteLine($"\n📊 成功 {ok}，失败 {fail}，共 {files.Length}");
    }

    // ── 通知 ──
    static void RenderNotice(NoticeInput d, string output)
    {
        using var doc = WordprocessingDocument.Create(output, WordprocessingDocumentType.Document);
        var mp = doc.AddMainDocumentPart(); mp.Document = new Document();
        var body = new Body(); K.AddStyles(mp);

        K.AppendGovHeader(body, d.GovOrg, d.DocNum);
        K.AppendDocTitle(body, d.Title);
        body.Append(K.BodyPara(d.SendTo + "\uFF1A", indent: false));
        K.AppendSections(body, d.Sections);
        if (d.PolicyRefs is { Count: > 0 }) K.AppendPolicyTable(mp, body, d.PolicyRefs);
        K.AppendSignature(body, d.GovOrg, d.Date, d.Seal);
        K.AppendFootnote(body, d.CcOrgs);
        K.AppendPageSetup(mp, body);
        mp.Document.Append(body); doc.Save();
    }

    // ── 信函 ──
    static void RenderLetter(LetterInput d, string output)
    {
        using var doc = WordprocessingDocument.Create(output, WordprocessingDocumentType.Document);
        var mp = doc.AddMainDocumentPart(); mp.Document = new Document();
        var body = new Body(); K.AddStyles(mp);

        K.AppendGovHeader(body, d.GovOrg, d.DocNum, isLetter: true);
        K.AppendDocTitle(body, d.Title);
        body.Append(K.BodyPara(d.SendTo + "\uFF1A", indent: false));
        K.AppendSections(body, d.Sections);
        if (d.Contact != null)
        {
            var ct = "";
            if (!string.IsNullOrEmpty(d.Contact.Dept)) ct += "\u8054\u7CFB\u90E8\u95E8\uFF1A" + d.Contact.Dept;
            if (!string.IsNullOrEmpty(d.Contact.Phone)) ct += (ct.Length > 0 ? "\uFF0C" : "") + "\u8054\u7CFB\u7535\u8BDD\uFF1A" + d.Contact.Phone;
            if (ct.Length > 0) body.Append(K.BodyPara(ct));
        }
        K.AppendSignature(body, d.GovOrg, d.Date, d.Seal);
        K.AppendFootnote(body, d.CcOrgs);
        K.AppendPageSetup(mp, body);
        mp.Document.Append(body); doc.Save();
    }

    // ── 报告 ──
    static void RenderReport(ReportInput d, string output)
    {
        using var doc = WordprocessingDocument.Create(output, WordprocessingDocumentType.Document);
        var mp = doc.AddMainDocumentPart(); mp.Document = new Document();
        var body = new Body(); K.AddStyles(mp);

        // 封面
        if (!string.IsNullOrEmpty(d.Confidential))
            body.Append(K.RightAligned(d.Confidential, "24", "CC0000"));
        for (int i = 0; i < 6; i++) body.Append(K.Spacer());
        body.Append(K.CenterText(d.Title, "SimHei", "52", K.ACCENT));
        if (!string.IsNullOrEmpty(d.Subtitle))
            body.Append(K.CenterText(d.Subtitle, "FangSong", "32", K.GRAY, after: "600"));
        for (int i = 0; i < 4; i++) body.Append(K.Spacer());
        body.Append(K.CenterText(d.Org, "FangSong", "32"));
        body.Append(K.CenterText(d.Date, "FangSong", "32"));
        body.Append(K.PageBreak());

        // 正文
        K.AppendSections(body, d.Sections);
        if (d.KvTables != null) foreach (var t in d.KvTables) K.AppendKvTable(body, t);
        if (d.DataTables != null) foreach (var t in d.DataTables) K.AppendDataTable(body, t);
        if (d.PolicyRefs is { Count: > 0 }) K.AppendPolicyTable(mp, body, d.PolicyRefs);
        K.AppendSignature(body, d.Org, d.Date, d.Seal);
        K.AppendPageSetup(mp, body);
        mp.Document.Append(body); doc.Save();
    }

    // ── 通用文档 ──
    static void RenderGeneric(GenericInput d, string output)
    {
        using var doc = WordprocessingDocument.Create(output, WordprocessingDocumentType.Document);
        var mp = doc.AddMainDocumentPart(); mp.Document = new Document();
        var body = new Body(); K.AddStyles(mp);

        body.Append(K.CenterText(d.Title, "SimHei", "44", K.ACCENT, before: "300", after: "200"));
        if (!string.IsNullOrEmpty(d.Subtitle))
            body.Append(K.CenterText(d.Subtitle, "FangSong", "28", K.GRAY, after: "200"));

        var meta = new List<string>();
        if (!string.IsNullOrEmpty(d.Org)) meta.Add(d.Org);
        if (!string.IsNullOrEmpty(d.Author)) meta.Add("作者：" + d.Author);
        if (!string.IsNullOrEmpty(d.Date)) meta.Add(d.Date);
        if (meta.Count > 0)
            body.Append(K.CenterText(string.Join("  |  ", meta), "FangSong", "24", K.GRAY, after: "300"));

        K.AppendSections(body, d.Sections);
        if (d.KvTables != null) foreach (var t in d.KvTables) K.AppendKvTable(body, t);
        if (d.DataTables != null) foreach (var t in d.DataTables) K.AppendDataTable(body, t);
        if (d.PolicyRefs is { Count: > 0 }) K.AppendPolicyTable(mp, body, d.PolicyRefs);

        if (!string.IsNullOrEmpty(d.FooterNote))
            body.Append(K.RightAligned(d.FooterNote, "21", K.GRAY));

        K.AppendPageSetup(mp, body);
        mp.Document.Append(body); doc.Save();
    }

    // ── 请示/批复 ──
    static void RenderResolution(ResolutionInput d, string output)
    {
        using var doc = WordprocessingDocument.Create(output, WordprocessingDocumentType.Document);
        var mp = doc.AddMainDocumentPart(); mp.Document = new Document();
        var body = new Body(); K.AddStyles(mp);

        K.AppendGovHeader(body, d.GovOrg, d.DocNum);
        K.AppendDocTitle(body, d.Title);
        body.Append(K.BodyPara(d.SendTo + "\uFF1A", indent: false));
        if (d.Subtype == "\u6279\u590D" && !string.IsNullOrEmpty(d.RefDoc))
            body.Append(K.BodyPara("\u4F60\u5355\u4F4D" + d.RefDoc + "\u6536\u6089\u3002\u7ECF\u7814\u7A76\uFF0C\u73B0\u6279\u590D\u5982\u4E0B\uFF1A"));
        K.AppendSections(body, d.Sections);
        if (!string.IsNullOrEmpty(d.Conclusion)) body.Append(K.BodyPara(d.Conclusion));
        K.AppendSignature(body, d.GovOrg, d.Date, d.Seal);
        K.AppendFootnote(body, d.CcOrgs);
        K.AppendPageSetup(mp, body);
        mp.Document.Append(body); doc.Save();
    }

    // ── 纪要 ──
    static void RenderMinutes(MinutesInput d, string output)
    {
        using var doc = WordprocessingDocument.Create(output, WordprocessingDocumentType.Document);
        var mp = doc.AddMainDocumentPart(); mp.Document = new Document();
        var body = new Body(); K.AddStyles(mp);

        body.Append(K.CenterText(d.GovOrg, "FZXiaoBiaoSong-B05", "44", K.GOV_RED, before: "800"));
        body.Append(K.CenterText(d.DocNum, "FangSong", "32", before: "100", after: "200"));
        K.AppendDocTitle(body, d.Title);

        var mi = d.MeetingInfo;
        var meetingKv = new KvTable
        {
            Items = new List<KvItem> {
                new() { Key = "\u4F1A\u8BAE\u65F6\u95F4", Value = mi.Time },
                new() { Key = "\u4F1A\u8BAE\u5730\u70B9", Value = mi.Location },
                new() { Key = "\u4E3B\u6301\u4EBA", Value = mi.Host },
                new() { Key = "\u51FA\u5E2D\u4EBA\u5458", Value = string.Join("\u3001", mi.Attendees) },
            }
        };
        if (!string.IsNullOrEmpty(mi.Recorder))
            meetingKv.Items.Add(new KvItem { Key = "\u8BB0\u5F55\u4EBA", Value = mi.Recorder });
        K.AppendKvTable(body, meetingKv);

        for (int i = 0; i < d.AgendaItems.Count; i++)
        {
            var item = d.AgendaItems[i];
            body.Append(K.Heading1($"\u8BAE\u9898{i + 1}\uFF1A{item.Topic}"));
            if (!string.IsNullOrEmpty(item.Discussion)) body.Append(K.BodyPara(item.Discussion));
            body.Append(K.BodyPara("\u8BAE\u5B9A\u4E8B\u9879\uFF1A" + item.Resolution, bold: true));
            if (!string.IsNullOrEmpty(item.Responsible)) body.Append(K.BodyPara("\u8D23\u4EFB\u90E8\u95E8\uFF1A" + item.Responsible));
            if (!string.IsNullOrEmpty(item.Deadline)) body.Append(K.BodyPara("\u5B8C\u6210\u65F6\u9650\uFF1A" + item.Deadline));
        }

        K.AppendSignature(body, d.GovOrg, d.Date, d.Seal);
        K.AppendFootnote(body, d.CcOrgs);
        K.AppendPageSetup(mp, body);
        mp.Document.Append(body); doc.Save();
    }

    // ── 决定 ──
    static void RenderDecision(DecisionInput d, string output)
    {
        using var doc = WordprocessingDocument.Create(output, WordprocessingDocumentType.Document);
        var mp = doc.AddMainDocumentPart(); mp.Document = new Document();
        var body = new Body(); K.AddStyles(mp);

        K.AppendGovHeader(body, d.GovOrg, d.DocNum);
        K.AppendDocTitle(body, d.Title);
        if (!string.IsNullOrEmpty(d.SendTo)) body.Append(K.BodyPara(d.SendTo + "\uFF1A", indent: false));

        if (d.CaseInfo != null)
        {
            var ci = d.CaseInfo;
            var items = new List<KvItem>();
            if (ci.CaseNum != null) items.Add(new() { Key = "\u6848\u4EF6\u7F16\u53F7", Value = ci.CaseNum });
            if (ci.Party != null) items.Add(new() { Key = "\u5F53\u4E8B\u4EBA", Value = ci.Party });
            if (ci.PartyId != null) items.Add(new() { Key = "\u7EDF\u4E00\u793E\u4F1A\u4FE1\u7528\u4EE3\u7801", Value = ci.PartyId });
            if (ci.PartyAddress != null) items.Add(new() { Key = "\u5730\u5740", Value = ci.PartyAddress });
            if (ci.LegalRep != null) items.Add(new() { Key = "\u6CD5\u5B9A\u4EE3\u8868\u4EBA", Value = ci.LegalRep });
            if (items.Count > 0) K.AppendKvTable(body, new KvTable { Items = items });
        }

        if (d.Facts is { Count: > 0 })
        {
            body.Append(K.Heading1("\u4E00\u3001\u8FDD\u6CD5\u4E8B\u5B9E"));
            foreach (var f in d.Facts) body.Append(K.BodyPara(f));
        }
        if (d.LegalBasis is { Count: > 0 })
        {
            body.Append(K.Heading1("\u4E8C\u3001\u6CD5\u5F8B\u4F9D\u636E"));
            foreach (var lb in d.LegalBasis)
            {
                var t = $"\u300A{lb.Name}\u300B\uFF08{lb.DocNum}\uFF09";
                if (!string.IsNullOrEmpty(lb.Clause)) t += lb.Clause;
                body.Append(K.BodyPara(t));
            }
        }
        if (d.Penalties is { Count: > 0 })
        {
            body.Append(K.Heading1("\u4E09\u3001\u5904\u7F5A\u51B3\u5B9A"));
            for (int i = 0; i < d.Penalties.Count; i++)
                body.Append(K.BodyPara($"{i + 1}. {d.Penalties[i].Item}\uFF1A{d.Penalties[i].Detail}"));
        }
        if (d.Sections != null) K.AppendSections(body, d.Sections);
        if (d.AppealInfo != null)
        {
            body.Append(K.Heading1("\u56DB\u3001\u6551\u6D4E\u9014\u5F84"));
            var ai = d.AppealInfo;
            if (ai.ReconsiderOrg != null)
                body.Append(K.BodyPara($"\u5F53\u4E8B\u4EBA\u5BF9\u672C\u51B3\u5B9A\u4E0D\u670D\u7684\uFF0C\u53EF\u5728\u6536\u5230\u672C\u51B3\u5B9A\u4E66\u4E4B\u65E5\u8D77{ai.ReconsiderDays}\u65E5\u5185\u5411{ai.ReconsiderOrg}\u7533\u8BF7\u884C\u653F\u590D\u8BAE\u3002"));
            if (ai.LawsuitCourt != null)
                body.Append(K.BodyPara($"\u4E5F\u53EF\u5728{ai.LawsuitDays}\u4E2A\u6708\u5185\u5411{ai.LawsuitCourt}\u63D0\u8D77\u884C\u653F\u8BC9\u8BBC\u3002"));
        }
        K.AppendSignature(body, d.GovOrg, d.Date, d.Seal);
        K.AppendFootnote(body, d.CcOrgs);
        K.AppendPageSetup(mp, body);
        mp.Document.Append(body); doc.Save();
    }
}

public sealed class TemplateIndexCatalog
{
    public string IndexPath { get; }
    public List<string> TemplateTypes { get; }
    public Dictionary<string, string> Aliases { get; }
    public Dictionary<string, string[]> RequiredFieldsByType { get; }

    TemplateIndexCatalog(
        string indexPath,
        List<string> templateTypes,
        Dictionary<string, string> aliases,
        Dictionary<string, string[]> requiredFieldsByType)
    {
        IndexPath = indexPath;
        TemplateTypes = templateTypes;
        Aliases = aliases;
        RequiredFieldsByType = requiredFieldsByType;
    }

    public static TemplateIndexCatalog LoadOrExit()
    {
        try
        {
            return Load();
        }
        catch (Exception ex)
        {
            Console.WriteLine($"❌ 读取 template-index.json 失败：{ex.Message}");
            Console.WriteLine("   建议通过 scripts/build 调用引擎，或设置 DOCX_TEMPLATE_INDEX 指向索引文件");
            Environment.Exit(1);
            return null!;
        }
    }

    static TemplateIndexCatalog Load()
    {
        var indexPath = ResolveIndexPath();
        if (indexPath == null)
            throw new InvalidOperationException("未找到 template-index.json");

        using var doc = JsonDocument.Parse(File.ReadAllText(indexPath));
        var root = doc.RootElement;
        if (!root.TryGetProperty("templates", out var templatesEl) || templatesEl.ValueKind != JsonValueKind.Array)
            throw new InvalidOperationException("缺少 templates 数组");

        var templateTypes = new List<string>();
        var aliases = new Dictionary<string, string>(StringComparer.OrdinalIgnoreCase);
        var requiredFields = new Dictionary<string, string[]>(StringComparer.OrdinalIgnoreCase);

        foreach (var t in templatesEl.EnumerateArray())
        {
            if (!t.TryGetProperty("type", out var typeEl) || typeEl.ValueKind != JsonValueKind.String)
                throw new InvalidOperationException("templates[].type 必须是字符串");

            var typeRaw = (typeEl.GetString() ?? "").Trim();
            if (typeRaw.Length == 0)
                throw new InvalidOperationException("templates[].type 不能为空");

            var type = typeRaw.ToLowerInvariant();
            if (requiredFields.ContainsKey(type))
                throw new InvalidOperationException($"模板类型重复：{type}");

            if (!t.TryGetProperty("required", out var requiredEl) || requiredEl.ValueKind != JsonValueKind.Array)
                throw new InvalidOperationException($"templates[{type}].required 必须是数组");

            var required = requiredEl.EnumerateArray()
                .Where(x => x.ValueKind == JsonValueKind.String)
                .Select(x => (x.GetString() ?? "").Trim())
                .Where(x => x.Length > 0)
                .Distinct(StringComparer.OrdinalIgnoreCase)
                .ToArray();

            if (required.Length == 0)
                throw new InvalidOperationException($"templates[{type}].required 不能为空");

            templateTypes.Add(type);
            requiredFields[type] = required;
            aliases[type] = type;
        }

        if (root.TryGetProperty("aliases", out var aliasEl) && aliasEl.ValueKind == JsonValueKind.Object)
        {
            foreach (var pair in aliasEl.EnumerateObject())
            {
                var alias = pair.Name.Trim();
                var target = (pair.Value.GetString() ?? "").Trim().ToLowerInvariant();
                if (alias.Length == 0 || target.Length == 0) continue;
                if (!requiredFields.ContainsKey(target))
                    throw new InvalidOperationException($"aliases.{alias} 指向未知模板类型：{target}");
                aliases[alias] = target;
            }
        }

        return new TemplateIndexCatalog(indexPath, templateTypes, aliases, requiredFields);
    }

    static string? ResolveIndexPath()
    {
        var fromEnv = Environment.GetEnvironmentVariable("DOCX_TEMPLATE_INDEX");
        if (!string.IsNullOrWhiteSpace(fromEnv))
        {
            var full = Path.GetFullPath(fromEnv);
            if (File.Exists(full)) return full;
        }

        var fromCwd = FindFileUpwards(Directory.GetCurrentDirectory(), "template-index.json", 12);
        if (fromCwd != null) return fromCwd;

        var fromBase = FindFileUpwards(AppContext.BaseDirectory, "template-index.json", 12);
        if (fromBase != null) return fromBase;

        return null;
    }

    static string? FindFileUpwards(string startDir, string fileName, int maxDepth)
    {
        var current = new DirectoryInfo(startDir);
        for (var depth = 0; depth <= maxDepth && current != null; depth++)
        {
            var candidate = Path.Combine(current.FullName, fileName);
            if (File.Exists(candidate)) return candidate;
            current = current.Parent;
        }
        return null;
    }
}

// ══════════════════════════════════════════════
// 排版工具箱
// ══════════════════════════════════════════════
public static class K
{
    public const string GOV_RED = "C81414";
    public const string BLACK = "000000";
    public const string GRAY = "666666";
    public const string ACCENT = "1F4E79";
    public const uint A4W = 11906, A4H = 16838;
    public const int MTop = 2098, MBot = 1984, MLeft = 1588, MRight = 1474;

    public static Paragraph BodyPara(string text, bool bold = false, bool indent = true)
    {
        var pp = new ParagraphProperties(
            new Justification { Val = JustificationValues.Both },
            new SpacingBetweenLines { Line = "570", LineRule = LineSpacingRuleValues.Exact, After = "0" });
        if (indent) pp.Append(new Indentation { FirstLine = "640" });
        var rp = new RunProperties(FS(), new FontSize { Val = "32" }, new FontSizeComplexScript { Val = "32" });
        if (bold) rp.Append(new Bold());
        return new Paragraph(pp, new Run(rp, new Text(text)));
    }

    public static Paragraph Heading1(string t) => Heading(t, 1);
    public static Paragraph Heading(string t, int level) => level switch
    {
        1 => new Paragraph(
            new ParagraphProperties(new ParagraphStyleId { Val = "Heading1" }, new Justification { Val = JustificationValues.Left },
                new SpacingBetweenLines { Before = "200", After = "100", Line = "570", LineRule = LineSpacingRuleValues.Exact },
                new Indentation { FirstLine = "0" }),
            new Run(new RunProperties(HT(), new FontSize { Val = "32" }, new FontSizeComplexScript { Val = "32" }, new Bold { Val = false }), new Text(t))),
        2 => new Paragraph(
            new ParagraphProperties(new ParagraphStyleId { Val = "Heading2" }, new Justification { Val = JustificationValues.Left },
                new SpacingBetweenLines { Before = "100", After = "50", Line = "570", LineRule = LineSpacingRuleValues.Exact },
                new Indentation { FirstLine = "640" }),
            new Run(new RunProperties(KT(), new FontSize { Val = "32" }, new FontSizeComplexScript { Val = "32" }), new Text(t))),
        _ => new Paragraph(
            new ParagraphProperties(new Justification { Val = JustificationValues.Left },
                new SpacingBetweenLines { Before = "100", After = "50", Line = "570", LineRule = LineSpacingRuleValues.Exact },
                new Indentation { FirstLine = "640" }),
            new Run(new RunProperties(FS(), new FontSize { Val = "32" }, new FontSizeComplexScript { Val = "32" }, new Bold()), new Text(t)))
    };

    public static void AppendSections(Body body, List<SectionInput>? sections)
    {
        if (sections == null) return;
        foreach (var s in sections)
        {
            body.Append(Heading(s.Heading, s.Level));
            if (s.Paragraphs != null) foreach (var p in s.Paragraphs) body.Append(BodyPara(p));
            AppendSections(body, s.Children);
        }
    }

    public static void AppendGovHeader(Body body, string org, string docNum, bool isLetter = false)
    {
        var orgText = isLetter ? org + "\u51FD" : org;
        body.Append(new Paragraph(
            new ParagraphProperties(new Justification { Val = JustificationValues.Center },
                new SpacingBetweenLines { Before = isLetter ? "800" : "1200", After = "100" }),
            new Run(new RunProperties(XB(), new FontSize { Val = "44" }, new FontSizeComplexScript { Val = "44" }, new Color { Val = GOV_RED }), new Text(orgText))));
        body.Append(new Paragraph(new ParagraphProperties(
            new ParagraphBorders(new BottomBorder { Val = BorderValues.Single, Size = (uint)(isLetter ? 4 : 8), Color = GOV_RED, Space = 1 }),
            new SpacingBetweenLines { Before = "0", After = "0" })));
        body.Append(new Paragraph(
            new ParagraphProperties(new Justification { Val = isLetter ? JustificationValues.Left : JustificationValues.Center },
                new SpacingBetweenLines { Before = "100", After = "200" }),
            new Run(new RunProperties(FS(), new FontSize { Val = "32" }, new FontSizeComplexScript { Val = "32" }), new Text(docNum))));
    }

    public static void AppendDocTitle(Body body, string title)
    {
        body.Append(new Paragraph(
            new ParagraphProperties(new Justification { Val = JustificationValues.Center },
                new SpacingBetweenLines { Before = "200", After = "300", Line = "570", LineRule = LineSpacingRuleValues.Exact }),
            new Run(new RunProperties(XB(), new FontSize { Val = "44" }, new FontSizeComplexScript { Val = "44" }), new Text(title))));
    }

    public static void AppendSignature(Body body, string org, string date, SealConfig? seal = null)
    {
        body.Append(new Paragraph(new ParagraphProperties(new SpacingBetweenLines { Before = "600" })));
        if (seal?.Enabled == true)
        {
            body.Append(new Paragraph(
                new ParagraphProperties(new Justification { Val = JustificationValues.Right }, new SpacingBetweenLines { After = "50" }),
                new Run(new RunProperties(FS(), new FontSize { Val = "24" }, new FontSizeComplexScript { Val = "24" },
                    new Color { Val = "CC0000" }), new Text(seal.Text))));
        }
        body.Append(RightLine(org));
        body.Append(RightLine(date));
    }

    public static void AppendFootnote(Body body, string? cc)
    {
        if (string.IsNullOrEmpty(cc)) return;
        body.Append(new Paragraph(new ParagraphProperties(
            new ParagraphBorders(new TopBorder { Val = BorderValues.Single, Size = 4, Color = GOV_RED, Space = 1 }),
            new SpacingBetweenLines { Before = "600", After = "0" }),
            new Run(new RunProperties(FS(), new FontSize { Val = "24" }, new FontSizeComplexScript { Val = "24" }),
                new Text("\u6284\u9001\uFF1A" + cc + "\u3002"))));
        body.Append(new Paragraph(new ParagraphProperties(
            new ParagraphBorders(new BottomBorder { Val = BorderValues.Single, Size = 4, Color = GOV_RED, Space = 1 }),
            new SpacingBetweenLines { Before = "0", After = "0" })));
    }

    public static void AppendPageSetup(MainDocumentPart mp, Body body)
    {
        var fp = mp.AddNewPart<FooterPart>();
        var fid = mp.GetIdOfPart(fp);
        var para = new Paragraph(new ParagraphProperties(new Justification { Val = JustificationValues.Center }));
        para.Append(new Run(new RunProperties(FS(), new FontSize { Val = "24" }, new FontSizeComplexScript { Val = "24" }),
            new Text("\u2014 ") { Space = SpaceProcessingModeValues.Preserve }));
        para.Append(new Run(new FieldChar { FieldCharType = FieldCharValues.Begin }));
        para.Append(new Run(new FieldCode(" PAGE ")));
        para.Append(new Run(new FieldChar { FieldCharType = FieldCharValues.Separate }));
        para.Append(new Run(new Text("1")));
        para.Append(new Run(new FieldChar { FieldCharType = FieldCharValues.End }));
        para.Append(new Run(new RunProperties(FS(), new FontSize { Val = "24" }, new FontSizeComplexScript { Val = "24" }),
            new Text(" \u2014") { Space = SpaceProcessingModeValues.Preserve }));
        fp.Footer = new Footer(para);
        body.Append(new SectionProperties(
            new FooterReference { Type = HeaderFooterValues.Default, Id = fid },
            new PageSize { Width = A4W, Height = A4H },
            new PageMargin { Top = MTop, Bottom = MBot, Left = (uint)MLeft, Right = (uint)MRight, Header = 720, Footer = 720 }));
    }

    public static void AddStyles(MainDocumentPart mp)
    {
        var sp = mp.AddNewPart<StyleDefinitionsPart>();
        sp.Styles = new Styles();
        sp.Styles.Append(new Style(new StyleName { Val = "Normal" },
            new StyleParagraphProperties(new SpacingBetweenLines { Line = "570", LineRule = LineSpacingRuleValues.Exact, After = "0" }, new Indentation { FirstLine = "640" }),
            new StyleRunProperties(FS(), new FontSize { Val = "32" }, new FontSizeComplexScript { Val = "32" }, new Color { Val = BLACK })
        ) { Type = StyleValues.Paragraph, StyleId = "Normal", Default = true });
        sp.Styles.Append(new Style(new StyleName { Val = "heading 1" }, new BasedOn { Val = "Normal" },
            new StyleParagraphProperties(new KeepNext(), new KeepLines(), new OutlineLevel { Val = 0 }, new Indentation { FirstLine = "0" }),
            new StyleRunProperties(HT(), new FontSize { Val = "32" }, new FontSizeComplexScript { Val = "32" })
        ) { Type = StyleValues.Paragraph, StyleId = "Heading1" });
        sp.Styles.Append(new Style(new StyleName { Val = "heading 2" }, new BasedOn { Val = "Normal" },
            new StyleParagraphProperties(new KeepNext(), new KeepLines(), new OutlineLevel { Val = 1 }),
            new StyleRunProperties(KT(), new FontSize { Val = "32" }, new FontSizeComplexScript { Val = "32" })
        ) { Type = StyleValues.Paragraph, StyleId = "Heading2" });
        sp.Styles.Append(new Style(new StyleName { Val = "heading 3" }, new BasedOn { Val = "Normal" },
            new StyleParagraphProperties(new KeepNext(), new KeepLines(), new OutlineLevel { Val = 2 }),
            new StyleRunProperties(FS(), new Bold(), new FontSize { Val = "32" }, new FontSizeComplexScript { Val = "32" })
        ) { Type = StyleValues.Paragraph, StyleId = "Heading3" });
    }

    public static void AppendPolicyTable(MainDocumentPart mp, Body body, List<PolicyRef> refs)
    {
        body.Append(Heading1("\u653F\u7B56\u4F9D\u636E\u7D22\u5F15"));
        var tbl = new Table();
        tbl.Append(new TableProperties(
            new TableWidth { Width = "5000", Type = TableWidthUnitValues.Pct },
            new TableBorders(
                new TopBorder { Val = BorderValues.Single, Size = 12, Color = BLACK },
                new BottomBorder { Val = BorderValues.Single, Size = 12, Color = BLACK },
                new LeftBorder { Val = BorderValues.Nil }, new RightBorder { Val = BorderValues.Nil },
                new InsideHorizontalBorder { Val = BorderValues.Nil }, new InsideVerticalBorder { Val = BorderValues.Nil })));
        var w = new[] { "2000", "2400", "1800", "2800" };
        tbl.Append(new TableGrid(new GridColumn { Width = w[0] }, new GridColumn { Width = w[1] }, new GridColumn { Width = w[2] }, new GridColumn { Width = w[3] }));
        var hr = new TableRow(new TableRowProperties(new TableHeader()));
        foreach (var (h, i) in new[] { "\u6587\u53F7", "\u653F\u7B56\u540D\u79F0", "\u5F15\u7528\u6761\u6B3E", "\u539F\u6587\u94FE\u63A5" }.Select((x, i) => (x, i)))
            hr.Append(TCell(h, w[i], header: true));
        tbl.Append(hr);
        foreach (var p in refs)
        {
            var row = new TableRow();
            row.Append(TCell(p.DocNum, w[0])); row.Append(TCell(p.Name, w[1])); row.Append(TCell(p.Clause ?? "", w[2]));
            if (!string.IsNullOrEmpty(p.Url))
            {
                var rid = mp.AddHyperlinkRelationship(new Uri(p.Url), true).Id;
                row.Append(new TableCell(new TableCellProperties(new TableCellWidth { Width = w[3], Type = TableWidthUnitValues.Dxa }),
                    new Paragraph(CellPP(),
                        new Hyperlink(new Run(new RunProperties(FS(), new FontSize { Val = "21" }, new FontSizeComplexScript { Val = "21" },
                            new Color { Val = "0563C1" }, new Underline { Val = UnderlineValues.Single }), new Text("\u94FE\u63A5"))) { Id = rid })));
            }
            else row.Append(TCell("", w[3]));
            tbl.Append(row);
        }
        body.Append(tbl);
    }

    public static void AppendKvTable(Body body, KvTable kvt)
    {
        if (!string.IsNullOrEmpty(kvt.Title)) body.Append(Heading(kvt.Title, 2));
        var tbl = new Table();
        tbl.Append(new TableProperties(new TableWidth { Width = "5000", Type = TableWidthUnitValues.Pct },
            new TableBorders(
                new TopBorder { Val = BorderValues.Single, Size = 4, Color = BLACK },
                new BottomBorder { Val = BorderValues.Single, Size = 4, Color = BLACK },
                new LeftBorder { Val = BorderValues.Single, Size = 4, Color = BLACK },
                new RightBorder { Val = BorderValues.Single, Size = 4, Color = BLACK },
                new InsideHorizontalBorder { Val = BorderValues.Single, Size = 4, Color = "CCCCCC" },
                new InsideVerticalBorder { Val = BorderValues.Single, Size = 4, Color = "CCCCCC" })));
        tbl.Append(new TableGrid(new GridColumn { Width = "3000" }, new GridColumn { Width = "6000" }));
        foreach (var item in kvt.Items)
        {
            var row = new TableRow();
            row.Append(new TableCell(new TableCellProperties(new TableCellWidth { Width = "3000", Type = TableWidthUnitValues.Dxa },
                new Shading { Val = ShadingPatternValues.Clear, Fill = "F2F2F2" }),
                new Paragraph(CellPP(),
                    new Run(new RunProperties(HT(), new FontSize { Val = "24" }, new FontSizeComplexScript { Val = "24" }), new Text(item.Key)))));
            row.Append(new TableCell(new TableCellProperties(new TableCellWidth { Width = "6000", Type = TableWidthUnitValues.Dxa }),
                new Paragraph(CellPP(),
                    new Run(new RunProperties(FS(), new FontSize { Val = "24" }, new FontSizeComplexScript { Val = "24" }), new Text(item.Value)))));
            tbl.Append(row);
        }
        body.Append(tbl);
    }

    public static void AppendDataTable(Body body, DataTable dt)
    {
        if (!string.IsNullOrEmpty(dt.Title)) body.Append(Heading(dt.Title, 2));
        var tbl = new Table();
        tbl.Append(new TableProperties(new TableWidth { Width = "5000", Type = TableWidthUnitValues.Pct },
            new TableBorders(
                new TopBorder { Val = BorderValues.Single, Size = 4, Color = BLACK },
                new BottomBorder { Val = BorderValues.Single, Size = 4, Color = BLACK },
                new LeftBorder { Val = BorderValues.Single, Size = 4, Color = BLACK },
                new RightBorder { Val = BorderValues.Single, Size = 4, Color = BLACK },
                new InsideHorizontalBorder { Val = BorderValues.Single, Size = 4, Color = "CCCCCC" },
                new InsideVerticalBorder { Val = BorderValues.Single, Size = 4, Color = "CCCCCC" })));
        var hr = new TableRow(new TableRowProperties(new TableHeader()));
        foreach (var h in dt.Headers)
            hr.Append(new TableCell(new TableCellProperties(new Shading { Val = ShadingPatternValues.Clear, Fill = "F2F2F2" }),
                new Paragraph(CellPPCenter(),
                    new Run(new RunProperties(HT(), new FontSize { Val = "24" }, new FontSizeComplexScript { Val = "24" }, new Bold()), new Text(h)))));
        tbl.Append(hr);
        foreach (var rd in dt.Rows)
        {
            var row = new TableRow();
            foreach (var c in rd)
                row.Append(new TableCell(new Paragraph(CellPP(),
                    new Run(new RunProperties(FS(), new FontSize { Val = "24" }, new FontSizeComplexScript { Val = "24" }), new Text(c)))));
            tbl.Append(row);
        }
        body.Append(tbl);
    }

    // ── helpers ──
    public static Paragraph CenterText(string t, string font, string sz, string? color = null, string before = "0", string after = "0")
    {
        var rp = new RunProperties(new RunFonts { Ascii = font, HighAnsi = font, EastAsia = font },
            new FontSize { Val = sz }, new FontSizeComplexScript { Val = sz });
        if (color != null) rp.Append(new Color { Val = color });
        return new Paragraph(new ParagraphProperties(new Justification { Val = JustificationValues.Center },
            new SpacingBetweenLines { Before = before, After = after }), new Run(rp, new Text(t)));
    }
    public static Paragraph RightAligned(string t, string sz, string color) =>
        new(new ParagraphProperties(new Justification { Val = JustificationValues.Right }, new SpacingBetweenLines { Before = "200", After = "0" }),
            new Run(new RunProperties(FS(), new FontSize { Val = sz }, new FontSizeComplexScript { Val = sz }, new Color { Val = color }), new Text(t)));
    public static Paragraph RightLine(string t) =>
        new(new ParagraphProperties(new Justification { Val = JustificationValues.Right },
            new SpacingBetweenLines { After = "100", Line = "570", LineRule = LineSpacingRuleValues.Exact }),
            new Run(new RunProperties(FS(), new FontSize { Val = "32" }, new FontSizeComplexScript { Val = "32" }), new Text(t)));
    public static Paragraph Spacer() => new(new ParagraphProperties(
        new SpacingBetweenLines { Before = "0", After = "0", Line = "400", LineRule = LineSpacingRuleValues.Exact }));
    public static Paragraph PageBreak() => new(new ParagraphProperties(new SectionProperties(
        new PageSize { Width = A4W, Height = A4H },
        new PageMargin { Top = MTop, Bottom = MBot, Left = (uint)MLeft, Right = (uint)MRight, Header = 720, Footer = 720 })));

    static RunFonts FS() => new() { Ascii = "FangSong", HighAnsi = "FangSong", EastAsia = "FangSong" };
    static RunFonts HT() => new() { Ascii = "SimHei", HighAnsi = "SimHei", EastAsia = "SimHei" };
    static RunFonts KT() => new() { Ascii = "KaiTi", HighAnsi = "KaiTi", EastAsia = "KaiTi" };
    static RunFonts XB() => new() { Ascii = "FZXiaoBiaoSong-B05", HighAnsi = "FZXiaoBiaoSong-B05", EastAsia = "FZXiaoBiaoSong-B05" };

    static ParagraphProperties CellPP() => new(
        new SpacingBetweenLines { Before = "40", After = "40", Line = "400", LineRule = LineSpacingRuleValues.Exact },
        new Indentation { FirstLine = "0" });

    static ParagraphProperties CellPPCenter() {
        var pp = CellPP();
        pp.Append(new Justification { Val = JustificationValues.Center });
        return pp;
    }

    static TableCell TCell(string text, string width, bool header = false)
    {
        var rp = new RunProperties(header ? HT() : FS(),
            new FontSize { Val = header ? "24" : "21" }, new FontSizeComplexScript { Val = header ? "24" : "21" });
        if (header) { rp.Append(new Bold()); }
        var tcp = new TableCellProperties(new TableCellWidth { Width = width, Type = TableWidthUnitValues.Dxa });
        if (header) tcp.Append(new TableCellBorders(new BottomBorder { Val = BorderValues.Single, Size = 6, Color = BLACK }));
        return new TableCell(tcp, new Paragraph(
            header ? CellPPCenter() : CellPP(),
            new Run(rp, new Text(text))));
    }
}

// ══════════════════════════════════════════════
// 数据模型
// ══════════════════════════════════════════════
public class SectionInput
{
    [JsonPropertyName("heading")] public string Heading { get; set; } = "";
    [JsonPropertyName("level")] public int Level { get; set; } = 1;
    [JsonPropertyName("paragraphs")] public List<string>? Paragraphs { get; set; }
    [JsonPropertyName("children")] public List<SectionInput>? Children { get; set; }
}
public class PolicyRef
{
    [JsonPropertyName("doc_num")] public string DocNum { get; set; } = "";
    [JsonPropertyName("name")] public string Name { get; set; } = "";
    [JsonPropertyName("clause")] public string? Clause { get; set; }
    [JsonPropertyName("url")] public string? Url { get; set; }
}
public class SealConfig
{
    [JsonPropertyName("enabled")] public bool Enabled { get; set; } = true;
    [JsonPropertyName("text")] public string Text { get; set; } = "\uFF08\u6B64\u5904\u52A0\u76D6\u516C\u7AE0\uFF09";
    [JsonPropertyName("position")] public string Position { get; set; } = "signature";
}
public class KvItem
{
    [JsonPropertyName("key")] public string Key { get; set; } = "";
    [JsonPropertyName("value")] public string Value { get; set; } = "";
}
public class KvTable
{
    [JsonPropertyName("title")] public string? Title { get; set; }
    [JsonPropertyName("items")] public List<KvItem> Items { get; set; } = new();
}
public class DataTable
{
    [JsonPropertyName("title")] public string? Title { get; set; }
    [JsonPropertyName("headers")] public List<string> Headers { get; set; } = new();
    [JsonPropertyName("rows")] public List<List<string>> Rows { get; set; } = new();
}
public class PenaltyItem
{
    [JsonPropertyName("item")] public string Item { get; set; } = "";
    [JsonPropertyName("detail")] public string Detail { get; set; } = "";
}
public class CaseInfo
{
    [JsonPropertyName("case_num")] public string? CaseNum { get; set; }
    [JsonPropertyName("party")] public string? Party { get; set; }
    [JsonPropertyName("party_id")] public string? PartyId { get; set; }
    [JsonPropertyName("party_address")] public string? PartyAddress { get; set; }
    [JsonPropertyName("legal_rep")] public string? LegalRep { get; set; }
}
public class AppealInfo
{
    [JsonPropertyName("reconsider_org")] public string? ReconsiderOrg { get; set; }
    [JsonPropertyName("reconsider_days")] public int ReconsiderDays { get; set; } = 60;
    [JsonPropertyName("lawsuit_court")] public string? LawsuitCourt { get; set; }
    [JsonPropertyName("lawsuit_days")] public int LawsuitDays { get; set; } = 6;
}
public class ContactInfo
{
    [JsonPropertyName("dept")] public string? Dept { get; set; }
    [JsonPropertyName("phone")] public string? Phone { get; set; }
}
public class MeetingInfo
{
    [JsonPropertyName("time")] public string Time { get; set; } = "";
    [JsonPropertyName("location")] public string Location { get; set; } = "";
    [JsonPropertyName("host")] public string Host { get; set; } = "";
    [JsonPropertyName("attendees")] public List<string> Attendees { get; set; } = new();
    [JsonPropertyName("recorder")] public string? Recorder { get; set; }
}
public class AgendaItem
{
    [JsonPropertyName("topic")] public string Topic { get; set; } = "";
    [JsonPropertyName("discussion")] public string? Discussion { get; set; }
    [JsonPropertyName("resolution")] public string Resolution { get; set; } = "";
    [JsonPropertyName("responsible")] public string? Responsible { get; set; }
    [JsonPropertyName("deadline")] public string? Deadline { get; set; }
}

// ── 各类型输入 ──
public class NoticeInput
{
    [JsonPropertyName("gov_org")] public string GovOrg { get; set; } = "";
    [JsonPropertyName("doc_num")] public string DocNum { get; set; } = "";
    [JsonPropertyName("title")] public string Title { get; set; } = "";
    [JsonPropertyName("send_to")] public string SendTo { get; set; } = "";
    [JsonPropertyName("date")] public string Date { get; set; } = "";
    [JsonPropertyName("cc_orgs")] public string? CcOrgs { get; set; }
    [JsonPropertyName("sections")] public List<SectionInput> Sections { get; set; } = new();
    [JsonPropertyName("policy_refs")] public List<PolicyRef>? PolicyRefs { get; set; }
    [JsonPropertyName("seal")] public SealConfig? Seal { get; set; }
}
public class ReportInput
{
    [JsonPropertyName("title")] public string Title { get; set; } = "";
    [JsonPropertyName("subtitle")] public string? Subtitle { get; set; }
    [JsonPropertyName("org")] public string Org { get; set; } = "";
    [JsonPropertyName("date")] public string Date { get; set; } = "";
    [JsonPropertyName("confidential")] public string? Confidential { get; set; }
    [JsonPropertyName("sections")] public List<SectionInput> Sections { get; set; } = new();
    [JsonPropertyName("kv_tables")] public List<KvTable>? KvTables { get; set; }
    [JsonPropertyName("data_tables")] public List<DataTable>? DataTables { get; set; }
    [JsonPropertyName("policy_refs")] public List<PolicyRef>? PolicyRefs { get; set; }
    [JsonPropertyName("seal")] public SealConfig? Seal { get; set; }
}
public class GenericInput
{
    [JsonPropertyName("title")] public string Title { get; set; } = "";
    [JsonPropertyName("subtitle")] public string? Subtitle { get; set; }
    [JsonPropertyName("org")] public string? Org { get; set; }
    [JsonPropertyName("author")] public string? Author { get; set; }
    [JsonPropertyName("date")] public string? Date { get; set; }
    [JsonPropertyName("sections")] public List<SectionInput> Sections { get; set; } = new();
    [JsonPropertyName("kv_tables")] public List<KvTable>? KvTables { get; set; }
    [JsonPropertyName("data_tables")] public List<DataTable>? DataTables { get; set; }
    [JsonPropertyName("policy_refs")] public List<PolicyRef>? PolicyRefs { get; set; }
    [JsonPropertyName("footer_note")] public string? FooterNote { get; set; }
}
public class LetterInput
{
    [JsonPropertyName("gov_org")] public string GovOrg { get; set; } = "";
    [JsonPropertyName("doc_num")] public string DocNum { get; set; } = "";
    [JsonPropertyName("title")] public string Title { get; set; } = "";
    [JsonPropertyName("send_to")] public string SendTo { get; set; } = "";
    [JsonPropertyName("date")] public string Date { get; set; } = "";
    [JsonPropertyName("cc_orgs")] public string? CcOrgs { get; set; }
    [JsonPropertyName("sections")] public List<SectionInput> Sections { get; set; } = new();
    [JsonPropertyName("contact")] public ContactInfo? Contact { get; set; }
    [JsonPropertyName("seal")] public SealConfig? Seal { get; set; }
}
public class ResolutionInput
{
    [JsonPropertyName("subtype")] public string Subtype { get; set; } = "\u8BF7\u793A";
    [JsonPropertyName("gov_org")] public string GovOrg { get; set; } = "";
    [JsonPropertyName("doc_num")] public string DocNum { get; set; } = "";
    [JsonPropertyName("title")] public string Title { get; set; } = "";
    [JsonPropertyName("send_to")] public string SendTo { get; set; } = "";
    [JsonPropertyName("date")] public string Date { get; set; } = "";
    [JsonPropertyName("cc_orgs")] public string? CcOrgs { get; set; }
    [JsonPropertyName("ref_doc")] public string? RefDoc { get; set; }
    [JsonPropertyName("sections")] public List<SectionInput> Sections { get; set; } = new();
    [JsonPropertyName("conclusion")] public string? Conclusion { get; set; }
    [JsonPropertyName("seal")] public SealConfig? Seal { get; set; }
}
public class MinutesInput
{
    [JsonPropertyName("gov_org")] public string GovOrg { get; set; } = "";
    [JsonPropertyName("doc_num")] public string DocNum { get; set; } = "";
    [JsonPropertyName("title")] public string Title { get; set; } = "";
    [JsonPropertyName("meeting_info")] public MeetingInfo MeetingInfo { get; set; } = new();
    [JsonPropertyName("agenda_items")] public List<AgendaItem> AgendaItems { get; set; } = new();
    [JsonPropertyName("date")] public string Date { get; set; } = "";
    [JsonPropertyName("cc_orgs")] public string? CcOrgs { get; set; }
    [JsonPropertyName("seal")] public SealConfig? Seal { get; set; }
}
public class DecisionInput
{
    [JsonPropertyName("gov_org")] public string GovOrg { get; set; } = "";
    [JsonPropertyName("doc_num")] public string DocNum { get; set; } = "";
    [JsonPropertyName("title")] public string Title { get; set; } = "";
    [JsonPropertyName("send_to")] public string? SendTo { get; set; }
    [JsonPropertyName("date")] public string Date { get; set; } = "";
    [JsonPropertyName("cc_orgs")] public string? CcOrgs { get; set; }
    [JsonPropertyName("case_info")] public CaseInfo? CaseInfo { get; set; }
    [JsonPropertyName("facts")] public List<string>? Facts { get; set; }
    [JsonPropertyName("legal_basis")] public List<PolicyRef>? LegalBasis { get; set; }
    [JsonPropertyName("penalties")] public List<PenaltyItem>? Penalties { get; set; }
    [JsonPropertyName("sections")] public List<SectionInput>? Sections { get; set; }
    [JsonPropertyName("appeal_info")] public AppealInfo? AppealInfo { get; set; }
    [JsonPropertyName("seal")] public SealConfig? Seal { get; set; }
}

// ══════════════════════════════════════════════
// 版本对比 / 修订标记引擎
// ══════════════════════════════════════════════
public static class GovDocDiff
{
    static readonly JsonSerializerOptions JsonOpts = new()
    {
        PropertyNameCaseInsensitive = true,
        ReadCommentHandling = JsonCommentHandling.Skip,
        AllowTrailingCommas = true
    };

    /// <summary>
    /// 对比两个 JSON 输入，生成带修订标记的 docx。
    /// 策略：以 new 版本为基础渲染，对比 old 版本的 sections，
    /// 将差异标记为 Track Changes（插入/删除）。
    /// </summary>
    public static void RenderDiff(string docType, string oldPath, string newPath, string outputPath)
    {
        if (!File.Exists(oldPath)) { Console.WriteLine($"❌ 旧版文件不存在：{oldPath}"); Environment.Exit(1); }
        if (!File.Exists(newPath)) { Console.WriteLine($"❌ 新版文件不存在：{newPath}"); Environment.Exit(1); }

        // 先正常渲染新版本
        GovDocRenderer.RenderSingle(docType, newPath, outputPath);
        if (!File.Exists(outputPath)) { Console.WriteLine("❌ 基础文档生成失败"); Environment.Exit(1); }

        // 解析新旧版本的 sections 用于对比
        var oldJson = File.ReadAllText(oldPath);
        var newJson = File.ReadAllText(newPath);

        var oldSections = ExtractSections(oldJson);
        var newSections = ExtractSections(newJson);

        // 打开生成的 docx，注入修订标记
        using var doc = WordprocessingDocument.Open(outputPath, true);
        var mainPart = doc.MainDocumentPart!;
        var body = mainPart.Document.Body!;

        // 启用修订追踪
        EnableTrackRevisions(mainPart);

        // 对比并标记差异
        var revisionId = 1;
        var author = "NexAU \u667A\u80FD\u4F53";  // NexAU 智能体

        // 收集所有正文段落（跳过版头、标题等结构元素）
        var paragraphs = body.Elements<Paragraph>().ToList();

        // 构建新旧版本的段落文本映射
        var oldTexts = FlattenSections(oldSections);
        var newTexts = FlattenSections(newSections);

        // 简单 LCS diff
        var diff = ComputeDiff(oldTexts, newTexts);

        // 在文档末尾添加修订摘要
        body.InsertBefore(new Paragraph(new ParagraphProperties(
            new SpacingBetweenLines { Before = "600" })), body.Elements<SectionProperties>().FirstOrDefault());

        var summaryPara = new Paragraph(
            new ParagraphProperties(
                new ParagraphBorders(new TopBorder { Val = BorderValues.Single, Size = 4, Color = "999999", Space = 1 }),
                new SpacingBetweenLines { Before = "200", After = "100" },
                new Indentation { FirstLine = "0" }),
            new Run(new RunProperties(
                new RunFonts { Ascii = "SimHei", HighAnsi = "SimHei", EastAsia = "SimHei" },
                new FontSize { Val = "24" }, new FontSizeComplexScript { Val = "24" },
                new Color { Val = "666666" }),
                new Text("\u4FEE\u8BA2\u6458\u8981")));  // 修订摘要
        body.InsertBefore(summaryPara, body.Elements<SectionProperties>().FirstOrDefault());

        int insertCount = 0, deleteCount = 0, changeCount = 0;
        foreach (var d in diff)
        {
            Paragraph? diffPara = null;
            if (d.Type == DiffType.Added)
            {
                insertCount++;
                diffPara = new Paragraph(
                    new ParagraphProperties(new Indentation { FirstLine = "0" },
                        new SpacingBetweenLines { Line = "400", LineRule = LineSpacingRuleValues.Exact, After = "0" }),
                    new InsertedRun(new Run(
                        new RunProperties(
                            new RunFonts { Ascii = "FangSong", HighAnsi = "FangSong", EastAsia = "FangSong" },
                            new FontSize { Val = "21" }, new FontSizeComplexScript { Val = "21" },
                            new Color { Val = "008000" }),
                        new Text("[+] " + Truncate(d.Text, 60))))
                    { Author = author, Date = new DateTimeValue(DateTime.UtcNow), Id = (revisionId++).ToString() });
            }
            else if (d.Type == DiffType.Removed)
            {
                deleteCount++;
                diffPara = new Paragraph(
                    new ParagraphProperties(new Indentation { FirstLine = "0" },
                        new SpacingBetweenLines { Line = "400", LineRule = LineSpacingRuleValues.Exact, After = "0" }),
                    new DeletedRun(new Run(
                        new RunProperties(
                            new RunFonts { Ascii = "FangSong", HighAnsi = "FangSong", EastAsia = "FangSong" },
                            new FontSize { Val = "21" }, new FontSizeComplexScript { Val = "21" },
                            new Color { Val = "CC0000" },
                            new Strike()),
                        new DeletedText { Text = "[-] " + Truncate(d.Text, 60), Space = SpaceProcessingModeValues.Preserve }))
                    { Author = author, Date = new DateTimeValue(DateTime.UtcNow), Id = (revisionId++).ToString() });
            }

            if (diffPara != null)
                body.InsertBefore(diffPara, body.Elements<SectionProperties>().FirstOrDefault());
        }

        changeCount = insertCount + deleteCount;

        // 统计行
        var statsPara = new Paragraph(
            new ParagraphProperties(new Indentation { FirstLine = "0" },
                new SpacingBetweenLines { Before = "100", After = "200" }),
            new Run(new RunProperties(
                new RunFonts { Ascii = "FangSong", HighAnsi = "FangSong", EastAsia = "FangSong" },
                new FontSize { Val = "21" }, new FontSizeComplexScript { Val = "21" },
                new Color { Val = "999999" }),
                new Text($"\u5171 {changeCount} \u5904\u4FEE\u8BA2\uFF1A\u65B0\u589E {insertCount} \u6BB5\uFF0C\u5220\u9664 {deleteCount} \u6BB5")));
        body.InsertBefore(statsPara, body.Elements<SectionProperties>().FirstOrDefault());

        mainPart.Document.Save();
        Console.WriteLine($"✅ 修订文档：{outputPath} ({new FileInfo(outputPath).Length} bytes)");
        Console.WriteLine($"   修订统计：新增 {insertCount} 段，删除 {deleteCount} 段");
    }

    static void EnableTrackRevisions(MainDocumentPart mainPart)
    {
        var settingsPart = mainPart.DocumentSettingsPart;
        if (settingsPart == null)
        {
            settingsPart = mainPart.AddNewPart<DocumentSettingsPart>();
            settingsPart.Settings = new Settings();
        }
        var settings = settingsPart.Settings;
        if (settings.Elements<TrackRevisions>().FirstOrDefault() == null)
            settings.PrependChild(new TrackRevisions());
        settings.Save();
    }

    static List<SectionInput> ExtractSections(string json)
    {
        try
        {
            using var doc = JsonDocument.Parse(json);
            var root = doc.RootElement;
            if (root.TryGetProperty("sections", out var sectionsEl))
                return JsonSerializer.Deserialize<List<SectionInput>>(sectionsEl.GetRawText(), JsonOpts) ?? new();
        }
        catch { }
        return new();
    }

    static List<string> FlattenSections(List<SectionInput> sections)
    {
        var result = new List<string>();
        foreach (var s in sections)
        {
            result.Add($"[{s.Level}] {s.Heading}");
            if (s.Paragraphs != null) result.AddRange(s.Paragraphs);
            if (s.Children != null) result.AddRange(FlattenSections(s.Children));
        }
        return result;
    }

    enum DiffType { Same, Added, Removed }
    record DiffItem(DiffType Type, string Text);

    static List<DiffItem> ComputeDiff(List<string> oldTexts, List<string> newTexts)
    {
        // Simple LCS-based diff
        int m = oldTexts.Count, n = newTexts.Count;
        var dp = new int[m + 1, n + 1];
        for (int i = 1; i <= m; i++)
            for (int j = 1; j <= n; j++)
                dp[i, j] = oldTexts[i - 1] == newTexts[j - 1]
                    ? dp[i - 1, j - 1] + 1
                    : Math.Max(dp[i - 1, j], dp[i, j - 1]);

        // Backtrack
        var result = new List<DiffItem>();
        int ii = m, jj = n;
        while (ii > 0 || jj > 0)
        {
            if (ii > 0 && jj > 0 && oldTexts[ii - 1] == newTexts[jj - 1])
            {
                result.Add(new DiffItem(DiffType.Same, oldTexts[ii - 1]));
                ii--; jj--;
            }
            else if (jj > 0 && (ii == 0 || dp[ii, jj - 1] >= dp[ii - 1, jj]))
            {
                result.Add(new DiffItem(DiffType.Added, newTexts[jj - 1]));
                jj--;
            }
            else
            {
                result.Add(new DiffItem(DiffType.Removed, oldTexts[ii - 1]));
                ii--;
            }
        }
        result.Reverse();
        return result.Where(d => d.Type != DiffType.Same).ToList();
    }

    static string Truncate(string s, int max) => s.Length <= max ? s : s[..max] + "...";
}
