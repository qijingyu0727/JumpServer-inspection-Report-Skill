# 仓库目录说明

当前仓库按“入口文件保持克制、实现与资料分层”的方式组织：

- `agents/`
  - Skill 运行时的 agent 配置入口。
- `assets/`
  - 静态资源目录，放 SQL、命令清单、报告模板和预编译 `jms_inspect` 二进制等不会在运行时改写的内容。
- `bin/`
  - 面向使用者的薄封装 CLI。
- `references/`
  - 使用说明、运行规则、故障排查和模板说明。
- `references/metadata/`
  - 仓库内部的辅助元数据与规划文档，例如巡检清单、任务计划、过程记录。
- `runtime/`
  - 本地运行态目录，放 profile、报告输出、浏览器缓存和虚拟环境，不作为源码目录使用。
- `scripts/`
  - 核心实现脚本与可复用执行逻辑。
- `third_party/`
  - 上游源码快照与本地补丁说明，用于维护 official 巡检引擎。

根目录仅保留真正的入口与总览文件：

- `README.md`
- `README.en.md`
- `SKILL.md`
- `requirements.txt`
- `main.py`
- `.env.example`
