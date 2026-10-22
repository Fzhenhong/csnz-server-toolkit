# CSNZ 鉴权服务

跑在云服务器上，与 CSNZ 服务端同机。登录器通过它验证账号，读的是
`UserDatabase.db3`（SQLite 本地文件）。

## 为什么必须有这一层

三个硬性事实：

1. `UserDatabase.db3` 是本地 SQLite 文件，玩家电脑上没有、也不该有
2. 服务端 `LoginUser(IExtendedSocket*, ...)` 要求已建立的游戏 socket，
   外部程序无法「替玩家登录」
3. 服务端没有任何 HTTP / RPC 管理接口

所以登录器要验证账号，只能中间加一层能读到数据库的服务。

## 启动

> **推荐方式**：不用手动启动。在 CSNZ 服务端管理工具的「服务器配置」页点
> 「启动服务端」，会连同鉴权服务一起拉起；也可单独点「启动鉴权」。
> 下面的命令行方式仅在脱离管理工具时需要。


```bat
pip install -r requirements.txt
python server.py
```

默认监听 `0.0.0.0:38120`。端口可在管理工具「服务器配置」页修改，会自动同步到登录器。

## 接口

所有接口要求请求头 `X-Api-Key` 与 `config.json` 里的 `api_key` 一致。

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/health` | 健康检查 |
| POST | `/register` | 注册。body: `{username, password}` |
| POST | `/login` | 登录校验。body: `{username, password, kick_existing?}` |
| POST | `/kick` | 清掉残留会话。body: `{user_id}` |
| GET | `/status?user_id=1` | 查询账号状态 |
| GET | `/events` | 事件列表（可过滤 kind / ip / username） |
| GET | `/events/ip-summary` | 按 IP 聚合失败次数 |
| GET | `/events/stats` | 统计 + 当前限频快照 |
| POST | `/rate-limit/reset` | 解除某 IP / 账号的限频 |

`/login` 返回 `has_character`：

- `true` → 有角色，游戏内直接进大厅
- `false` → 新账号，首次进游戏会弹建角界面

若账号已在线（`UserSession` 有行），返回 409 且 `can_kick: true`，
登录器据此询问玩家是否顶号。

## 账号规则（复刻服务端）

| 项 | 规则 | 源码位置 |
|---|---|---|
| 账号 | 5-15 位，仅英文字母+数字 | `RegisterUser` |
| 密码 | 5-15 位，不能纯数字 | `RegisterUser` |
| 每 IP 注册数 | 受 `MaxRegistrationsPerIP` 限制 | `Register` |
| userID 分配 | 取自 `UserDist.userIDNext` 自增 | `Register` |

## 限频与自动封禁

防止暴力破解，两个维度独立计数：

| 维度 | 说明 |
|---|---|
| IP | 同一 IP 撞不同账号（撞库典型特征） |
| 账号 | 同一账号被不同 IP 撞 |

默认配置（`rate_limit`）：10 分钟内失败 5 次 → 锁定 10 分钟。
**登录成功立即清零**，正常玩家不会因为手滑被锁。

### 自动封禁

累计失败达到 `auto_ban.threshold`（默认 30）时，自动把 IP 写入 `IPBanList`。
服务端在 TCP 连接建立阶段就拒绝该 IP。

两个关键设计：

1. **用累计值，不是单窗口值**。单窗口在冷却结束会清零，攻击者每 10 分钟试 4 次就能永久绕过。进程内累计值不清零，才真正反映「一直在撞库」。
2. **被限频后仍继续尝试，也计入累计**。否则攻击者被限频后就停止计数，自动封禁永远触发不到。这是实测发现的缺陷，已修复。

⚠ **自动封禁是永久的，没有自动解封。** 原因是 `IPBanList` 表只有 `ip` 一列（服务端定义，不能加列），无法存过期时间。所以：

- 阈值默认 30，偏保守
- **网吧 / 校园网这类共享 IP 建议调到 100 以上**，否则一人爆破全店被封
- 误封可在 GM 工具「安全日志」页选中 IP 后点「解封 IP」

## 安全须知

**密码是明文存储、明文比对。** 服务端 SQL 是：

```sql
SELECT userID FROM User WHERE userName = ? AND password = ?
```

`User.password` 是 `VARCHAR(32)`。改成哈希会让**游戏客户端自带的登录失效**，
所以不能改。弥补手段只有：

1. **生产环境必须开 HTTPS**（`use_https: true` + 证书），否则账号密码在网络上是明文
2. `api_key` 设成长随机串
3. 鉴权服务端口不要裸奔，建议放在 Nginx/Caddy 后面并限制频率

## 部署到云服务器

```json
{
  "server_root": "..",
  "listen_host": "0.0.0.0",
  "listen_port": 38120,
  "api_key": "换成长随机串",
  "use_https": true,
  "cert_file": "cert.pem",
  "key_file": "key.pem"
}
```

`server_root` 指向 CSNZ 服务端根目录（含 `UserDatabase.db3` 和 `ServerConfig.json`）。

**注意**：鉴权服务只读账号表，不要让它写 `UserCharacter` / `UserInventory`
——那些是游戏端负责的，两边同时写会打架。
