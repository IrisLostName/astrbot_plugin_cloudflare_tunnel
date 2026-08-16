# AstrBot 插件开发规范

本文件适用于 `astrbot_plugin_cloudflare_tunnel`，供 Codex、Claude Code 及其他代码代理读取。

## 项目边界

- 本插件独立负责 `cloudflared` Tunnel 守护、启动/停止/重启和故障通知。
- Bot 后台检查是主动检查项；正常时不推送，连续失败达到配置阈值后重启 `cloudflared` 并通知绑定会话。
- `cloudflared` 连续启动失败或异常退出达到 `cloudflared_crash_limit` 后必须停止无限重启，处理配置或文件问题后通过 `/cfzt restart` 恢复。
- 订阅聚合、节点解析和订阅输出属于 `astrbot_plugin_sub_aggregator`，不要重新耦合回来。

## 修改要求

- 修改前先阅读 `main.py`、`_conf_schema.json`、`metadata.yaml` 和 README。
- 所有路径都必须按容器内路径处理；宿主机存在的文件不代表 AstrBot 容器内可见。
- `cloudflared_path`、Tunnel token 和自定义命令不得写入源码、README、测试输出或 Git 历史。
- 失败通知要避免重复刷屏；正常恢复不主动推送，除非用户明确要求增加恢复通知。
- 健康检查失败与 cloudflared 进程异常要在状态命令中区分展示，便于定位是 Bot 回源问题还是 Tunnel 问题。

## 配置与安全

- 使用 `/cfzt bind` 保存通知会话，不要硬编码 QQ 会话 ID。
- Tunnel token 一旦出现在聊天、日志或仓库中，应立即在 Cloudflare Zero Trust 中轮换；源码中只保留占位说明。
- 默认检查 Bot 容器内地址，例如 `http://127.0.0.1:6185`，不要把套有 Cloudflare Access 的公网域名作为无人值守检查地址。
- 默认路径应与实际容器部署一致，但 README 示例必须提醒用户按自己的容器路径确认。

## 验证与发布

```powershell
python -m compileall .
git diff --check
```

发布前确认 `main.py` 的 `@register` 版本与 `metadata.yaml` 一致，并确认 `.gitignore` 排除了 `__pycache__`、`*.pyc`、`cloudflared.log` 等运行产物。

