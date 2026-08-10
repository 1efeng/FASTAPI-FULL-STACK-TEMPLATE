# FastAPI 项目 - 前端

前端使用 [Vite](https://vitejs.dev/)、[React](https://reactjs.org/)、[TypeScript](https://www.typescriptlang.org/)、[TanStack Query](https://tanstack.com/query)、[TanStack Router](https://tanstack.com/router) 和 [Tailwind CSS](https://tailwindcss.com/) 构建。

## 环境要求

- [Bun](https://bun.sh/)(推荐)或 [Node.js](https://nodejs.org/)

## 快速开始

```bash
bun install
bun run dev
```

* 然后打开浏览器访问 http://localhost:5173/。

注意,这个开发服务器不在 Docker 里运行,它用于本地开发,这也是推荐的工作流。当前端完成后,你可以构建后端 Docker 镜像并启动它,来测试生产环境类似的配置——FastAPI 在 `http://localhost:8000` 提供构建好的前端。

查看 `package.json` 文件了解其他可用选项。

### 移除前端

如果你在开发一个仅 API 的应用并想移除前端,可以轻松做到:

* 删除 `./frontend` 目录。

* 在 `backend/app/main.py` 文件中,移除 `app.frontend()` 调用。

* 在 `backend/Dockerfile` 文件中,移除前端构建阶段和 `COPY --from=frontend-build` 指令。

* 在 `compose.override.yml` 文件中,移除 `playwright` 服务。

完成,你现在拥有了一个无前端(仅 API)的应用。🤓

---

如果你想,还可以从以下位置移除 `FRONTEND_HOST` 环境变量:

* `.env`

但这只是为了清理,留着它们也不会有什么影响。

## 生成客户端

### 自动生成

* 激活后端虚拟环境。
* 在项目顶层目录运行脚本:

```bash
bash ./scripts/generate-client.sh
```

* 提交修改。

### 手动生成

* 启动 Docker Compose 环境。

* 从 `http://localhost:8000/api/v1/openapi.json` 下载 OpenAPI JSON 文件,并复制到 `frontend` 目录根目录下的新文件 `openapi.json`。

* 生成前端客户端,运行:

```bash
bun run generate-client
```

* 提交修改。

注意,每次后端发生变化(修改 OpenAPI schema)时,你都应该重新执行这些步骤来更新前端客户端。

## 使用远程 API

默认情况下,构建好的前端与 FastAPI 应用使用同源。如果你想在运行 Vite 开发服务器时使用远程 API,可以把 `VITE_API_URL` 环境变量设置为远程 API 的 URL。例如,可以在 `frontend/.env` 文件中设置:

```env
VITE_API_URL=https://my-domain.example.com
```

然后,当你运行前端时,它会用该 URL 作为 API 的基础 URL。

## 代码结构

前端代码结构如下:

* `frontend/src` - 前端主要代码。
* `frontend/src/assets` - 静态资源。
* `frontend/src/client` - 自动生成的 OpenAPI 客户端。
* `frontend/src/components` - 前端的各个组件。
* `frontend/src/hooks` - 自定义 hooks。
* `frontend/src/routes` - 前端的各个路由,包含页面。

## 使用 Playwright 进行端到端测试

前端包含使用 Playwright 的初始端到端测试。要运行这些测试,你需要让 Docker Compose 环境运行起来。用以下命令启动环境:

```bash
docker compose up -d --wait backend
```

然后,你可以用以下命令运行测试:

```bash
bunx playwright test
```

你也可以在 UI 模式下运行测试,查看浏览器并与它交互:

```bash
bunx playwright test --ui
```

停止并移除 Docker Compose 环境以及清理测试产生的数据,使用以下命令:

```bash
docker compose down -v
```

要更新测试,进入测试目录并修改现有测试文件,或根据需要添加新文件。

关于编写和运行 Playwright 测试的更多信息,请参考官方 [Playwright 文档](https://playwright.dev/docs/intro)。
