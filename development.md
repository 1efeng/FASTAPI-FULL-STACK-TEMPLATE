# FastAPI 项目 - 开发指南

## Docker Compose

* 使用 Docker Compose 启动本地环境:

```bash
docker compose watch
```

* 然后打开浏览器访问以下地址:

应用(前端和 API 均由 FastAPI 提供服务):<http://localhost:8000>

带 Swagger UI 的自动交互式 API 文档:<http://localhost:8000/docs>

Adminer,数据库 Web 管理:<http://localhost:8080>

Traefik UI,查看代理如何处理路由:<http://localhost:8090>

**注意**:首次启动环境时,可能需要一分钟才能就绪。因为后端需要等待数据库就绪并完成所有配置。你可以查看日志来监控进度。

查看日志,在(另一个终端中)运行:

```bash
docker compose logs
```

查看某个具体服务的日志,在命令后加上服务名,例如:

```bash
docker compose logs backend
```

## Mailcatcher

Mailcatcher 是一个简单的 SMTP 服务器,用于捕获开发环境下后端发送的所有邮件。它不是真的发送邮件,而是把邮件捕获下来并在 Web 界面中展示。

它的用途:

* 在开发阶段测试邮件功能
* 检查邮件内容和格式
* 在不会真实发送邮件的前提下调试邮件相关功能

在本地使用 Docker Compose 运行时,后端会自动配置使用 Mailcatcher(SMTP 端口 1025)。所有被捕获的邮件可以在 <http://localhost:1080> 查看。

## 本地开发

Docker Compose 文件配置了每个辅助服务在 `localhost` 的不同端口上运行。

FastAPI 把构建好的前端和 API 作为一个应用在 `http://localhost:8000` 提供服务。API 路由位于 `/api` 下。

对于带热重载的前端开发,你可以单独运行本地 Vite 开发服务器。

启动本地前端开发服务器:

```bash
bun run dev
```

或者,你也可以停止 `backend` 的 Docker Compose 服务:

```bash
docker compose stop backend
```

然后本地运行后端开发服务器:

```bash
cd backend
fastapi dev app/main.py
```

## 在 `localhost.tiangolo.com` 下使用 Docker Compose

当你启动 Docker Compose 环境时,默认使用 `localhost`,每个服务使用不同端口(backend、adminer 等)。

当你部署到生产环境(或预发环境)时,应用使用一个域名。前端在 `/` 提供,API 在 `/api` 下。

在[部署](deployment.md)指南中,你可以了解 Traefik 这个已配置的代理。它是负责根据域名把流量转发到应用服务的组件。

如果你想在本地测试一切是否正常工作,可以编辑本地的 `.env` 文件,把:

```dotenv
DOMAIN=localhost.tiangolo.com
```

Docker Compose 文件会用它来配置各服务的基础域名。

Traefik 会把 `localhost.tiangolo.com` 的应用流量转发给 FastAPI,FastAPI 同时提供前端和 API。

`localhost.tiangolo.com` 是一个特殊域名,它(以及它的所有子域名)被配置为指向 `127.0.0.1`。这样你就可以用它来做本地开发。

更新之后,再次运行:

```bash
docker compose watch
```

在生产环境(例如线上)部署时,主 Traefik 是配置在 Docker Compose 文件之外的。本地开发时,[compose.override.yml](compose.override.yml) 里附带了一个 Traefik,只是为了让你测试域名是否符合预期,例如用 `localhost.tiangolo.com`。

## Docker Compose 文件和环境变量

主配置文件 `compose.yml` 包含适用于整个环境的所有配置,`docker compose` 会自动使用它。

另外还有一个 `compose.override.yml`,包含开发环境的覆盖配置,例如把源码挂载为卷。`docker compose` 会自动使用它在 `compose.yml` 之上应用覆盖。

这些 Docker Compose 文件使用 `.env` 文件中的配置,把它们作为环境变量注入到容器中。

它们还会使用脚本在调用 `docker compose` 命令之前设置的一些附加环境变量。

修改变量之后,确保重启环境:

```bash
docker compose watch
```

## .env 文件

`.env` 文件包含你所有的配置、生成的密钥和密码等。

根据你的工作流,你可能想把它从 Git 中排除,例如项目是公开的。这种情况下,你需要为 CI 工具设置一种方式,让它们在构建或部署项目时能获取到这个文件。

一种方法是把每个环境变量添加到你的 CI/CD 系统中,并修改 `compose.yml`,让它读取具体的环境变量,而不是读取 `.env` 文件。

## 预提交与代码检查

我们使用一个叫 [prek](https://prek.j178.dev/)([Pre-commit](https://pre-commit.com/) 的现代替代品)的工具做代码检查和格式化。

安装之后,它会在 git 提交之前自动运行。这样能确保代码在提交前就已经保持一致并被格式化。

你可以在项目根目录找到包含配置的 `.pre-commit-config.yaml` 文件。

#### 安装 prek 以自动运行

`prek` 已经是项目依赖的一部分。

在 `prek` 工具安装并可用之后,你需要在本地仓库中"安装"它,这样它才能在每个提交前自动运行。

使用 `uv`,你可以这样做(确保你位于 `backend` 目录内):

```bash
❯ uv run prek install -f
prek installed at `../.git/hooks/pre-commit`
```

`-f` 标志用于强制安装,以防之前已经安装过 `pre-commit` 钩子。

现在,每当你尝试提交时,例如:

```bash
git commit
```

...prek 会运行并检查、格式化你即将提交的代码,并提示你重新把这些代码用 git 添加(stage)后再提交。

然后你再次 `git add` 修改/修复过的文件,现在就可以提交了。

#### 手动运行 prek 钩子

你也可以手动对所有文件运行 `prek`,使用 `uv` 这样做:

```bash
❯ uv run prek run --all-files
check for added large files..............................................Passed
check toml...............................................................Passed
check yaml...............................................................Passed
fix end of files.........................................................Passed
trim trailing whitespace.................................................Passed
ruff.....................................................................Passed
ruff-format..............................................................Passed
biome check..............................................................Passed
```

## URL 地址

生产环境或预发环境的 URL 会使用相同的路径,但使用你自己的域名。

### 开发环境 URL

开发环境 URL,用于本地开发。

应用:<http://localhost:8000>

自动交互式文档(Swagger UI):<http://localhost:8000/docs>

自动替代文档(ReDoc):<http://localhost:8000/redoc>

Adminer:<http://localhost:8080>

Traefik UI:<http://localhost:8090>

MailCatcher:<http://localhost:1080>

### 配置了 `localhost.tiangolo.com` 的开发环境 URL

开发环境 URL,用于本地开发。

应用:<http://localhost.tiangolo.com>

自动交互式文档(Swagger UI):<http://localhost.tiangolo.com/docs>

自动替代文档(ReDoc):<http://localhost.tiangolo.com/redoc>

Adminer:<http://localhost.tiangolo.com:8080>

Traefik UI:<http://localhost.tiangolo.com:8090>

MailCatcher:<http://localhost.tiangolo.com:1080>
