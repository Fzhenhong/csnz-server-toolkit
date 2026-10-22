<div align="center">

# CSNZ Server Toolkit

**Counter-Strike Online / Nexon Zombies 私服服务端管理工具**

服务端管理 · 账号鉴权，两个组件协同工作

[![Python](https://img.shields.io/badge/Python-3.8%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Platform](https://img.shields.io/badge/Platform-Windows-0078D4?logo=windows&logoColor=white)](#)
[![License](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![CSNZ Build](https://img.shields.io/badge/CSNZ%20Build-2728-blueviolet)](#)

[功能](#-功能) · [快速开始](#-快速开始) · [架构](#-架构) · [文档](#-文档) · [已知问题](#-已知问题)

</div>

---

## 这是什么

针对 **CSNZ（CSO/Nexon Zombies）服务端 Build 2728** 的一套管理工具，解决三个实际运维痛点：

- **改配置要翻十个 JSON/CSV 文件，编码还各不相同** → 图形化编辑，自动校验、自动备份
- **发道具、改点券只能敲控制台命令，还得自己查 itemID** → 3743 条道具全文检索，一键发放
- **玩家账号安全没法管控** → 独立鉴权服务，限频防爆破、自动封禁撞库 IP

所有写入规则均**逐条复刻服务端源码**，不是猜测的字段含义。

## ✨ 功能

### 🖥️ 服务端管理工具 (`gm-tool/`)

| 模块 | 能力 |
|---|---|
| **总览** | 服务端状态、在线人数、封禁计数、实时日志 |
| **用户管理** | 账号列表与搜索、封禁状态（含剩余天数）、点券/经验/等级修改、GM 权限、背包查看 |
| **道具发放** | 3743 条道具全文检索（ID/内部名/中文名/分类）、标出已持有、批量发放 |
| **商城管理** | 商品增删、档位（数量/天数/价格/返点）增删改、推荐位、热销位 |
| **服务器配置** | 端口、欢迎语、34 项 Metadata 开关、鉴权端口、服务启停 |
| **封禁管理** | 账号 / IP / HWID 三通道，一键三封 |
| **运行与日志** | 启停服务端、控制台命令、实时日志、审计记录 |
| **安全日志** | 登录失败/限频/撞库来源，一键封禁或解封 |

### 🔐 鉴权服务 (`auth-server/`)

- 账号注册 / 登录校验 / 会话踢出
- **限频防爆破**：IP 与账号双维度独立计数，成功即清零
- **自动封禁**：累计失败超阈值自动拉黑 IP
- 事件审计：登录记录、撞库来源分析

## 🚀 快速开始

### 环境要求

- Windows 10/11
- Python 3.8+（**无需 pip 安装任何依赖**，仅用标准库）
- 一份 CSNZ 服务端（Build 2728）

> 鉴权服务需要 `fastapi` 与 `uvicorn`，见 [auth-server/requirements.txt](auth-server/requirements.txt)

### 部署

```bash
git clone https://github.com/fengzhenhong/csnz-server-toolkit.git
cd csnz-server-toolkit
```

把三个目录放进 CSNZ 服务端根目录（与 `CSNZ_Server.exe` 同级）：

```
CSNZ服务端/
├── CSNZ_Server.exe
├── UserDatabase.db3
├── ServerConfig.json
├── Data/
├── gm-tool/          ← 管理工具
└── auth-server/      ← 鉴权服务
```

### 启动

1. 双击 `gm-tool/启动.bat`
2. 在「服务器配置」页点 **启动服务端**
3. 服务端（30002）与鉴权服务（38120）同时就位
4. 玩家用客户端登录器连接 `http://你的地址:38120` 完成账号验证

> 首次使用请先修改三处配置的 `api_key` 为同一长随机串，
> 详见 [部署文档](docs/deployment.md)

## 🏗️ 架构

```
┌─────────────────────────────────────────────┐
│  玩家客户端登录器             玩家电脑        │
│  注册 / 登录（调用下方接口）                 │
└──────────────────┬──────────────────────────┘
                   │ HTTPS + API Key
┌──────────────────▼──────────────────────────┐
│  鉴权服务 (auth-server)      云服务器        │
│  /register /login /kick /events             │
└──────────────────┬──────────────────────────┘
                   │ 同机读 SQLite
┌──────────────────▼──────────────────────────┐
│  CSNZ 服务端 + UserDatabase.db3             │
│  ▲                                          │
│  │ stdin 管道 / 进程守护                     │
│  ┌──────────────────────────────────┐       │
│  │  管理工具 (gm-tool)              │       │
│  └──────────────────────────────────┘       │
└─────────────────────────────────────────────┘
```

**为什么需要鉴权服务？** 三个硬性事实决定了它不可省略：

1. `UserDatabase.db3` 是本地 SQLite 文件，玩家电脑上不该有
2. 服务端 `LoginUser()` 要求已建立的游戏 socket，外部无法替玩家登录
3. 服务端没有任何 HTTP / RPC 接口

## 📚 文档

| 文档 | 内容 |
|---|---|
| [部署指南](docs/deployment.md) | 云服务器部署、端口、HTTPS、安全组 |
| [数据规则](docs/data-rules.md) | 时间戳单位、道具堆叠、槽位分配等服务端规则 |
| [已知问题](docs/known-issues.md) | 服务端缺陷与规避方案 |

## ⚠️ 已知问题

以下是**服务端自身缺陷**，工具已做规避：

| 问题 | 影响 | 规避 |
|---|---|---|
| `shopreload` 不清空旧列表 | 商品数翻倍（47→94→141→188） | 改用 `dbreload` |
| 密码明文存储 | 无法改哈希，否则游戏登录失效 | 必须开 HTTPS |
| `IPBanList` 无过期字段 | 自动封禁只能永久 | 阈值设保守，提供手动解封 |
| 监听地址写死 `0.0.0.0` | 无法绑定指定网卡 | 只能改端口 |

详见 [known-issues.md](docs/known-issues.md)

## 🤝 贡献

欢迎 Issue 与 PR。提交前请确保：

- 新增的配置写入规则有源码依据（附文件与行号）
- 涉及数据库写操作的改动在副本上测试，不碰真实存档

## 📄 License

[MIT](LICENSE)

## 免责声明

本项目仅供**私服架设与学习研究**使用，与服务端开发方无关联。
请勿用于商业用途或侵犯他人权益。
