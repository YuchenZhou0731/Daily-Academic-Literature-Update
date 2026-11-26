# GitHub 仓库维护入门

本仓库地址：`https://github.com/YuchenZhou0731/Daily-Academic-Literature-Update`。

## 页面上的文件有什么用

| 文件或目录 | 用途 |
|---|---|
| `README.md` | GitHub 首页的中文使用说明 |
| `README.en.md` | 英文说明 |
| `SKILL.md` | 助手读取的 Skill 入口与工作规则 |
| `agents/openai.yaml` | Codex 中的名称、简介和默认调用提示 |
| `scripts/` | 初始化、配置、检索、归档、精读及测试代码 |
| `assets/` | 用户填写值为 xxx 的配置模板与静态文献库模板 |
| `examples/` | 用户填写值为 xxx 的偏好与主题模板 |
| `references/` | 助手按需读取的详细工作说明 |
| `.github/workflows/` | 推送代码后自动运行的离线测试 |
| `.gitignore` | 避免把个人运行数据提交到 Git |
| `LICENSE` | 已选择的 MIT 开源许可 |

“仓库”用于共享代码和说明；每个使用者的文献库是另一个私有目录。邮箱、Key、数据库、原始缓存、论文全文、日报和定时任务身份都不应作为代码更新提交。

## 分享给别人

分享仓库链接即可。对方先读 README，再让其助手安装并询问自己的需求。分享这个 Skill 不会把你的个人任务、收件方式或已申请的 Key 交给对方。

## 以后怎样更新

小的说明修改可以在 GitHub 网页中编辑文件；代码或多文件修改适合先在本地完成。每次更新都应：

1. 说明要改变的用户行为，例如“增加 xxx 配置项”。
2. 修改代码、示例和对应说明，避免文档与实际能力不一致。
3. 运行 `python -I -B -X utf8 scripts/run_tests.py`。
4. 检查待提交文件中没有运行目录、密钥或真实个人资料。
5. 提交并推送，再在 GitHub 的 Actions 页面查看自动测试结果。

不要把“改了配置文件”当作“已经改好了定时任务”，也不要把“测试通过”当作“所有用户的 API 都可用”。用户反馈问题时，请提供去除密钥和个人信息后的错误状态、运行环境和最小复现步骤。

可以继续让 Codex 协助维护，例如：

> 请检查这个仓库，为用户增加 xxx 配置项；保留现有历史数据兼容性，补充针对行为的测试，更新 README，并在上传前检查是否包含私人数据。

参考：[GitHub 创建仓库说明](https://docs.github.com/en/repositories/creating-and-managing-repositories/creating-a-new-repository)、[GitHub 提交并推送修改](https://docs.github.com/en/get-started/using-git/pushing-commits-to-a-remote-repository)。
