# CCL 公共服务器目录

这个仓库为 [CCL 启动器](https://github.com/Zennho/ccl)提供 Minecraft Java 版公开服务器目录快照。GitHub Actions 每天 UTC 03:15 尝试更新 `data/servers.json`，也可以手动运行；计划任务可能延迟或暂停，以文件中的更新时间为准。

目录通过各平台的公开 API 收集并按地址去重。当前来源：

- [Minecraft Java Servers](https://minecraft-java-servers.com/)（最多读取 40 页，每页 500 条；遵守匿名 API 配额）
- [minecraftservers](https://minecraftserve.rs/)
- [MCSrvList](https://mcsrvlist.com/)
- [minecraftserver.id](https://minecraftserver.id/)（Java 和跨平台服务器）
- [AnyServer](https://anyserver.pro/)
- [Cloud Client](https://cloudclient.gg/)
- [MC Server List](https://msl.appahouse.com/)

每个服务器保留来源标识；每个来源记录独立更新时间、状态与是否达到采集上限。单个来源失败时保留其上次快照，并标记为旧数据；所有来源都失败或没有有效服务器时不替换现有快照。服务器状态、人数和版本是快照，不代表实时状态，也不表示 CCL 推荐或认证。公开服务器无法保证全部被任何目录收录。

运行 `python update_catalog.py` 可手动更新，运行 `python -m unittest discover -s tests` 可执行测试；仅使用 Python 标准库。请遵守数据来源及服务器的使用规则。
