# 微博爬虫项目使用手册

本项目位于 `C:\Projects\weibo_craw`，由 `Python FastAPI` 后端和 `React` 前端组成，用于：

- 批量抓取一个或多个微博账号的发博内容、评论、图片
- 按数量上限或发布时间范围筛选抓取结果
- 在前端搜索微博账号，并批量关注 / 取关
- 查看当前登录账号的关注列表，并批量取关
- 对账号发博内容和评论区进行话题、观点、态度总结

## 1. 项目结构

```text
weibo_craw
├─ backend
│  ├─ app
│  │  ├─ core
│  │  ├─ models
│  │  ├─ services
│  │  └─ utils
│  ├─ requirements.txt
│  └─ .env.example
├─ frontend
│  ├─ src
│  ├─ package.json
│  └─ vite.config.js
├─ 开发文档.md
└─ README.md
```

## 2. 运行前准备

### 2.1 浏览器登录

当前实现默认读取本机 `Edge` 浏览器的微博 Cookie。请先确保：

- 你已经在 `Edge` 中登录微博
- 目标账号页面可以正常访问
- 本机网络可以打开 `https://weibo.com`

如果你使用的是 `Chrome`，可在 `backend/.env` 中将 `WEIBO_COOKIE_BROWSER=edge` 改成 `chrome`。

如果当前 Windows 环境无法直接读取浏览器 Cookie，可在前端“登录态设置”中填写 Cookie 兜底，也可以手工写入 `.env`：

- 在 `backend/.env` 中填写 `WEIBO_COOKIE_STRING=你的微博Cookie`
- Cookie 可从浏览器开发者工具的任意微博请求头中复制
- 如果你有多个浏览器 Profile，可同时调整 `WEIBO_BROWSER_PROFILE`

### 2.2 安装后端依赖

在项目根目录打开 PowerShell：

```powershell
python -m venv backend\.venv
backend\.venv\Scripts\Activate.ps1
pip install -r backend\requirements.txt
python -m playwright install chromium
Copy-Item backend\.env.example backend\.env
```

### 2.3 安装前端依赖

```powershell
cd frontend
npm install
cd ..
```

## 3. 启动项目

### 3.1 启动后端

```powershell
backend\.venv\Scripts\Activate.ps1
uvicorn app.main:app --app-dir backend --reload --host 127.0.0.1 --port 8000
```

后端地址：

- API: `http://127.0.0.1:8000`
- 健康检查: `http://127.0.0.1:8000/api/health`

### 3.2 启动前端

```powershell
cd frontend
npm run dev
```

前端地址：

- `http://127.0.0.1:5173`

## 4. 功能使用说明

### 4.0 登录态设置

前端首页顶部有“登录态设置”区域，会显示当前后端是否能读取微博登录态。

为什么 Edge 已登录仍可能失败：

- 微博登录态保存在 Edge 的本机 Cookie 数据库中
- Edge 运行时或 Windows 权限策略可能锁定该数据库文件
- 后端是独立 Python 进程，不能保证能直接读取正在被锁定的浏览器文件
- 这时需要把微博请求头里的 `Cookie` 复制到前端，后端会保存到本机 `backend/.env`

获取 Cookie 的简要步骤：

1. 在 Edge 打开微博页面并保持登录
2. 按 F12 打开开发者工具，进入“网络 / Network”
3. 刷新微博页面，点开任意 `weibo.com/ajax/...` 请求
4. 在 Request Headers 中复制 `Cookie` 整行内容
5. 回到前端“登录态设置”，粘贴并点击“保存 Cookie”

### 4.1 批量抓取微博内容和评论

前端的“抓取与分析”区域支持：

- 输入多个微博账号 URL 或 UID
- 设置最多抓取博文数
- 设置每条博文评论抓取上限
- 限制开始时间和结束时间
- 选择是否抓取评论
- 选择是否下载图片到本地

默认示例账号已写入：

- `https://weibo.com/u/3074452897`
- `https://weibo.com/u/1917281600`
- `https://weibo.com/u/2031482343`

抓取完成后，页面会展示：

- 账号资料
- 每条微博文本
- 微博图片
- 评论文本
- 评论图片链接
- 发博内容分析
- 评论内容分析
- 导出的 JSON 文件路径

### 4.2 批量关注 / 取关

前端“账号搜索与关注管理”区域支持：

1. 输入微博昵称、UID 或关键词搜索账号
2. 勾选多个搜索结果
3. 执行“批量关注”或“批量取关”
4. 切换到“我的关注”，加载当前登录账号的关注列表
5. 勾选已关注账号后执行“批量取关”

说明：

- 搜索账号和关注列表读取走微博 HTTP 接口，不再依赖 Playwright
- 关注 / 取关仍通过 Playwright 打开微博网页后模拟操作
- 如果首次使用失败，通常是没有执行 `python -m playwright install chromium`
- 如果微博页面结构变化，可能需要调整 `backend/app/services/follow_service.py` 里的按钮定位逻辑

### 4.3 摘要分析

当前默认是本地规则分析，不依赖外部大模型，输出：

- 高频话题
- 代表性观点
- 整体态度：正面 / 负面 / 中性 / 分化

前端会用表格和条形图展示：

- 话题出现次数
- 正面、负面、中性数量
- 代表观点列表

如果后续要切换到大模型，可在后端服务层继续扩展。

## 5. 数据输出位置

抓取出的文件默认保存在：

- 图片：`backend/data/downloads/`
- 导出 JSON：`backend/data/exports/`

后端也会通过 `/downloads/...` 静态路径提供图片访问能力。

## 6. 常见问题

### 6.1 返回 403

说明微博接口没有拿到有效登录态。优先检查：

- Edge / Chrome 是否确实已登录微博
- Cookie 是否过期
- 是否切换了浏览器
- 当前 Windows 是否阻止直接读取浏览器 Cookie 文件

如果自动读取失败，优先使用前端“登录态设置”保存 Cookie。也可以直接在 `backend/.env` 中配置：

```env
WEIBO_COOKIE_STRING=SUB=...; XSRF-TOKEN=...; ...
```

### 6.2 搜索或关注失败

优先检查：

- Playwright 浏览器是否已安装
- 微博页面是否触发风控或弹出验证
- 页面按钮文案或结构是否发生变化

### 6.3 图片下载失败

可能原因：

- 图片链接临时失效
- 网络波动
- 微博 CDN 返回限制

## 7. 开发说明

更详细的设计、模块职责、接口说明和扩展建议见根目录：

- `C:\Projects\weibo_craw\开发文档.md`
