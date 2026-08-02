# Git 远端恢复

核验时间：2026-08-02T08:56:05Z。

## 诊断

- DNS：`github.com` 成功解析为 `20.205.243.166`。
- TCP：`github.com:443` 连接成功。
- Git 仓库级与用户级 `http.proxy` / `https.proxy`：未设置。
- 进程环境 `HTTP_PROXY` / `HTTPS_PROXY` / `ALL_PROXY`：未设置。
- WinHTTP：Direct access。
- Git HTTP：显式配置为 HTTP/1.1。
- 凭据助手：Git Credential Manager；未读取凭据文件，未输出 Token。
- `git ls-remote origin` 与 `git fetch origin --prune`：本轮均退出码 0。

此前 P5 的 GitHub 443 超时为外部连通性阻断；本轮网络已恢复，未修改代理、凭据、提交或历史。

## 原 P5 分支推送

执行普通推送：

```text
git -c credential.interactive=never push -u origin feat/p5-production-acceptance-gates
```

结果：成功创建远端分支。核验如下：

- 本地 SHA：`cf37a43c444515f2c92530aab050410efac4b544`。
- 远端 SHA：`cf37a43c444515f2c92530aab050410efac4b544`。
- ahead/behind：`0/0`。
- 未 force push，未改写历史。

因此原 P5 的 `REMOTE_PUSH` 本地可控阻断已解除。P5A 分支仅在本轮整改提交完成后普通推送并再次核验。
