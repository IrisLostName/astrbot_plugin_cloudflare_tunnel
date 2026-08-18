# Cloudflare Tunnel 守护（重构版）

本插件只守护自己创建的 `cloudflared` 进程，并检查 Bot 或订阅插件的内部健康地址。它不解析订阅、不提供订阅 HTTP 服务，也不通过 Cloudflare API 判断公网状态。

## AstrBot layout

Install the complete tree under `AstrBot/data/plugins/astrbot_plugin_cloudflare_tunnel`. Persist logs and diagnostic state under `AstrBot/data/runtime/astrbot_plugin_cloudflare_tunnel`, not inside the plugin directory. Keep third-party dependencies in `requirements.txt` and use asynchronous network I/O.



- `ASTRBOT_CF_TUNNEL_CLOUDFLARED_PATH`：容器内 cloudflared 路径；
- `ASTRBOT_CF_TUNNEL_TOKEN`：Tunnel 凭据；
- `ASTRBOT_CF_TUNNEL_RUNTIME_DIR`：持久化诊断目录；
- 任何运行环境所需的系统变量，例如 `FONTCONFIG_PATH`。

这些变量必须使用**容器内**路径。SFTP 中看到的路径不代表 AstrBot 容器可见。Bot 和订阅回源默认仅监听回环/私网；Cloudflare Access 不能保护直接暴露的源站端口，因此还必须在云防火墙关闭源站端口的公网入站。
