# 数据规则

以下规则全部**逐条复刻自服务端源码**，改库时违反任何一条都可能造成数据错乱。

## 时间戳

**单位是分钟，不是秒。**

```cpp
time_t CServerInstance::GetCurrentTime() {
    return m_CurrentTime;  // timestamp in minutes
}
```

`29876183` 对应 2026-10-21 08:23 UTC。一天 = 1440。

## 道具发放

复刻 `CItemManager::AddItem` 与 `CUserDatabaseSQLite::AddInventoryItem`：

| 规则 | 说明 |
|---|---|
| 永久道具 | `status=1, inUse=1, expiryDate=0` |
| 限时道具 | `expiryDate = now + 天数 × 1440` |
| 可堆叠判定 | `Category==9` 且 `UseType∈{0,1,2}`，或 `Category==8` 且 `UseType∈{0,2}` |
| 可堆叠处理 | 同 itemID 累加 `count`，不新建行 |
| 槽位分配 | 优先复用 `itemID=0` 的空槽行；没有才用 `nextInventorySlot` 并自增 |
| 清空道具 | 写回 `itemID=0` 的空行，**不是 DELETE** |
| 密码箱（166） | 不占槽位，累加 `UserCharacter.passwordBoxes` |
| 背包上限 | 有效道具数 ≥ `InventorySlotMax`（默认 4000）视为满 |

> **绝不要自己算 `max(slot)+1`**，会与 `nextInventorySlot` 自增游标冲突。

## 装扮

`Category==12` 或 `ClassName=="Tattoo"` 的道具，入库只是**持有**，
穿上要另外写 `UserCostumeLoadout`（或 `UserZBCostumeLoadout`）。

## 账号注册

`RegisterUser` 的校验：

- 账号：5-15 位，仅英文字母 + 数字
- 密码：5-15 位，不能是纯数字

`Register` 只写 `User` 表，**不建角色**。这是刻意的——
服务端 `LoginUser` 有分支：

```cpp
if (!newUser->IsCharacterExists())
    g_PacketManager.SendCharacter(socket);   // 弹建角
else
    SendLoginPacket(newUser, character);     // 直接进大厅
```

新账号首次进游戏会弹建角界面（一次），之后直接进大厅。

`userID` 取自 `UserDist.userIDNext` 自增，不能用 `MAX(userID)+1`。

## 封禁

| 通道 | 表 | 粒度 |
|---|---|---|
| 账号 | `UserBan` | `term` 为到期分钟戳 |
| IP | `IPBanList` | 只有 ip 一列，**永久** |
| HWID | `HWIDBanList` | 只有 hwid 一列，**永久** |

`UserBan.term=0` 表示永久。服务端每分钟执行：

```sql
DELETE FROM UserBan WHERE term <= now
```

**判定封禁要看 `term` 是否过期**，不能只看 `type != 0`——
服务端没运行时过期行会残留在库里，会导致误判。

## 在线状态

以 `UserSession` 表为准：登录时 `INSERT`，登出时 `DropSession` 删除。
该表行数即当前在线会话数。

## 商城

| 规则 | 说明 |
|---|---|
| `Version` | 必须为 `1`，否则 `dbreload` 会让服务端关闭 |
| 子规格 ID | 加载时按 JSON 顺序自增分配，改完必须重载 |
| 一件道具 | 一个子规格只能卖一件道具，礼包走 `ItemRewards` |
| 字段宽度 | `duration` Int16 / `count` UInt16 / `price` UInt32 / `adType` UInt8 |

超宽会被**静默截断**（填 70000 客户端显示 4464），工具已拦截。
