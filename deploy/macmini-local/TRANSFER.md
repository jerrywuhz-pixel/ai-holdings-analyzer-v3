# 复制到 Mac mini

当前项目包可以用任意方式复制到 Mac mini：AirDrop、外接盘、Finder 文件共享、`scp`、`rsync` 都可以。推荐优先使用 `rsync/scp`，因为可校验、可续传。

## 当前机器上的文件

打包输出目录：

```bash
/Users/jerry.wu/Documents/vibecodingapp/macmini-transfer
```

里面会有：

- `ai-holdings-analyzer-v3-macmini-<timestamp>.tar.gz`
- `ai-holdings-analyzer-v3-macmini-<timestamp>.tar.gz.sha256`
- `ai-holdings-analyzer-v3-macmini-<timestamp>.tar.gz.contents.txt`
- `manifest-<timestamp>.txt`
- `forbidden-<timestamp>.txt`

`forbidden-*.txt` 应为空，表示归档中没有 `.git`、`node_modules`、`.next`、真实 `.env` 等禁入内容。

## 如果 Mac mini 开启了 SSH

在 Mac mini 上打开：

`系统设置 -> 通用 -> 共享 -> 远程登录`

然后在当前机器执行：

```bash
MACMINI_HOST=<mac-mini-ip-or-hostname>
MACMINI_USER=<mac-mini-user>
ARCHIVE=$(ls -t /Users/jerry.wu/Documents/vibecodingapp/macmini-transfer/ai-holdings-analyzer-v3-macmini-*.tar.gz | head -1)
scp "$ARCHIVE" "$ARCHIVE.sha256" "$MACMINI_USER@$MACMINI_HOST:~/Downloads/"
```

也可以用 `rsync`：

```bash
rsync -avh --progress \
  /Users/jerry.wu/Documents/vibecodingapp/macmini-transfer/ai-holdings-analyzer-v3-macmini-*.tar.gz* \
  "$MACMINI_USER@$MACMINI_HOST:~/Downloads/"
```

## 在 Mac mini 上解包

```bash
cd ~/Downloads
shasum -a 256 -c ai-holdings-analyzer-v3-macmini-*.tar.gz.sha256
mkdir -p ~/Projects
tar -xzf ai-holdings-analyzer-v3-macmini-*.tar.gz -C ~/Projects
cd ~/Projects/ai-holdings-analyzer-v3-macmini-*
```

## 在 Mac mini 上启动

```bash
cp deploy/macmini-local/env.macmini.example .env.server
open -e .env.server
```

填好必要密钥后：

```bash
docker compose --env-file .env.server \
  -f docker-compose.server.yml \
  -f docker-compose.wechat-bridge.yml \
  up -d --build

./scripts/apply-server-migrations.sh

curl -fsS http://127.0.0.1:3000 >/dev/null
curl -fsS http://127.0.0.1:8000/health
curl -fsS http://127.0.0.1:8080/health
```

## 如果只能用 Finder/AirDrop

直接把 `.tar.gz` 和 `.sha256` 两个文件传到 Mac mini 的 `Downloads`，然后按“在 Mac mini 上解包”继续。
