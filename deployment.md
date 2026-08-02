# FastAPI 项目 - 部署

你可以使用 Docker Compose 将项目部署到远程服务器。

本项目期望你有一个 Traefik 代理来处理与外部世界的通信以及 HTTPS 证书。

你可以使用 CI/CD(持续集成与持续部署)系统来自动部署,项目已经内置了使用 GitHub Actions 的配置。

但你需要先配置一些东西。🤓

## 准备

* 准备好一台可用的远程服务器。
* 为应用域名以及你想暴露的辅助服务子域名配置指向该服务器的 DNS 记录,例如 `fastapi-project.example.com`、`traefik.fastapi-project.example.com` 和 `adminer.fastapi-project.example.com`。预发环境的域名也要同样处理,例如 `staging.fastapi-project.example.com`。
* 在远程服务器上安装并配置 [Docker](https://docs.docker.com/engine/install/)(使用 Docker Engine,而不是 Docker Desktop)。

## 公共 Traefik

我们需要一个 Traefik 代理来处理入站连接和 HTTPS 证书。

下面的步骤你只需要做一次。

### Traefik Docker Compose

* 创建一个远程目录来存放你的 Traefik Docker Compose 文件:

```bash
mkdir -p /root/code/traefik-public/
```

把 Traefik Docker Compose 文件复制到你的服务器。可以在本地终端运行 `rsync` 命令来完成:

```bash
rsync -a compose.traefik.yml root@your-server.example.com:/root/code/traefik-public/
```

### Traefik 公共网络

这个 Traefik 需要一个名为 `traefik-public` 的 Docker "公共网络"来与你的环境通信。

这样一来,会有一个单一的公共 Traefik 代理处理与外部世界的通信(HTTP 和 HTTPS),在它后面,你可以有一个或多个不同域名的环境,即使它们都在同一台服务器上。

在你的远程服务器上运行以下命令来创建名为 `traefik-public` 的 Docker "公共网络":

```bash
docker network create traefik-public
```

### Traefik 环境变量

Traefik 的 Docker Compose 文件期望你在启动前于终端中设置一些环境变量。可以在远程服务器上运行以下命令来完成。

* 创建用于 HTTP Basic Auth 的用户名,例如:

```bash
export USERNAME=admin
```

* 创建用于 HTTP Basic Auth 的密码环境变量,例如:

```bash
export PASSWORD=changethis
```

* 使用 openssl 生成 HTTP Basic Auth 密码的"哈希"版本并存入环境变量:

```bash
export HASHED_PASSWORD=$(openssl passwd -apr1 $PASSWORD)
```

要验证哈希密码是否正确,可以打印它:

```bash
echo $HASHED_PASSWORD
```

* 创建包含你服务器域名的环境变量,例如:

```bash
export DOMAIN=fastapi-project.example.com
```

* 创建用于 Let's Encrypt 的邮箱环境变量,例如:

```bash
export EMAIL=admin@example.com
```

**注意**:你需要设置一个不同的邮箱,`@example.com` 的邮箱是不行的。

### 启动 Traefik Docker Compose

进入你在远程服务器上复制 Traefik Docker Compose 文件的目录:

```bash
cd /root/code/traefik-public/
```

现在环境变量已设置好、`compose.traefik.yml` 就位,你可以运行以下命令启动 Traefik Docker Compose:

```bash
docker compose -f compose.traefik.yml up -d
```

## 部署 FastAPI 项目

Traefik 就绪后,你就可以用 Docker Compose 部署 FastAPI 项目了。

**注意**:你可能想先跳到关于使用 GitHub Actions 进行持续部署的部分。

## 复制代码

```bash
rsync -av --exclude=".git/" --filter=":- .gitignore" ./ root@your-server.example.com:/root/code/app/
```

注意:`--filter=":- .gitignore"` 告诉 `rsync` 使用与 git 相同的规则,忽略被 git 忽略的文件,例如 Python 虚拟环境。

## 环境变量

你需要先设置一些环境变量。

### 生成密钥

`.env` 文件中的一些环境变量默认值是 `changethis`。

你必须把它们改成密钥,生成密钥可以运行以下命令:

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

复制输出内容作为密码 / 密钥。再运行一次生成另一个安全密钥。

### 必需的环境变量

设置 `ENVIRONMENT`,默认是 `local`(用于开发),但部署到服务器时应设置为 `staging` 或 `production`:

```bash
export ENVIRONMENT=production
```

设置 `DOMAIN`,默认是 `localhost`(用于开发),但部署时应使用你自己的域名,例如:

```bash
export DOMAIN=fastapi-project.example.com
```

将 `POSTGRES_PASSWORD` 设置为不同于 `changethis` 的值:

```bash
export POSTGRES_PASSWORD="changethis"
```

设置 `SECRET_KEY`,用于给 token 签名:

```bash
export SECRET_KEY="changethis"
```

注意:你可以用上面的 Python 命令生成一个安全密钥。

将 `FIRST_SUPERUSER_PASSWORD` 设置为不同于 `changethis` 的值:

```bash
export FIRST_SUPERUSER_PASSWORD="changethis"
```

将 `FRONTEND_HOST` 设置为应用 URL,它用于在邮件中生成链接:

```bash
export FRONTEND_HOST="https://${DOMAIN?Variable not set}"
```

你还可以设置其他一些环境变量:

* `PROJECT_NAME`:项目名称,用于 API 的文档和邮件。
* `STACK_NAME`:用于 Docker Compose 标签和项目名的栈名称,`staging`、`production` 等环境应使用不同的值。你可以用域名把点替换成短横线,例如 `fastapi-project-example-com` 和 `staging-fastapi-project-example-com`。
* `BACKEND_CORS_ORIGINS`:以逗号分隔的额外允许的 CORS 来源列表。由 FastAPI 服务的前端使用同源,不需要添加。
* `FIRST_SUPERUSER`:第一个超级用户的邮箱,这个超级用户是可以创建新用户的人。
* `SMTP_HOST`:发送邮件的 SMTP 服务器主机,通常来自你的邮件服务商(例如 Mailgun、Sparkpost、Sendgrid 等)。
* `SMTP_USER`:发送邮件的 SMTP 服务器用户。
* `SMTP_PASSWORD`:发送邮件的 SMTP 服务器密码。
* `EMAILS_FROM_EMAIL`:发送邮件的邮箱账号。
* `POSTGRES_SERVER`:PostgreSQL 服务器的主机名。可以保留默认的 `db`,由同一个 Docker Compose 提供。除非你使用第三方服务商,否则通常不需要修改。
* `POSTGRES_PORT`:PostgreSQL 服务器的端口。可以保留默认值。除非你使用第三方服务商,否则通常不需要修改。
* `POSTGRES_USER`:Postgres 用户,可以保留默认值。
* `POSTGRES_DB`:此应用使用的数据库名称。可以保留默认的 `app`。
* `SENTRY_DSN`:如果你使用 Sentry,这是它的 DSN。

## GitHub Actions 环境变量

还有一些仅由 GitHub Actions 使用、你可以配置的环境变量:

* `LATEST_CHANGES`:由 GitHub Action [latest-changes](https://github.com/tiangolo/latest-changes) 使用,根据合并的 PR 自动添加发布说明。它是一个个人访问令牌,详情请阅读其文档。
* `SMOKESHOW_AUTH_KEY`:用于使用 [Smokeshow](https://github.com/samuelcolvin/smokeshow) 处理和发布代码覆盖率,按照它的说明创建一个(免费的)Smokeshow key。

### 使用 Docker Compose 部署

环境变量就绪后,你可以用 Docker Compose 部署:

```bash
cd /root/code/app/
docker compose -f compose.yml build
docker compose -f compose.yml up -d
```

生产环境不需要 `compose.override.yml` 中的覆盖配置,这就是为什么我们显式指定使用 `compose.yml`。

## 持续部署(CD)

你可以使用 GitHub Actions 自动部署项目。😎

你可以配置多个环境的部署。

项目已经配置了 `staging` 和 `production` 两个环境。🚀

### 安装 GitHub Actions Runner

* 在远程服务器上为你的 GitHub Actions 创建一个用户:

```bash
sudo adduser github
```

* 给 `github` 用户添加 Docker 权限:

```bash
sudo usermod -aG docker github
```

* 临时切换到 `github` 用户:

```bash
sudo su - github
```

* 进入 `github` 用户的主目录:

```bash
cd
```

* [按照官方指南安装 GitHub Action 自托管 runner](https://docs.github.com/en/actions/hosting-your-own-runners/managing-self-hosted-runners/adding-self-hosted-runners#adding-a-self-hosted-runner-to-a-repository)。

* 当被询问标签时,为环境添加一个标签,例如 `production`。你也可以稍后再添加标签。

安装后,指南会告诉你运行一个命令启动 runner。但如果你终止该进程,或者与服务器的本地连接断开,它就会停止。

为了确保它开机自启并持续运行,你可以把它安装为服务。要做到这一点,退出 `github` 用户,回到 `root` 用户:

```bash
exit
```

这样做之后,你会回到之前的用户,以及之前属于该用户的目录。

在进入 `github` 用户目录之前,你需要先成为 `root` 用户(你可能已经是了):

```bash
sudo su
```

* 作为 `root` 用户,进入 `github` 用户主目录下的 `actions-runner` 目录:

```bash
cd /home/github/actions-runner
```

* 以 `github` 用户的身份将自托管 runner 安装为服务:

```bash
./svc.sh install github
```

* 启动服务:

```bash
./svc.sh start
```

* 查看服务状态:

```bash
./svc.sh status
```

你可以在官方指南中了解更多:[将自托管 runner 应用配置为服务](https://docs.github.com/en/actions/hosting-your-own-runners/managing-self-hosted-runners/configuring-the-self-hosted-runner-application-as-a-service)。

### 配置 GitHub Environments

部署工作流为 `staging` 和 `production` 使用 [GitHub Environments](https://docs.github.com/en/actions/how-tos/deploy/configure-and-manage-deployments/manage-environments)。这样可以启用环境专属的 secrets、部署保护规则(例如必需审核人、等待计时器)以及部署状态跟踪。

要配置它们,进入仓库的 **Settings** > **Environments**,创建 `staging` 和 `production` 环境。

### 设置 Secrets

为每个 GitHub Environment(`staging` 和 `production`)配置必需的 secrets 作为[环境 secrets](https://docs.github.com/en/actions/how-tos/write-workflows/choose-what-workflows-do/use-secrets#creating-secrets-for-an-environment)。环境 secrets 优于[仓库 secrets](https://docs.github.com/en/actions/how-tos/write-workflows/choose-what-workflows-do/use-secrets#creating-secrets-for-a-repository),因为它们被限定在特定环境内,减少了暴露范围,并与你配置的保护规则保持一致。

当前的 GitHub Actions 工作流期望以下 secrets:

* `DOMAIN_PRODUCTION`
* `DOMAIN_STAGING`
* `STACK_NAME_PRODUCTION`
* `STACK_NAME_STAGING`
* `EMAILS_FROM_EMAIL`
* `FIRST_SUPERUSER`
* `FIRST_SUPERUSER_PASSWORD`
* `POSTGRES_PASSWORD`
* `SECRET_KEY`
* `LATEST_CHANGES`
* `SMOKESHOW_AUTH_KEY`

## GitHub Action 部署工作流

`.github/workflows` 目录中已经有配置好的 GitHub Action 工作流,用于部署到各个环境(带有对应标签的 GitHub Actions runner):

* `staging`:推送到(或合并到)`master` 分支之后。
* `production`:发布 release 之后。

这两个工作流都关联到各自的 GitHub Environment,因此部署会显示在仓库的 **Environments** 部分,并遵守你配置的任何保护规则。

如果你需要添加更多环境,可以以这些作为起点。

## URL 地址

把 `fastapi-project.example.com` 替换成你自己的域名。

### 主 Traefik 仪表盘

Traefik UI: `https://traefik.fastapi-project.example.com`

### 生产环境

应用(前端和 API):`https://fastapi-project.example.com`

交互式 API 文档:`https://fastapi-project.example.com/docs`

Adminer: `https://adminer.fastapi-project.example.com`

### 预发环境

应用(前端和 API):`https://staging.fastapi-project.example.com`

交互式 API 文档:`https://staging.fastapi-project.example.com/docs`

Adminer: `https://adminer.staging.fastapi-project.example.com`
