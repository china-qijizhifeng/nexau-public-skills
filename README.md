# north-public-skills

面向 **North Agent Cloud（NAC）/ NexAU** 平台使用者的公开 skill 集合。

这些 skill 以 [Agent Skills](https://code.claude.com/docs/en/skills) 格式组织（`SKILL.md` +
`references/` + `templates/`），可以直接被 AI coding agent 加载，也可以当成普通文档阅读。
本仓库设计为被其他模块直接引用，因此保持公开、结构稳定、不含任何环境相关配置。

## 包含的 skill

| skill | 做什么 | 什么时候用 |
|---|---|---|
| [`nexau-artifact-builder`](nexau-artifact-builder/) | NAC / NexAU Agent 制品（Artifact）开发指南：制品结构与打包硬约束、`agent.yaml` 完整契约与校验强度、内置工具与自定义工具、Skill 设计与 Agentic Search、MCP 与子代理、中间件与内容安全护栏、环境变量与密钥注入、运行时路径边界、错误速查，以及 10 个可直接复制改造的实战模板 | 创建 Agent、写 `nexau.json` / `agent.yaml` / `tool.yaml`、开发自定义工具、打包上传制品、或制品行为不符合预期时 |

## 怎么引用

### 作为 git submodule（推荐给需要固定版本的模块）

```bash
git submodule add https://github.com/china-qijizhifeng/north-public-skills.git path/to/skills
git submodule update --init --recursive
```

### 直接 clone

```bash
git clone --depth 1 https://github.com/china-qijizhifeng/north-public-skills.git
```

### 只取其中一个 skill（sparse checkout）

```bash
git clone --depth 1 --filter=blob:none --sparse \
  https://github.com/china-qijizhifeng/north-public-skills.git
cd north-public-skills
git sparse-checkout set nexau-artifact-builder
```

### 给 AI agent 使用

把 skill 目录放进 agent 的 skill 搜索路径即可（例如 Claude Code 的 `~/.claude/skills/`
或项目内 `.claude/skills/`）：

```bash
ln -s "$PWD/nexau-artifact-builder" ~/.claude/skills/nexau-artifact-builder
```

## 约定

- **每个 skill 自包含**：`SKILL.md` 是入口，`references/` 放按需下钻的细节，
  `templates/` 放可复制改造的完整示例。不跨 skill 相互依赖。
- **按需读，不要一次性全读**：`SKILL.md` 里有导航表，指明什么问题该翻哪一份 reference。
- **不含环境相关配置**：这里只有平台契约与写法，不含任何具体部署地址、凭证或客户数据。

## 反馈

发现内容与平台实际行为不一致，欢迎提 issue —— 请附上你观察到的实际表现（报错原文 / 日志 /
复现步骤），这类反馈对修正文档最有价值。
