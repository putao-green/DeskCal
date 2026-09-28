# sync-server —— 可选的跨机器同步后端

默认不需要这个目录。DeskCal 的数据存在本机 `localStorage`，只有你想让多台 Mac 共用同一个清单时才需要它。

FastAPI + SQLite，两个业务接口加一个健康检查，按条目 `updatedAt` 合并。全部依赖只有 `fastapi` 和 `uvicorn`。

## 先读这一节

这个服务没有用户体系。接口地址一旦暴露到公网，任何知道地址的人都能读到你全部待办，也能改和删。所以下面三条按顺序理解：

1. **有效的防线只有反向代理层。** nginx 按来源 IP 放行，只放 `127.0.0.1` 和你自己的出口 IP。
2. **不对外暴露也是一种选择，而且更省事。** 后端只听 `127.0.0.1`，需要同步时用 SSH 隧道把端口转到本机。出口 IP 会变的话用这种。
3. **`DESKCAL_TOKEN` 只是第二道。** 组件要能同步就得从服务器加载 `index.html`，而那个页面是公开的，写在页面里的 token 谁看源码都能拿到。它挡得住扫描器，挡不住会看源码的人，不要单独依赖它。

出口 IP 查法：在你要用组件的那个网络里执行 `curl -s ifconfig.me`。

## 接口

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/health` | 健康检查，返回 `ok`、`version`、`todos` 条数 |
| GET | `/state` | 拉全量状态，返回 `{version, updatedAt, data:{todos, cats, settings}}` |
| PUT | `/state` | 推本地状态，服务端合并后回传权威状态 |

合并规则：

1. 待办与分类按 `id` 对齐，`updatedAt` 新的胜出。
2. 请求体里显式带了 `todos` / `cats` 字段时，以客户端提交的列表为准，不在列表里的条目视为已删除。
3. 请求体里没带这两个字段时，保留服务端已有数据。只改设置就属于这种情况。
4. `settings` 整体按 `updatedAt` 取新。

上限：待办 5000 条、分类 100 个、标题 200 字。

## 环境变量

| 变量 | 默认 | 说明 |
|---|---|---|
| `DESKCAL_DB` | `/home/deskcal/data/deskcal.db` | SQLite 文件路径 |
| `DESKCAL_TOKEN` | 空 | 访问令牌。留空则不鉴权，只适合本机自用 |
| `DESKCAL_ORIGINS` | 空 | 允许的跨域来源，逗号分隔。留空表示不放行任何跨域 |

设了 `DESKCAL_TOKEN` 之后，请求要带 `x-deskcal-token` 头或 `?token=` 查询参数。

## 部署

### 方式一：不对外暴露，走 SSH 隧道

最省心的方式，适合出口 IP 不固定的情况。

```bash
# 服务器上
pip install fastapi uvicorn
mkdir -p /home/deskcal/data
cp app.py /home/deskcal/server/app.py

# 用 systemd 托管
cp deskcal.service /etc/systemd/system/deskcal.service
systemctl daemon-reload && systemctl enable --now deskcal

# 本机建立隧道，把服务器的 8002 转到本地 8002
ssh -N -L 8002:127.0.0.1:8002 你的服务器
```

然后本机跑一个只监听 `127.0.0.1` 的静态服务器把 `index.html` 发出去，让组件从这个地址加载页面，同源访问 `/api/state` 就能走通。

### 方式二：nginx 反代，按来源白名单

适合出口 IP 固定的情况。静态页面与接口都挂在同一个域名下，同源，不需要跨域。

```nginx
location /deskcal/ {
    root /home;
    index index.html;
}

location /deskcal/api/ {
    allow 127.0.0.1;
    allow 你的出口IP;
    deny all;

    proxy_pass http://127.0.0.1:8002/;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_read_timeout 30s;
}
```

```bash
nginx -t && systemctl reload nginx
```

改动前先备份配置：

```bash
cp /etc/nginx/conf.d/default.conf /etc/nginx/conf.d/default.conf.bak.$(date +%s)
```

## 验证

```bash
# 后端本身是否正常（服务器上执行）
curl -s http://127.0.0.1:8002/health

# 公网入口是否已拦住（自己机器上执行，期望 403）
curl -s -m 5 -o /dev/null -w '%{http_code}\n' http://你的服务器/deskcal/api/health
```

返回 `200` 加一段 JSON 说明白名单没生效，回去检查 `nginx -t` 的输出和配置块的位置。

## 客户端怎么接

组件的接口地址是相对路径，写在 `index.html` 里：

```js
const API_URL = new URL('api/state', location.href).href;
```

从服务器加载页面时它会解析成 `你的服务器/deskcal/api/state`。外壳的加载地址在 `DeskCalApp/App.swift` 顶部的 `LOAD_URL`，把默认的 App 内置页面换成你的服务器地址即可。

注意：换成服务器地址后，组件就依赖网络了。`LOAD_URL` 保持默认（App 内内置页面）时接口地址会解析成 `file://` 路径，同步不可用，但本地功能完全正常。这两种形态按需选择。

### 还得放开 ATS

`build_app.sh` 生成的 `Info.plist` 默认不放开发输安全策略。本地形态用 `file://`，不需要；改用 http 服务器地址同步时**必须**补上这一行，否则 WKWebView 会直接拒绝加载，界面变成那块深色错误页：

```xml
<key>NSAppTransportSecurity</key><dict><key>NSAllowsArbitraryLoads</key><true/></dict>
```

能用 https 就别用 http，那样连这一行都不用加。白名单形式比全量放开更好，但需要知道具体域名：

```xml
<key>NSAppTransportSecurity</key><dict>
  <key>NSExceptionDomains</key><dict>
    <key>你的域名</key><dict>
      <key>NSExceptionAllowsInsecureHTTPLoads</key><true/>
    </dict>
  </dict>
</dict>
```


## 备份

待办条目是不可逆删除的，动手前先留一份：

```bash
cp /home/deskcal/data/deskcal.db /home/deskcal/data/deskcal.db.bak.$(date +%Y%m%d%H%M)
```
