# 全栈 FastAPI 模板

<a href="https://github.com/fastapi/full-stack-fastapi-template/actions?query=workflow%3A%22Test+Docker+Compose%22" target="_blank"><img src="https://github.com/fastapi/full-stack-fastapi-template/workflows/Test%20Docker%20Compose/badge.svg" alt="Test Docker Compose"></a>
<a href="https://github.com/fastapi/full-stack-fastapi-template/actions?query=workflow%3A%22Test+Backend%22" target="_blank"><img src="https://github.com/fastapi/full-stack-fastapi-template/workflows/Test%20Backend/badge.svg" alt="Test Backend"></a>
<a href="https://coverage-badge.samuelcolvin.workers.dev/redirect/fastapi/full-stack-fastapi-template" target="_blank"><img src="https://coverage-badge.samuelcolvin.workers.dev/fastapi/full-stack-fastapi-template.svg" alt="Coverage"></a>

## 技术栈与特性

- ⚡ [**FastAPI**](https://fastapi.tiangolo.com) 用于 Python 后端 API。
  - 🧰 [SQLAlchemy](https://www.sqlalchemy.org) 用于 Python SQL 数据库交互(ORM),配合异步会话和 Alembic 管理迁移。
  - 🔍 [Pydantic](https://docs.pydantic.dev),由 FastAPI 使用,用于数据校验和配置管理。
  - 💾 [PostgreSQL](https://www.postgresql.org) 作为 SQL 数据库。
- 🚀 [React](https://react.dev) 用于前端。
  - 🧩 前端被打包进后端镜像,由 FastAPI 在 API 的同一域名下提供服务。
  - 💃 使用 TypeScript、hooks、[Vite](https://vitejs.dev) 以及现代前端技术栈的其他组件。
  - 🎨 [Tailwind CSS](https://tailwindcss.com) 和 [shadcn/ui](https://ui.shadcn.com) 用于前端组件。
  - 🤖 一个自动生成的前端客户端。
  - 🧪 [Playwright](https://playwright.dev) 用于端到端(E2E)测试。
  - 🦇 支持暗色模式。
- 🐋 [Docker Compose](https://www.docker.com) 用于开发和部署。
- 🔒 默认使用安全的密码哈希。
- 🔑 JWT(JSON Web Token)认证。
- 📫 基于邮件的密码找回。
- 📬 [Mailcatcher](https://mailcatcher.me) 用于开发环境下的本地邮件测试。
- ✅ 使用 [Pytest](https://pytest.org) 编写测试。
- 📞 [Traefik](https://traefik.io) 作为反向代理 / 负载均衡器。
- 🚢 使用 Docker Compose 的部署说明,包括如何配置 Traefik 来自动获取 HTTPS 证书。
- 🏭 基于 GitHub Actions 的 CI(持续集成)和 CD(持续部署)。

### 仪表盘登录

[![Dashboard login screenshot](img/login.png)](https://github.com/fastapi/full-stack-fastapi-template)

### 仪表盘 - 管理

[![Admin dashboard screenshot](img/dashboard.png)](https://github.com/fastapi/full-stack-fastapi-template)

### 仪表盘 - Items

[![Items dashboard screenshot](img/dashboard-items.png)](https://github.com/fastapi/full-stack-fastapi-template)

### 仪表盘 - 暗色模式

[![Dark mode dashboard screenshot](img/dashboard-dark.png)](https://github.com/fastapi/full-stack-fastapi-template)

### 交互式 API 文档

[![API docs](img/docs.png)](https://github.com/fastapi/full-stack-fastapi-template)

## 如何使用

你可以**直接 fork 或克隆**这个仓库,然后按原样使用。

✨ 开箱即用。✨

### 如何使用私有仓库

如果你想使用私有仓库,GitHub 不允许直接 fork(因为无法修改 fork 的可见性)。

但你可以这样做:

- 创建一个新的 GitHub 仓库,例如 `my-full-stack`。
- 手动克隆这个仓库,并将名称设置为你想要的项目名,例如 `my-full-stack`:

```bash
git clone git@github.com:fastapi/full-stack-fastapi-template.git my-full-stack
```

- 进入新目录:

```bash
cd my-full-stack
```

- 将 origin 设置为你的新仓库,从 GitHub 界面复制地址,例如:

```bash
git remote set-url origin git@github.com:octocat/my-full-stack.git
```

- 将这个仓库添加为另一个 "remote",以便以后获取更新:

```bash
git remote add upstream git@github.com:fastapi/full-stack-fastapi-template.git
```

- 将代码推送到你的新仓库:

```bash
git push -u origin master
```

### 从原始模板更新

克隆仓库并做了修改之后,你可能想从原始模板获取最新更新。

- 确保你已经添加了原始仓库作为 remote,可以用以下命令检查:

```bash
git remote -v

origin    git@github.com:octocat/my-full-stack.git (fetch)
origin    git@github.com:octocat/my-full-stack.git (push)
upstream    git@github.com:fastapi/full-stack-fastapi-template.git (fetch)
upstream    git@github.com:fastapi/full-stack-fastapi-template.git (push)
```

- 拉取最新修改但不合并:

```bash
git pull --no-commit upstream master
```

这会从该模板下载最新修改,但不会提交,这样你可以在提交前检查一切是否正常。

- 如果有冲突,在编辑器中解决。

- 完成之后,提交修改:

```bash
git merge --continue
```

### 配置

先复制环境变量模板:

```bash
cp .env.example .env
```

然后你可以更新 `.env` 文件中的配置来自定义项目。

在部署之前,至少要修改以下值:

- `SECRET_KEY`
- `FIRST_SUPERUSER_PASSWORD`
- `POSTGRES_PASSWORD`

你可以(也应该)通过环境变量以机密(secret)的方式传入这些值。

更多细节请阅读 [deployment.md](./deployment.md) 文档。

### 生成密钥

`.env` 文件中的一些环境变量默认值是 `changethis`。

你必须把它们改成密钥,生成密钥可以运行以下命令:

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

复制输出内容作为密码 / 密钥。再运行一次生成另一个安全密钥。

## 如何使用 - 使用 Copier 的另一种方式

这个仓库还支持使用 [Copier](https://copier.readthedocs.io) 生成新项目。

它会复制所有文件,询问你配置问题,并根据你的回答更新 `.env` 文件。

### 安装 Copier

你可以这样安装 Copier:

```bash
pip install copier
```

或者更好,如果你有 [`pipx`](https://pipx.pypa.io/),可以直接用 `pipx` 运行:

```bash
pipx install copier
```

**注意**:如果你有 `pipx`,安装 copier 是可选的,你可以直接运行它。

### 使用 Copier 生成项目

为你的新项目目录起一个名字,你会在下面用到它。例如 `my-awesome-project`。

进入作为项目父目录的目录,用你的项目名运行命令:

```bash
copier copy https://github.com/fastapi/full-stack-fastapi-template my-awesome-project --trust
```

如果你有 `pipx` 但没安装 `copier`,可以直接运行:

```bash
pipx run copier copy https://github.com/fastapi/full-stack-fastapi-template my-awesome-project --trust
```

**注意**:`--trust` 选项是必须的,用于执行一个[创建后脚本](https://github.com/fastapi/full-stack-fastapi-template/blob/master/.copier/update_dotenv.py),该脚本会更新你的 `.env` 文件。

### 输入变量

Copier 会询问你一些信息,在生成项目之前你可能需要先准备好答案。

不过不用担心,之后你随时可以在 `.env` 文件中更新任何值。

输入变量及其默认值(部分会自动生成)如下:

- `project_name`:(默认:`"FastAPI Project"`)项目名称,展示给 API 用户(在 .env 中)。
- `stack_name`:(默认:`"fastapi-project"`)用于 Docker Compose 标签和项目名的栈名称(不能有空格和句点)(在 .env 中)。
- `secret_key`:(默认:`"changethis"`)项目密钥,用于安全,存储在 .env 中,你可以用上面的方法生成一个。
- `first_superuser`:(默认:`"admin@example.com"`)第一个超级用户的邮箱(在 .env 中)。
- `first_superuser_password`:(默认:`"changethis"`)第一个超级用户的密码(在 .env 中)。
- `smtp_host`:(默认:"")用于发送邮件的 SMTP 服务器主机,稍后可以在 .env 中设置。
- `smtp_user`:(默认:"")用于发送邮件的 SMTP 用户,稍后可以在 .env 中设置。
- `smtp_password`:(默认:"")用于发送邮件的 SMTP 密码,稍后可以在 .env 中设置。
- `emails_from_email`:(默认:`"info@example.com"`)发送邮件的邮箱账号,稍后可以在 .env 中设置。
- `postgres_password`:(默认:`"changethis"`)PostgreSQL 数据库的密码,存储在 .env 中,你可以用上面的方法生成一个。
- `sentry_dsn`:(默认:"")如果你使用 Sentry,这是它的 DSN,稍后可以在 .env 中设置。

## 后端开发

后端文档:[backend/README.md](./backend/README.md)。

## 前端开发

前端文档:[frontend/README.md](./frontend/README.md)。

## 部署

部署文档:[deployment.md](./deployment.md)。

## 开发

通用开发文档:[development.md](./development.md)。

包括使用 Docker Compose、自定义本地域名、`.env` 配置等。

## 发布说明

查看 [release-notes.md](./release-notes.md) 文件。

## 许可证

全栈 FastAPI 模板根据 MIT 许可条款授权。
