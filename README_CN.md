# 尾盘猎手 Quant 安卓项目

## 项目结构
- `app/`：Android 原生 Kotlin + Jetpack Compose 客户端
- `backend/`：运行在 Windows 电脑或服务器上的 Python FastAPI + AkShare 行情服务
- `strategy/`：上一版 Python 选股/回测策略，请将 `overnight_auction.py` 放入此目录（或与项目根目录并列）

## 为什么 AkShare 不直接放进 APK？
AkShare 是 Python 数据采集库，依赖 Python 生态、网络请求和数据处理库。把它直接塞进原生 APK 会增加复杂度和兼容性风险。本项目采用手机 APP + Python 行情服务架构：手机负责展示与操作，电脑/服务器负责 AkShare 数据采集、筛选和回测。

## 启动行情服务（Windows）
1. 安装 Python 3.10 或更高版本。
2. 双击 `backend/start_windows.bat`。
3. 服务启动后，电脑浏览器访问 `http://127.0.0.1:8000/docs` 检查接口。
4. 手机与电脑连接同一 Wi-Fi。查电脑局域网 IPv4，例如 `192.168.1.20`。
5. 在 APP 设置里将地址改为 `http://192.168.1.20:8000`。
6. Windows 防火墙允许 Python/Uvicorn 通过专用网络的 TCP 8000 端口。

Android 模拟器可用 `http://10.0.2.2:8000`；真机不能使用这个地址。

## 生成 APK
需要 Android Studio（建议稳定版）、JDK 17、Android SDK Platform 35。
1. Android Studio -> Open -> 选择本项目 `QuantHunterAndroid` 文件夹。
2. 等待 Gradle Sync 完成。
3. Build -> Build Bundle(s) / APK(s) -> Build APK(s)。
4. APK 默认位于 `app/build/outputs/apk/debug/app-debug.apk`。
5. 将 APK 复制到安卓手机安装。首次安装可能需要允许“安装未知应用”。

命令行构建：
```bash
gradle assembleDebug
```
如果本机没有 Gradle，请使用 Android Studio 自带的 Gradle Wrapper 生成/同步项目。

## 当前功能与边界
- 原生安卓深色 UI、服务连接、扫描候选、卖出监控入口、回测入口和评分阈值设置。
- 后端 AkShare 实时快照初筛沪深主板，过滤 ST/退市名称。
- AkShare 实时快照不能保证提供历史 14:56 快照、收盘集合竞价实际成交价、次日 9:20 虚拟撮合价。
- 当前扫描返回的是“观察候选”，不是确认买入信号。尾盘增量成交量、竞价成交价及次日竞价数据必须由可靠数据源补齐。
- 回测接口先做数据格式校验；完整历史回测使用前一版 `overnight_auction.py` CLI，并需要真实竞价字段。
- 不会自动下单，不会连接券商，不保证成交或收益。A股T+1、涨跌停、停牌、竞价排队与滑点风险必须纳入实盘前验证。
- 本项目未内置任何 API Key，也不会收集账户密码。

## 不安装 Android Studio，使用 GitHub 云端生成 APK

项目已附带 `.github/workflows/build-apk.yml` 自动构建配置。无需在本地安装 Android Studio，但需要一个 GitHub 账号：

1. 登录 GitHub，创建一个新的空仓库（建议命名 `QuantHunterAndroid`）。
2. 将本 ZIP 解压后的 `QuantHunterAndroid` 文件夹内所有文件上传到仓库根目录，确保 `.github/workflows/build-apk.yml` 位于仓库对应路径。
3. 上传完成后，打开仓库的 **Actions** 页面，选择 **Build Android APK** 工作流，点击 **Run workflow**（如果 push 到 main，通常也会自动触发）。
4. 等待任务完成，打开成功的运行记录，在页面底部 **Artifacts** 下载 `QuantHunter-debug-apk`。
5. 解压下载的文件，得到 `app-debug.apk`，发送到安卓手机并点击安装。

此方式生成的是用于测试安装的 debug APK，不是应用商店发布用的正式签名包。首次安装可能需要允许浏览器或文件管理器“安装未知应用”。
