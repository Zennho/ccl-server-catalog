# CCL 公共服务器目录

这个仓库为 [CCL 启动器](https://github.com/Zennho/ccl)提供 Minecraft Java 版服务器目录快照。GitHub Actions 每天 UTC 03:15 尝试更新 `data/servers.json`，也可以手动运行。GitHub 的计划任务可能延迟或暂停，实际更新时间以文件中的 `updatedAt` 为准。

数据通过 [Minecraft Java Servers 公共 API](https://minecraft-java-servers.com/api) 获取，最多读取前 2500 条。服务器状态、人数和版本是快照，可能已经变化；它们不是 CCL 推荐或认证。API 更新失败时保留上一份成功的快照。请遵守数据来源及服务器的使用规则。

运行 `python update_catalog.py` 可手动更新，`python -m unittest discover -s tests` 可运行测试。只使用 Python 标准库。
