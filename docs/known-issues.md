# 已知问题

这里记录的是**服务端本身的缺陷**，不是工具的问题。工具已做规避，
但你自行修改服务端或第三方工具时仍需注意。

## 1. `shopreload` 会让商品数翻倍 ⚠️

`CommandShopReload` 直接调 `g_ShopManager.Init()`，而清空列表的
`Shutdown()` 没有被调用：

```cpp
void CommandShopReload(...) {
    g_ShopManager.Init();   // m_Products.clear() 在 Shutdown() 里，没被调
    ...
}
```

所以每执行一次就在旧列表后面再追加一遍。实测：

```
初始        47 products
shopreload  94 products
shopreload  141 products
shopreload  188 products
dbreload    47 products   ← 只有它会先 Shutdown 再 Init
```

**后果**：客户端商城出现重复商品、子规格 ID 错位，玩家可能买到错误的东西。

**规避**：重载商城请用 `dbreload`。本工具商城页的按钮已改成 dbreload。

## 2. 密码明文存储

`User.password` 是 `VARCHAR(32)`，SQL 明文比对：

```sql
SELECT userID FROM User WHERE userName = ? AND password = ?
```

**为什么不能改**：游戏客户端自带的登录提交的是明文，改成哈希会让它的登录失效。
而我们又需要通过客户端的自动登录功能。

**规避**：

- 生产环境**必须开 HTTPS**（见部署指南）
- 记住密码用 DPAPI 加密存储，磁盘不留明文
- API 密钥用长随机串

## 3. `IPBanList` 没有过期字段

表结构只有 `ip` 一列，由服务端定义，**不能加列**（会让服务端读写失败）。

所以自动封禁只能永久生效，没有自动解封。

**规避**：

- 阈值默认 30 次，偏保守
- 网吧 / 校园网这类共享 IP 建议调到 100 以上
- 误封在管理工具「安全日志」页可手动解封

## 4. 监听地址写死 `0.0.0.0`

```cpp
hints.ai_flags = AI_PASSIVE;
getaddrinfo(NULL, port.c_str(), &hints, &result);
```

传 `NULL` 等价于绑定所有网卡。`ServerConfig.json` 里没有任何 IP / bind 字段。

**规避**：只能改端口，不能限定网卡。如需绑定特定 IP，只能从系统防火墙层面限制。

## 5. `stdout` 全缓冲

服务端进程的 stdout 一旦被重定向到管道就变成全缓冲（4KB），
不主动 flush，日志会卡在缓冲区里。

**规避**：以 `Logs/Server_*.log` 文件为实时源（`CFileLogger` 用
`fopen/fclose` 逐条落盘），本工具即采用此方案。

## 6. `RestartOnCrash` 会拉起脱离管控的进程

服务端自带的崩溃重启是：

```cpp
ForceEndServer();
ShellExecute(NULL, "open", szPath, NULL, NULL, 1);  // 分离进程
```

新进程不接管理工具的命令管道，会变成「工具管不到却占着端口」的孤儿进程。
实测第二个实例会直接崩在 `bind failed: 10048`。

**规避**：保持 `RestartOnCrash: false`，用管理工具的守护功能代替。
