# 介山中转站 · New API 单机部署

部署在介山网关服务器上，独立运行。先通过 SSH 打开面板；持介山签发的 Key 发请求后，可以在使用日志核对渠道和扣费。公开接入和收款前需要验收真实上游、入口和账单。本站的容量目标是 **1000 条在途文本流**；[容量验收](capacity/README.md)记录了测试负载、实测结果和复测方法。

选用官方发布的 [v1.0.0-rc.51](https://github.com/QuantumNous/new-api/releases/tag/v1.0.0-rc.51)（候选版），固定应用镜像标签。单台 Linux 用 Docker Compose 运行 **New API + PostgreSQL 15 + Redis 7.4**。与[该版本的官方配置](https://github.com/QuantumNous/new-api/blob/v1.0.0-rc.51/docker-compose.yml)相比，数据库就绪才启动面板、密码在服务器生成，面板只绑定 `127.0.0.1:13000`，数据库和缓存都不映射宿主机端口。官方镜像针对 [Linux amd64 / arm64](https://github.com/QuantumNous/new-api/blob/v1.0.0-rc.51/.github/workflows/docker-build.yml) 构建。

## 1. 先看服务器，再启动

在**服务器**执行下列只读命令。用已有 SSH 登录方式；不需要发密码或私钥。先看系统架构、可用内存和磁盘，以及 80、443、13000 是否已被占。已有网站、宝塔或 1Panel 可以照常运行。

```bash
cat /etc/os-release
uname -m
free -h
df -h .
ss -ltn | grep -E ':(80|443|13000)[[:space:]]' || true
docker version --format '{{.Server.Version}}'
docker compose version
docker compose ls -a
```

需要能访问本机 Docker 的账号、现代 Compose 插件（支持 `up --wait`）、Bash、OpenSSL、curl、tar。建议 Docker Engine 28 或以上；[旧版对回环端口的隔离有例外](https://docs.docker.com/engine/network/port-publishing/)。如果缺 Docker，等看清发行版和正在运行的服务后按[对应系统安装指南](https://docs.docker.com/engine/install/)处理。如果 Compose 已有 `jieshan-new-api` 项目，先确认归属，不要覆盖。

在**本机**将 `jieshan-new-api-deploy.tar.gz` 上传，命令中的 `SERVER_ALIAS` 换成已有 SSH 别名或 `用户@服务器`；以下假设文件放在服务器的用户主目录。

```text
scp jieshan-new-api-deploy.tar.gz SERVER_ALIAS:~/
```

在**服务器**进入一个新目录解包，避免覆盖旧站。目录已经存在就先检查内容，不重复解包。下面的命令按顺序执行，上一步失败就先排查：

```bash
mkdir -m 700 ~/jieshan-trial && cd ~/jieshan-trial && tar -xzf ~/jieshan-new-api-deploy.tar.gz
cd ~/jieshan-trial/new-api-deploy
bash init-env.sh
docker compose config --quiet
docker compose pull
docker compose up -d --wait --wait-timeout 180
docker compose ps
curl -fsS http://127.0.0.1:13000/api/status
```

预期：三个服务均 healthy，状态 JSON 的 `success` 为 `true`，首次启动还没有管理员。`.env` 保存 4 个独立随机值，不要重建；重跑生成脚本会拒绝覆盖。如果服务器的 13000 被占，启动前改 `.env` 的 `APP_PORT`，并相应改本手册里的**服务器目标端口**。拉镜像失败先查服务器 DNS 和镜像仓库连通性，不用 `latest` 或陌生镜像替代。服务未就绪时在服务器本地看 `docker compose logs --tail=60 new-api postgres redis`；不要分享未经脱敏的配置和日志。应用、PostgreSQL、Redis 的资源上限分别为 **5 vCPU / 4 GiB、3 vCPU / 2 GiB、0.5 vCPU / 512 MiB**。数据库连接池最多 64 个、最多保留 16 个空闲连接；长流等待上游时不需要各占一个数据库连接。Go 内存软目标为 3 GiB，Redis 客户端池为 32。

## 2. 通过 SSH 隧道建管理员

在**本机另开终端**，保持它打开：

```text
ssh -o ExitOnForwardFailure=yes -N -L 127.0.0.1:13000:127.0.0.1:13000 SERVER_ALIAS
```

浏览器访问 `http://127.0.0.1:13000`，用[首次初始化向导](https://github.com/QuantumNous/new-api/blob/v1.0.0-rc.51/controller/setup.go)创建管理员并登录。暂时关闭公开注册、保留密码登录，不启用支付。新建一个普通测试用户，给少量测试额度。如果本机 13000 被占，只把 `-L` 的第一个端口改为例如 `13001`，浏览器也改用这个端口。无需在安全组开放 13000。隧道需要有转发权限的 SSH 登录方式；用于发布的密钥可能禁止转发。遇到 `administratively prohibited` 时改用已经获准转发的登录方式，不要修改维护密钥限制。

## 3. 验证两家上游与一次扣费

**手上有真实上游**：两家各建一个渠道，填各自的 API 基础地址和上游 Key，选双方都支持的同一模型和同一协议。渠道分别测试成功后，把它们放进相同分组，优先级主 `10`、备 `5`。开一把有限额的**介山下游 Key**发一条短请求；需要流式的客户端再测一次 `stream=true`。用管理员使用日志核对最终渠道、Token 和扣费，对照供应商的实际账单。不要为了测切换而向真实供应商大量发请求。

**没有额度或想可重复地测故障切换**：套件附两台只在 Docker 内网可访问的模拟服务。它们不连接模型供应商，不验证上游 Key，一台正常回复，一台固定返回 `429`。在服务器部署目录执行：

```bash
chmod 0644 mock-upstream.py
docker compose -f compose.yaml -f compose.smoke.yaml --profile smoke up -d mock-ok mock-limited
```

1. 在后台建一个仅供测试的分组（或用尚无对外用户的默认组）。新建两个 **OpenAI 兼容**渠道，都手工填写模型 `jieshan-smoke`，Key 随便填 `sk-local-test`。正常渠道的基础地址是 `http://mock-ok:8080`，限流渠道是 `http://mock-limited:8080`，都不加 `/v1`。该测试只覆盖非流式 Chat Completions，不使用 Responses、工具调用或生图。
2. 给该模型配置一个明确的**非零测试价格**和非零分组倍率，给普通测试用户一把限额 Key，允许这个分组和模型。先启用正常渠道、停用限流渠道。用下面命令发第一次请求，应返回「介山测试通了」。账务日志应有一条成功消费；模拟上游回报输入 12、输出 4 个 Token。
3. 启用限流渠道并把它设为优先级 `10`，正常渠道设为 `5`。在请求策略中把最多重试次数设为 `1`，确认 `429` 在自动重试范围内，测试不固定渠道、不要求原渠道、不在失败时自动禁用主渠道。**使用同一把 Key 再发一次**：客户端仍应成功；管理员对应请求应显示先尝试限流渠道、最后由正常渠道完成。对比本次前后余额，只应增加一次成功请求的应扣金额。只测手动停用渠道不能证明运行中的失败会重试。[渠道指南](https://docs.newapi.ai/zh/docs/guide/feature-guide/admin/channel) · [重试规则](https://docs.newapi.ai/zh/docs/guide/feature-guide/system-settings/settings-request-policies)

在**服务器 Bash** 中测试，提示输入时粘贴介山下游 Key；它不会进入命令历史：

```bash
read -rsp '介山测试 Key: ' js_test_key; printf '\n'
printf 'Authorization: Bearer %s\n' "$js_test_key" | curl -fsS -H @- \
  -H 'Content-Type: application/json' \
  --data '{"model":"jieshan-smoke","messages":[{"role":"user","content":"ping"}],"stream":false}' \
  http://127.0.0.1:13000/v1/chat/completions
unset js_test_key
```

试完禁用两条模拟渠道，撤销测试 Key，还原临时修改的重试策略和测试模型价格，然后 `docker compose -f compose.yaml -f compose.smoke.yaml --profile smoke stop mock-ok mock-limited`。模拟通过只证明路由和本站扣费流程；真实兼容性、真实成本和支付到账仍需另测。

## 4. 准备公开访问时才接域名

先完成管理员初始化、关掉公开注册和模拟渠道，再把域名 DNS 指向服务器，检查 A/AAAA 与实际入口一致。复用正在占用 80/443 的 Web 服务，在现有配置里增加**一个站点**；不要覆盖别的站点。没有域名就继续用 SSH 隧道。第一阶段无需 HTTPS 代理。

- 如果 Caddy 或 Nginx **直接运行在宿主机**，转发到 `127.0.0.1:13000`。Caddy 示例见包内 `Caddyfile.example`，替换示例域名和实际端口；先校验配置再重载。Caddy 默认支持 WebSocket 和 SSE 即时输出。[Caddy 反向代理说明](https://caddyserver.com/docs/caddyfile/directives/reverse_proxy)
- 宝塔/1Panel 或现有 Nginx：先辨认反代是宿主机进程还是容器。宿主机 Nginx 保留 `Host`、转发协议与客户端 IP，开启 WebSocket，关闭代理缓冲并为长请求留出读取时间。**另一只容器的 `127.0.0.1` 指向它自己**；这种情况下单建共享入口网络，只接反代和 `new-api`，目标用容器网络名 `new-api:3000`，不把数据库、Redis 接到入口网络。
- 激活公网代理前：在后台填写站点服务器地址；编辑已有 `.env`，把 `SESSION_COOKIE_SECURE` 改为 `true`，`SESSION_COOKIE_TRUSTED_URL` 改为精确的 `https://实际域名`（无路径、尾斜线、通配符）。把 `TRUSTED_PROXIES` 设为应用实际看到的前置代理地址，宿主机反代转进 Docker 时可能是桥的网关 IP；不确定时暂留 `none`，先核对再信任，否则按 IP 限流可能把所有用户当成同一个地址。[该版本的认证说明](https://github.com/QuantumNous/new-api/blob/v1.0.0-rc.51/docs/authentication.md)
- 让变量生效：`docker compose config --quiet`，然后 `docker compose up -d --no-deps --wait new-api`。打开真实 HTTPS 域名，测试登录、刷新后仍登录、退出，以及通过公开 `/v1` 发一条流式请求。数据库和 Redis 始终不需要开放端口。

## 5. 备份和恢复

在测试请求都结束、没有充值或写入的时间执行 `bash backup.sh`。它在权限受限的 `backups/` 里保存 PostgreSQL 自定义格式备份、`/data` 文件、原 `.env`、Compose 和实际镜像摘要；只有带 `COMPLETE` 的目录才算成功。`pg_restore --list` 和校验和只能验证备份可读，不能代替恢复演练。备份含渠道凭证，异机保存时加密。它不保存 Redis 的临时限流/缓存、应用文本日志或反代证书；使用日志和账户余额保存在此次备份的 PostgreSQL 中。

第一次收款或升级前，用**另一台隔离试机**恢复一次：只允许本机访问，不向真实上游或支付网关出站。将一个完整备份目录中的文件（含隐藏的 `.env`）复制到试机的全新私有目录，以该目录为工作目录，使用记录的镜像版本和摘要，确认本机没有同名 Compose 项目或旧 PostgreSQL 卷。按顺序校验并恢复，任一步失败就停下排查：

```bash
sha256sum -c SHA256SUMS
mkdir -m 700 data
tar -C data -xzf data.tar.gz
 docker compose up -d --wait postgres redis
docker compose exec -T postgres pg_restore --exit-on-error --single-transaction --no-owner --no-acl \
  -U jieshan -d jieshan_newapi < db.dump
docker compose up -d --wait new-api
```

若备份来自 HTTPS 站，恢复试机走 SSH 隧道时，只在**试机的 `.env` 副本**上把 Secure 改回 `false` 并清空可信 URL，保留原密钥。登录检查账户、余额、渠道和一次历史请求。试部署暂停用 `docker compose stop`，恢复用 `docker compose start`。升级先备份、记录镜像摘要、在隔离试机验库；升级迁移过数据库后，回退须配套恢复升级前的数据库和文件，不能只换旧镜像。

已在目标主机用模拟上游验证非流式请求和一次 `429` 切换，基于同机独立副本进行流式容量验收。恢复演练、公网入口、真实上游配额与支付到账仍需单独验证。
