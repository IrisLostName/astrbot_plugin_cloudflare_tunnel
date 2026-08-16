# AstrBot Cloudflare Tunnel 守护

独立守护 AstrBot 容器中的 `cloudflared`，并检查 Bot 后台或其他回源地址。正常状态不推送消息；检查连续失败达到阈值时重启 Tunnel，并向绑定会话发送通知。

## 与订阅插件的边界

| 插件 | 负责内容 |
| --- | --- |
| `astrbot_plugin_sub_aggregator` | 机场订阅拉取、节点聚合、Clash/Mihomo 输出、订阅 HTTP 出口 |
| `astrbot_plugin_cloudflare_tunnel` | cloudflared 进程、Bot 后台连通性检查、失败重启和通知 |

订阅插件不负责 HTTP/Tunnel 保活任务；本插件只检查配置中明确填写的 Bot 后台或其他回源地址。

## 安装

将完整目录放入：

```text
/AstrBot/data/plugins/astrbot_plugin_cloudflare_tunnel
```

然后重启 AstrBot，或使用 WebUI 重载插件。`cloudflared` 必须存在于 AstrBot 容器内，而不是只存在于宿主机。

## 推荐配置

| 配置 | 推荐值 | 说明 |
| --- | --- | --- |
| `cloudflared_enable` | `true` | 启用 Tunnel 守护 |
| `cloudflared_path` | `/astrbot-napcat-bjiqg3/data/bin/cloudflared` | 容器内可执行文件路径；按实际环境修改 |
| `cloudflared_token` | 重新生成的 token | 来自 Cloudflare Zero Trust Tunnel |
| `health_check_enable` | `true` | 启用 Bot/回源检查 |
| `health_check_interval_minutes` | `5` | 检查间隔 |
| `health_check_timeout_seconds` | `8` | 单次检查超时 |
| `health_check_failure_restart_threshold` | `3` 或 `5` | 连续失败后重启并通知 |
| `extra_health_checks[0].url` | `http://127.0.0.1:6185` | Bot 容器内地址，不要填 Cloudflare Access 公网域名 |
| `extra_health_checks[0].expected_statuses` | `200,302,401,403` | 登录页或鉴权页返回这些状态也视为在线 |
| `cloudflared_crash_limit` | `10` | 连续启动失败/异常退出 10 次后停止自动重启 |
| `notify_on_error` | `true` | 故障时通知绑定会话 |

如果还要检查订阅 HTTP 出口，可以在附加检查中增加：

```text
http://127.0.0.1:8077/sub/health
```

## 故障策略

### Bot 后台连续失败

1. 每个检查项独立累计失败次数。
2. 任一检查项连续失败达到 `health_check_failure_restart_threshold`，插件重启 `cloudflared`。
3. 重启原因、失败次数和目标地址会发送到 `/cfzt bind` 绑定的会话。
4. 正常状态不发送周期性“正常”消息，避免刷屏。

### cloudflared 连续崩溃

`cloudflared_crash_limit` 用于防止无限重启。连续启动失败或异常退出达到上限后，守护进入停止自动重启状态，并发送一次通知。

处理完路径、权限、命令或 Tunnel token 问题后，发送：

```text
/cfzt restart
```

该命令会清零失败计数并恢复守护。

## 指令

| 指令 | 作用 |
| --- | --- |
| `/cfzt help` | 查看帮助 |
| `/cfzt bind` | 绑定当前会话接收故障通知 |
| `/cfzt status` | 查看 cloudflared PID、最近错误、退出状态和日志路径 |
| `/cfzt checks` | 查看当前健康检查目标 |
| `/cfzt restart` | 清零失败计数并立即重启或拉起 cloudflared |

## 排查

### `FileNotFoundError`

出现类似：

```text
cloudflared 守护异常：FileNotFoundError
```

请在容器内确认文件存在且有执行权限：

```bash
ls -l /astrbot-napcat-bjiqg3/data/bin/cloudflared
chmod +x /astrbot-napcat-bjiqg3/data/bin/cloudflared
```

如果该路径是宿主机路径，必须先把文件挂载到容器内，或改成容器看到的实际路径。

### Bot 使用 Cloudflare Access

不要使用 `https://bot.example.com` 作为无人值守检查地址。Access 可能返回登录页、验证码或 403，且需要人工邮箱验证。应检查同一容器内的 Bot 地址，例如 `http://127.0.0.1:6185`；如确实检查公网回源，则使用未套 Access 的回源地址并配置允许的状态码。

## 安全

- Tunnel token 等同于 Tunnel 凭据，不能提交到 Git、README 或聊天记录。
- 如果 token 曾经泄露，请在 Cloudflare Zero Trust 中轮换或重建 Tunnel token，再填写新值。
- 日志中的 token 应脱敏；`cloudflared.log` 已加入 `.gitignore`。
- 使用 `/cfzt bind` 保存通知会话，不要把 QQ 会话 ID 硬编码到源码。

发布前运行 `python -m compileall .` 和 `git diff --check`，并确认 `AGENTS.md` 中的开发规范仍然适用。

## 插件市场

本插件的安装元数据位于仓库根目录的 `metadata.yaml`。市场源 JSON 使用独立的 registry 格式，不应把 `plugin_id`、本地目录名或 SSH 仓库地址写入插件元数据。当前市场记录由订阅聚合插件仓库中的 `plugins.json` 统一维护。
