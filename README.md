# 自定义学术文献推送 Skill

[English](README.en.md)

用自然语言设置研究兴趣，定期筛选文献，并保留可搜索的本地文献库与精读队列。

它面向希望自行配置文献推送的研究者，主要用于 Codex。Python 工具负责检索、去重、记录覆盖范围和归档；助手依据真实标题或摘要筛选、解读，宿主提供定时运行与通知。安装 Skill 本身不会创建后台任务。

## 可以自定义什么

| 配置 | 示例 |
|---|---|
| 研究主题 | 遥感、机器学习、电池回收，或任何自定义主题；可继续增加 |
| 篇数 | 每次最多 3、5、10 篇；不足不凑数 |
| 周期和时间 | 每日 08:00，或每周二、周五 09:15；自选时区 |
| 期刊范围 | 不限期刊、优先推荐指定期刊、仅限指定期刊、排除指定期刊 |
| 文献类型 | 研究论文、综述、数据库已识别的会议论文、单独标识的预印本 |
| 近期范围 | 例如近 30 天；保留只有年份或月份的日期精度 |
| 解读语言 | 中文或英文日报与分析 |
| 研究偏好 | 优先模型验证、开源方法、特定问题；用自由文本补充 |
| 接收方式 | 本地文献库、Codex 聊天，或另行授权的消息连接器 |

遥感四主题与机器学习仅是两个可选示例。首次初始化也可以选择空白方案。期刊分区、影响因子和单位目录不会被自动猜测；有此要求时，请提供可核验的期刊清单。

## 没有使用过 Skill？从这里开始

### 1. 安装

在支持安装 GitHub Skill 的 Codex 中发送：

```text
请使用 skill-installer 安装这个仓库根目录中的 Skill：
https://github.com/YuchenZhou0731/Daily-Academic-Literature-Update
技能名称是 literature-digest-skill。安装后验证文件，不要自动创建定时任务。
```

如果客户端不支持自动安装，可将仓库下载到本地，把仓库根目录作为 `literature-digest-skill` 文件夹放进该客户端的用户 Skill 目录；具体目录以客户端当前设置为准。`SKILL.md` 是入口，`scripts`、`assets` 和 `references` 要一起保留。

需要 Python 3.10 或更高版本。在所选 Python 环境中安装基础依赖：

```text
python -m pip install -r requirements.txt
```

### 2. 用对话设置需求

例如：

> 请使用 $literature-digest-skill 帮我配置文献推送。我关注电池回收和材料生命周期评价，每周二、周五北京时间 09:00，最多 5 篇。期刊不限，优先研究论文和综述，不收预印本。中文解读，保留本地文献库，并在本聊天推送。

助手会补问缺失信息、建立独立的私有工作区，并进行一次小规模检索。不要将邮箱、API Key、个人文献记录或运行目录上传到本仓库。

### 3. 先验收，再开启定时

检查检索结果是否符合研究方向，以及日期和证据标注是否准确。需要额外 API Key 时，只在自己的本地终端导入，不发到聊天。

如果宿主支持定时工具，再让助手创建或更新任务。确认固定采集命令可以不经每日重复审批执行；仍需单独核实第一次真正的定时触发和通知。若本机需要保持运行，关机或退出宿主后不能依赖这套本地流程继续执行。

配置中的 `schedule.enabled` 只表达意图，不能替代真实的任务登记。仓库不包含修改全局权限或关闭安全检查的脚本。

### 4. 随时修改

可以继续对助手说：

- “增加太阳能电池退化这一主题，保留原来的主题。”
- “改成每天早上七点半，最多两篇，时区为 Europe/Paris。”
- “这两本期刊改成优先关注，其他期刊仍然可以入选。”
- “只看我指定的期刊；允许预印本，但单独标识。”
- “优先有独立验证数据的工作，不要为了达到篇数而放宽相关性。”
- “把今天第二篇加入待精读，全文我稍后提供。”

修改配置会保存旧版本；主题和时间变化不会清空历史文献或推送去重记录。

## 文献来源与费用边界

| 来源 | 使用方式 |
|---|---|
| Crossref | 初始启用的公开元数据来源，无需 Key；摘要可能缺失 |
| arXiv | 可选公开来源，无需 Key；作为预印本处理 |
| OpenAlex | 用户自行提供 Key；按接口返回的每日额度和运行上限控制请求 |
| Scopus | 用户自行提供 Elsevier Key，实际能力取决于账号接口权限 |

不要求额外的模型 API Key；解读由使用 Skill 的助手完成。脚本不会购买额度，也不会把账号注册成功当作接口授权成功。其他数据库、邮件发送和消息平台不是默认已接通的能力。

Windows 的 Key 使用当前用户 DPAPI 加密；macOS 和 Linux 桌面可使用系统 Keychain / Secret Service，需要额外安装 `requirements-keyring.txt`。无可用系统密钥库的无头环境不支持该 Key 后端；仍可使用无 Key 来源。详见 [来源与密钥](references/sources.md)。

## 手动命令示例

以下在仓库根目录运行。示例先配置偏好并手动验收，不注册定时任务：

```text
python -I -B scripts/workspace.py --workspace ../literature-workspace init --preset remote-sensing
python -I -B scripts/workspace.py --workspace ../literature-workspace configure --patch examples/preferences.weekly.json --confirm
python -I -B scripts/workspace.py --workspace ../literature-workspace doctor
python -I -B scripts/digest.py --workspace ../literature-workspace collect
python -I -B scripts/digest.py --workspace ../literature-workspace prepare
```

`prepare` 生成待复核材料。助手审阅标题、摘要和覆盖信息后，编写分析 JSON，再执行 `archive`。仅执行 Python 采集并不会自动产生可信的 AI 解读，也不会自动发送消息。

添加主题：

```text
python -I -B scripts/workspace.py --workspace ../literature-workspace topic add --file examples/topic.battery-recycling.json
```

需要 Key 的来源由用户在交互式终端中导入：

```text
python -I -B scripts/workspace.py --workspace ../literature-workspace credential openalex
python -I -B scripts/workspace.py --workspace ../literature-workspace doctor --credentials
```

不要把 Key 放在命令参数、JSON 配置明文或环境变量中。本实现不读取环境变量值，也不采用匿名访问作为认证失败后的静默回退。

## 输出与可靠性

私有工作区保存 `profile.json`、SQLite 状态、来源缓存、筛选包、Markdown/HTML 日报、静态文献库和用户选定的精读材料。这些文件由 `.gitignore` 排除；发布仓库只包含代码、说明和示例。

- 同一 DOI 去重；归档与发送状态分开，重试发送不重新生成日报。
- 仅标题、已读取摘要、已完成全文阅读明确区分。
- 不将索引日期或卷期日期冒充首次在线发表日期。
- 超时、分页上限和失败窗口保留状态，不能据此声称“没有新论文”。
- 关键词匹配用于组织候选，实际入选仍由助手结合研究需求复核。
- 精读须由用户选定；附加文件不等于已经读过全文。

当前静态文献库界面和精读卡字段标签为中文，日报与解读可选择英文。不同客户端的调度和通知能力需要实际适配与验收。

## 测试和进一步说明

```text
python -I -B -X utf8 scripts/run_tests.py
```

测试使用隔离的合成数据，不需要 Key，也不发出联网请求。GitHub Actions 会在 Windows、Linux 和 macOS 上执行测试；通过这些检查不代表每个用户的网络、账号额度和定时通知已验证。

- [首次设置与修改](references/onboarding.md)
- [配置字段与示例](references/configuration.md)
- [来源与密钥](references/sources.md)
- [定时与免重复审批验收](references/scheduling.md)
- [用户选定的全文精读](references/reading.md)
- [维护这个 GitHub 仓库](docs/github-publishing.md)

## 设计参考

工作流设计参考了 [daily-literature-digest-skill](https://github.com/xuezheng627/daily-literature-digest-skill)、[literature-daily-digest](https://github.com/xczxj666/literature-daily-digest)、[research-radar-paper-vault](https://github.com/xuezheng627/research-radar-paper-vault) 和 [paper-search-mcp](https://github.com/openags/paper-search-mcp) 的公开方案。这里提供独立实现，不打包它们的脚本或服务，也不宣称具有未接入来源的搜索能力。

## 许可证

本项目采用 [MIT License](LICENSE)。
