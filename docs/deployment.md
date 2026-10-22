# 部署指南

## 端口规划

| 服务 | 默认端口 | 可改 | 说明 |
|---|---|---|---|
| CSNZ 游戏服务端 | 30002 | 是（`ServerConfig.Port`） | TCP + UDP 共用 |
| 鉴权服务 | 38120 | 是（管理工具内可改） | 仅 TCP |
| 客户端 UDP | 27015 / 27005 | 否 | 游戏引擎固定 |

**端口只有一个来源。** 服务端源码里：

```cpp
tcpPort = udpPort = cfg.value("Port", DEFAULT_PORT);
```

TCP 与 UDP 共用同一个端口，客户端也必须连同一个，所以界面只设一次。

## 安全组

云服务器需放行：

- `30002` TCP + UDP（玩家连游戏）
- `38120` TCP（登录器连鉴权服务）

> 忘记放行鉴权端口是最常见的「登录器连不上」原因。

## API 密钥

三个配置文件必须用**同一把密钥**：

| 文件 | 字段 |
|---|---|
| `auth-server/config.json` | `api_key` |
| `gm-tool/config.json` | `auth_api_key` |

生成方式：

```bash
python -c "import secrets;print(secrets.token_hex(32).upper())"
```

修改任意一处后，另外两处必须同步，否则登录器会收到 401。

## HTTPS（生产环境必须）

密码在服务端是**明文存储、明文比对**的：

```sql
SELECT userID FROM User WHERE userName = ? AND password = ?
```

改成哈希会让游戏客户端自带的登录失效，所以无法加密存储。唯一弥补手段是传输层加密。

`auth-server/config.json`：

```json
{
  "use_https": true,
  "cert_file": "cert.pem",
  "key_file": "key.pem"
}
```

证书放在 `auth-server/` 目录下。

客户端登录器的 `auth_base_url` 也需改成 `https://`。

## 地址配置

玩家客户端登录器需要填写两个地址：

- 鉴权服务地址：`https://你的域名:38120`
- 游戏服务器地址：`你的公网IP:30002`

这两个地址必须公网可达。

## 反向代理（推荐）

用 Nginx 挂 HTTPS，鉴权服务只监听 127.0.0.1：

```nginx
server {
    listen 443 ssl;
    server_name auth.example.com;

    ssl_certificate     /etc/ssl/cert.pem;
    ssl_certificate_key /etc/ssl/key.pem;

    location / {
        proxy_pass http://127.0.0.1:38120;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header Host $host;
    }
}
```

鉴权服务会读取 `X-Forwarded-For` 首段作为真实客户端 IP，
限频与自动封禁才能按真实来源计数。

此时 `auth-server/config.json` 可设 `listen_host: "127.0.0.1"`。

## 开机自启

管理工具本身不注册服务。若需开机自启：

1. `Win + R` → `shell:startup`
2. 放入 `gm-tool/启动.bat` 的快捷方式
