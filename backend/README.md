# FastAPI 项目 - 后端

## 环境要求

* [Docker](https://www.docker.com/)。
* [uv](https://docs.astral.sh/uv/) 用于 Python 包和环境管理。

## Docker Compose

按照 [../development.md](../development.md) 中的指南,使用 Docker Compose 启动本地开发环境。

## 通用工作流

默认情况下,依赖由 [uv](https://docs.astral.sh/uv/) 管理,先去安装它。

在 `./backend/` 目录下,你可以用以下命令安装所有依赖:

```console
$ uv sync
```

然后用以下命令激活虚拟环境:

```console
$ source .venv/bin/activate
```

确保你的编辑器使用正确的 Python 虚拟环境,解释器位于 `backend/.venv/bin/python`。

项目采用按业务模块分层的架构,每个模块在 `./backend/app/modules/<module>/` 下按职责拆分文件:

* `model.py` — SQLAlchemy ORM 表模型(继承 `app/core/base_model.py` 的 `BaseModel`,自动带 UUID 主键和 `created_at`/`updated_at`)。
* `repository.py` — 数据访问层,继承 `app/core/base_repository.py` 的 `BaseRepository`,只负责查询与写入,不提交事务。
* `service.py` — 业务逻辑层,负责编排仓库、校验(如邮箱唯一性)和事务提交(`commit`)。
* `schema.py` — Pydantic 请求/响应模型。
* `api.py` — 路由层,保持"薄":只做参数接收、依赖注入和响应序列化,业务逻辑委托给 Service。

路由统一通过 `app/main.py` 里的 `app.include_router(...)` 注册;公共依赖(数据库会话、当前用户、超管校验)位于 `./backend/app/core/deps.py`。新增一个业务模块时,照 `app/modules/item/` 的样子在 `modules/` 下新建目录即可。

## VS Code

项目已经配置好通过 VS Code 调试器运行后端,因此你可以使用断点、暂停并查看变量等。

配置也已设置好,你可以通过 VS Code 的 Python 测试选项卡运行测试。

## Docker Compose 覆盖配置

在开发期间,你可以在 `compose.override.yml` 文件中修改只影响本地开发环境的 Docker Compose 设置。

对该文件的修改只影响本地开发环境,不影响生产环境。因此,你可以添加有助于开发工作流的"临时"修改。

例如,后端代码目录会在 Docker 容器中同步,把修改后的代码实时复制到容器内的目录。这样你可以立即测试修改,而无需重新构建 Docker 镜像。这只应在开发时使用;生产环境应该用最新版本的后端代码构建 Docker 镜像。但在开发时,它可以让你非常快速地迭代。

还有一个命令覆盖配置,运行 `fastapi run --reload` 而不是默认的 `fastapi run`。它启动一个服务器进程(而不是生产环境中的多个),并在代码变更时重新加载进程。请注意,如果你有语法错误并保存了 Python 文件,进程会崩溃退出,容器会停止。之后,你可以修复错误后重新运行来重启容器:

```console
$ docker compose watch
```

还有一个被注释掉的 `command` 覆盖配置,你可以取消注释并注释掉默认的那个。它让后端容器运行一个"什么都不做"但保持容器存活的进程。这样你可以进入正在运行的容器并在里面执行命令,例如运行 Python 解释器测试已安装的依赖,或者启动带热重载的开发服务器。

要进入容器开启一个 `bash` 会话,你可以先启动环境:

```console
$ docker compose watch
```

然后在另一个终端中 `exec` 进入正在运行的容器:

```console
$ docker compose exec backend bash
```

你应该会看到类似下面的输出:

```console
root@7f2607af31c3:/app#
```

这表示你已经进入了容器内的 `bash` 会话,身份是 `root` 用户,位于 `/app` 目录下,这个目录里面还有一个叫 "app" 的目录,那就是你代码在容器中的位置:`/app/app`。

在那里你可以使用 `fastapi run --reload` 命令运行带热重载的调试服务器。

```console
$ fastapi run --reload app/main.py
```

...运行起来会像这样:

```console
root@7f2607af31c3:/app# fastapi run --reload app/main.py
```

然后按回车。这会运行一个在检测到代码变更时自动重载的热重载服务器。

不过,如果它没检测到变更而是遇到语法错误,它会直接报错停止。但因为容器还活着、你也还在 Bash 会话中,修好错误后可以用同样的命令快速重启(按"上箭头"和"回车")。

...正是这个细节,让"容器活着什么都不做、然后在 Bash 会话里启动热重载服务器"这种方式变得有用。

## 后端测试

测试后端运行:

```console
$ bash ./scripts/test.sh
```

测试使用 Pytest 运行,在 `./backend/tests/` 中修改和添加测试。

如果你使用 GitHub Actions,测试会自动运行。

### 测试运行中的环境

如果你的环境已经启动,只想运行测试,可以使用:

```bash
docker compose exec backend bash scripts/tests-start.sh
```

`/app/scripts/tests-start.sh` 脚本会在确保环境其他部分运行后调用 `pytest`。如果你需要向 `pytest` 传递额外参数,可以传给该命令,它们会被转发。

例如,在第一个错误处停止:

```bash
docker compose exec backend bash scripts/tests-start.sh -x
```

### 测试覆盖率

运行测试时,会生成 `htmlcov/index.html` 文件,你可以在浏览器中打开它查看测试覆盖率。

## 数据库迁移

由于本地开发时你的 app 目录作为卷挂载在容器内,你也可以在容器内用 `alembic` 命令运行迁移,迁移代码会出现在你的 app 目录中(而不是只在容器内)。这样你就可以把它提交到 git 仓库。

确保每次修改模型时都创建对应的 "revision" 并用它 "upgrade" 数据库。因为这是更新数据库表的方式,否则你的应用会出错。

* 在后端容器中启动一个交互式会话:

```console
$ docker compose exec backend bash
```

* Alembic 已经配置好:在 `./backend/app/alembic/env.py` 中导入所有模块的模型(如 `app.modules.user.model.User`、`app.modules.item.model.Item`),从而把它们的元数据注册到 `Base.metadata` 供 `autogenerate` 使用。新增模块后,记得把新的模型 import 进 `env.py`。

* 修改模型后(例如添加一列),在容器内创建 revision,例如:

```console
$ alembic revision --autogenerate -m "Add column last_name to User model"
```

* 把 alembic 目录中生成的文件提交到 git 仓库。

* 创建 revision 后,在数据库中运行迁移(这才会真正修改数据库):

```console
$ alembic upgrade head
```

如果你不想使用默认模型,想从一开始就移除/修改它们,且之前没有任何 revision,你可以删除 `./backend/app/alembic/versions/` 下的 revision 文件(`.py` Python 文件),然后按上面描述创建第一个迁移。

## 邮件模板

邮件模板位于 `./backend/app/email-templates/`。这里有两个目录:`build` 和 `src`。`src` 目录包含用于构建最终邮件模板的源文件,`build` 目录包含应用实际使用的最终邮件模板。

在继续之前,确保你的 VS Code 中安装了 [MJML 扩展](https://github.com/mjmlio/vscode-mjml)。

安装 MJML 扩展后,你可以在 `src` 目录中创建新的邮件模板。创建新的邮件模板并在编辑器中打开 `.mjml` 文件后,用 `Ctrl+Shift+P` 打开命令面板,搜索 `MJML: Export to HTML`。这会把 `.mjml` 文件转换为 `.html` 文件,然后你可以把它保存到 build 目录中。
