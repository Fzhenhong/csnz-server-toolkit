# 贡献指南

## 开发环境

- Python 3.8+
- Windows（部分功能依赖 Win32 API，如 DPAPI）

```bash
pip install -r auth-server/requirements.txt
```

管理工具与登录器**仅用标准库**，无需额外依赖。

## 代码风格

- 中文注释，解释「为什么」而不是「做了什么」
- 涉及服务端规则的代码，注释里附源码文件名
- 命名用完整单词，不用缩写

## 提交前检查

### 1. 编译检查

```bash
python -m compileall gm-tool auth-server launcher
```

### 2. 数据安全

涉及数据库写操作的改动，**必须在副本上测试**：

```python
import shutil, tempfile, pathlib
tmp = pathlib.Path(tempfile.mkdtemp())
shutil.copy2("UserDatabase.db3", tmp / "UserDatabase.db3")
# 在副本上操作
```

绝不直接改真实存档。

### 3. 规则依据

新增的配置写入规则必须能指出源码位置，例如：

```python
# 复刻自 CItemManager::AddItem：
# 可堆叠道具同 ID 累加 count，不新建行
if item.stackable and exists:
    ...
```

## PR 要求

- 一个 PR 只做一件事
- 说明改了什么、为什么改、如何验证
- 涉及界面的改动附截图

## 安全

- 不要提交 `config.json`（含密钥）
- 不要提交 `UserDatabase.db3`（含玩家数据）
- 不要提交 `*.log` / `*.mdmp`（可能含隐私）
