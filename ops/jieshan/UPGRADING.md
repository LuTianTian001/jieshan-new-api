# 介山如何维护 New API

应用代码以官方 [QuantumNous/new-api](https://github.com/QuantumNous/new-api) 的 GitHub fork 为基础。`upstream` 指向官方；`origin` 指向本项目的 [LuTianTian001/jieshan-new-api](https://github.com/LuTianTian001/jieshan-new-api)；[jieshan](https://github.com/LuTianTian001/jieshan-new-api/tree/jieshan) 是我们评审和发布的分支。首次运行的基线是 `v1.0.0-rc.51`，源码提交 `c9c6da2786b6a0912215127e78e28fbc6650c85f`。官方镜像的 OCI revision 与此提交相同，且在 Compose 中固定了摘要；第一次上线无需重编相同代码。

1. **建立维护分支**：在自己的 fork 从上述提交创建 `jieshan`。克隆自己的仓库后，添加官方远端：`git remote add upstream https://github.com/QuantumNous/new-api.git`。不把运行目录、`.env`、身份凭证、生产日志或数据库提交到 Git。
2. **合并新版本**：`git fetch upstream --tags`，阅读目标官方 release 的迁移说明。从最新 `origin/jieshan` 切临时升级分支，合并选定的官方 release 标签。检查与介山定制相关的冲突，对自己仓库的 `jieshan` 开 PR。不把官方 `main` 自动同步到服务器。
3. **验证、构建**：从审核合并后的精确提交构建镜像；构建前将该提交的发布标识写入官方构建读取的 `VERSION` 文件，OCI 标签 `org.opencontainers.image.revision` 设为完整源码 SHA，保留上游许可证与声明。将其推送到我们有写权限的镜像仓库，记录发布标签、源码 SHA、镜像摘要。来自官方仓库的 CI 默认以官方镜像名为目标；启用 fork 的构建前需改为我们自己的目标，且不配置生产 SSH 凭据到该流程。
4. **由我们决定何时上线**：先在隔离环境用两个测试渠道验证路由、扣费和数据迁移。备份线上数据库和文件后，才将运行目录 `.env` 中的 `NEW_API_IMAGE` 设置为审核过的 `仓库:发布标签@sha256:摘要`，运行 `docker compose pull new-api` 和 `docker compose up -d --no-deps --wait new-api`。升级后核对实际镜像、数据库、站点和旧网关健康；有数据库迁移时按配对备份回退。

修改镜像、连接池或资源上限后，用[容量验收](capacity/README.md)在独立项目重跑目标模型的流量形态。验收脚本从部署目录的 `compose.yaml` 和全新 `.env` 启动；如需验证自己的镜像，可在执行前将 `NEW_API_IMAGE` 设置为目标镜像的完整标签和摘要，并先拉到本机。不要拿旧版本的压测结果作为新版本的容量证明。
