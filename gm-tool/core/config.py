"""ServerConfig.json 的读取、受控编辑与校验。

只暴露工具真正该管的字段：整文件自由编辑容易被改成服务端无法解析的内容
（例如把 Port 改成非数字，CServerConfig::Load 失败 → 服启动失败）。
"""
from __future__ import annotations

import json
import shutil
from datetime import datetime
from pathlib import Path

# 字段 -> (中文名, 类型, 范围/说明[, 可选值])
# 第 4 项存在时，界面渲染为下拉框而不是输入框。
# 只有取值是「有限枚举」的字段才该有第 4 项——让用户手填数字是设计缺陷。
EDITABLE = {
    "HostName": ("服务器名", str, "显示在房间列表"),
    "Port": ("服务端监听端口", str, "TCP/UDP 端口，改动需重启服务端"),
    "MaxPlayers": ("最大在线", int, "1 - 1000"),
    "WelcomeMessage": ("登录欢迎语", str, "登录后弹窗显示"),
    "InventorySlotMax": ("背包槽上限", int, "32 - 100000，服务端默认 4000"),
    "MaxRegistrationsPerIP": ("每 IP 注册数", int, "0 - 100"),
    "BanListMaxSize": ("个人黑名单上限", int, "每用户可屏蔽的名字数"),
    # 取值来自客户端主菜单皮肤事件，源码只判断 > 0 后原样下发给客户端
    "MainMenuSkinEvent": ("主菜单皮肤", int, "选择主菜单显示的主题活动皮肤", {
        0: "无（默认）",
        5: "圣诞",
        6: "万圣节",
        7: "万圣节 + 雪",
        8: "复活节兔子",
    }),
    "CheckClientBuild": ("校验客户端版本", bool, "开启后需配 AllowedClientTimestamp"),
    "AllowedClientTimestamp": ("允许客户端时间戳", int, "需 CheckClientBuild = true"),
    "AllowedLauncherVersion": ("允许启动器版本", int, "当前 67"),
    "SSL": ("启用 SSL", bool, "需要 Data/Certs 证书"),
    "Crypt": ("启用 Crypt", bool, "EVP 加密"),
    "RestartOnCrash": ("崩溃自动重启", bool, ""),
}

METADATA_LABELS = {
    "Maplist": "地图表", "ClientTable": "客户端表", "Item": "道具主表",
    "ItemBox": "补给箱", "MatchOption": "房间选项", "ZombieWarWeaponList": "生化武器表",
    "WeaponParts": "武器部件", "GameModeList": "模式列表", "ProgressUnlock": "解锁进度",
    "WeaponPaints": "武器涂装", "ReinforceMaxLvl": "强化等级上限",
    "ReinforceMaxEXP": "强化经验上限", "ReinforceItemsExp": "强化材料经验",
    "ItemExpireTime": "道具过期表", "ScenarioTX_Common": "剧情文本(通用)",
    "ScenarioTX_Dedi": "剧情文本(专用)", "ShopItemList_Dedi": "专用服商品表",
    "ZBCompetitive": "生化竞技", "PPSystem": "PP 系统", "CodisData": "超凡武器",
    "WeaponProp": "武器属性", "RandomWeaponList": "随机武器", "ModeEvent": "模式事件",
    "HonorMoneyShop": "荣誉商城", "MileageShop": "里程商城", "EventShop": "活动商城",
    "FamilyTotalWarMap": "家族战地图", "FamilyTotalWar": "家族战",
    "WeaponAscend": "武器升华", "PerkParam": "技能参数", "Synthesis": "合成",
    "VoxelList": "体素列表", "VoxelItem": "体素道具", "VoxelConfigList": "体素配置",
}


class ServerConfig:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.data: dict = {}
        self.dirty = False

    def load(self) -> None:
        self.data = json.loads(self.path.read_text(encoding="utf-8-sig"))
        self.dirty = False

    def get(self, key: str, default=None):
        return self.data.get(key, default)

    def set(self, key: str, value) -> None:
        self.data[key] = value
        self.dirty = True

    @property
    def metadata(self) -> dict:
        return self.data.setdefault("Metadata", {})

    def set_metadata(self, key: str, enabled: bool) -> None:
        self.metadata[key] = bool(enabled)
        self.dirty = True

    def validate(self) -> list[str]:
        problems: list[str] = []
        port = str(self.data.get("Port", ""))
        if not port.isdigit() or not (1 <= int(port) <= 65535):
            problems.append(f"Port 非法：{port!r}，必须是 1-65535 的数字字符串")
        mp = self.data.get("MaxPlayers", 0)
        if not isinstance(mp, int) or not (1 <= mp <= 1000):
            problems.append(f"MaxPlayers 非法：{mp!r}，必须在 1-1000")
        slot = self.data.get("InventorySlotMax", 0)
        if not isinstance(slot, int) or slot < 32:
            problems.append(f"InventorySlotMax 非法：{slot!r}，至少 32")
        if self.data.get("CheckClientBuild"):
            ts = self.data.get("AllowedClientTimestamp", 0)
            if not isinstance(ts, int):
                problems.append("CheckClientBuild 开启时 AllowedClientTimestamp 必须是整数")
        skin = self.data.get("MainMenuSkinEvent", 0)
        choices = EDITABLE["MainMenuSkinEvent"][3]
        if skin not in choices:
            problems.append(
                f"MainMenuSkinEvent 必须是 {'/'.join(str(k) for k in choices)} "
                f"之一（当前 {skin}）"
            )
        if not isinstance(self.data.get("Metadata"), dict):
            problems.append("缺少 Metadata 段，客户端将收不到任何表")
        return problems

    def save(self, backup_dir: Path | None = None) -> Path | None:
        problems = self.validate()
        if problems:
            raise ValueError("服务端配置校验失败：\n" + "\n".join(problems))
        backup = None
        if backup_dir:
            backup_dir.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup = backup_dir / f"ServerConfig_{stamp}.json"
            if self.path.exists():
                shutil.copy2(self.path, backup)
        text = json.dumps(self.data, ensure_ascii=False, indent="\t")
        self.path.write_text(text + "\n", encoding="utf-8")
        self.dirty = False
        return backup


__all__ = ["ServerConfig", "EDITABLE", "METADATA_LABELS"]
