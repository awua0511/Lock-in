# Lock-In Architecture

[English](ARCHITECTURE.en.md) | 简体中文

本文档描述 Lock-In Windows 客户端与浏览器扩展的技术架构。产品功能与用户行为请参阅 [README.md](README.md)。

## 技术目标

- 使用事件驱动方式监听前台内容，避免高频轮询。
- 应用和浏览器监控均不要求管理员权限。
- 所有设置与行为记录默认保存在本地。
- 桌面程序与浏览器扩展使用稳定、可版本化的消息协议。
- 将规则引擎与操作系统接口分离，方便未来迁移到 C++。
- 监控或通信模块异常时，不影响用户正常使用电脑。

## 技术栈

第一版计划使用：

| 模块 | 技术 |
| --- | --- |
| Windows 主程序 | Python 3.12+ |
| 桌面界面 | PySide6 |
| Windows API | pywin32 / ctypes |
| 本地数据库 | SQLite |
| 浏览器扩展 | Manifest V3 + JavaScript/TypeScript |
| 扩展与主程序通信 | Native Messaging |
| Windows 打包 | PyInstaller 或 Nuitka |

如果 Python 版本在启动速度、资源占用、杀毒软件误报或分发稳定性方面遇到问题，可以将桌面常驻部分迁移到 C++/Qt。数据库结构和 Native Messaging 协议应保持兼容。

## 总体架构

```text
┌────────────────────────────────────────┐
│             Windows 主程序             │
│                                        │
│  UI / 计划调度 / 白名单 / 规则引擎      │
│  前台监听 / 计时 / 提醒 / 复盘          │
└───────────────────┬────────────────────┘
                    │ Native Messaging
┌───────────────────▼────────────────────┐
│               浏览器扩展               │
│                                        │
│  标签页激活 / 页面导航 / 域名提取       │
└───────────────────┬────────────────────┘
                    │
┌───────────────────▼────────────────────┐
│             本地 SQLite 数据库          │
│                                        │
│  工作计划 / 白名单 / 提醒事件 / 设置    │
└────────────────────────────────────────┘
```

## 模块划分

建议将 Windows 主程序拆分为以下模块：

```text
lock_in/
├── app/                  应用入口与生命周期
├── ui/                   PySide6窗口、托盘和对话框
├── monitoring/           前台窗口与浏览器状态监听
├── rules/                工作计划和白名单判断
├── sessions/             工作会话及前台计时
├── notifications/        提醒和晚间通知
├── storage/              SQLite仓储与迁移
├── native_messaging/     浏览器扩展通信
└── platform/windows/     Win32 API封装

browser_extension/
├── manifest.json
├── service-worker.js
├── options.html
└── options.js
```

UI 不应直接调用 Win32 API 或执行 SQL。操作系统事件先转换为内部事件，再由规则引擎判断是否需要提醒。

## 前台应用监听

### 事件来源

使用 `SetWinEventHook` 订阅 `EVENT_SYSTEM_FOREGROUND`：

```text
前台窗口变化
      ↓
WinEvent回调收到HWND
      ↓
将事件投递到应用事件队列
      ↓
后台工作线程解析应用身份
      ↓
规则引擎作出判断
```

回调函数中不执行数据库查询或复杂 UI 操作，避免阻塞系统事件线程。注册事件 Hook 的线程必须保持消息循环，并在程序退出时调用 `UnhookWinEvent`。

### 应用身份解析

普通 Win32 应用使用以下流程：

```text
HWND
  ↓ GetWindowThreadProcessId
PID
  ↓ OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION)
进程句柄
  ↓ QueryFullProcessImageNameW
可执行文件路径
  ↓ 路径规范化
ApplicationIdentity
```

内部身份模型示例：

```json
{
  "kind": "win32",
  "displayName": "Visual Studio Code",
  "executablePath": "C:\\Program Files\\Microsoft VS Code\\Code.exe"
}
```

路径比较应：

- 使用绝对规范路径。
- 忽略 Windows 路径大小写。
- 处理符号链接和短路径形式。
- 容忍进程在查询期间已经退出。
- 不因无法识别系统进程而反复提醒。

### Packaged 应用

Microsoft Store、MSIX 和部分 UWP 应用的安装路径可能包含版本号，更新后路径会变化。这类应用应优先保存 Package Family Name：

```json
{
  "kind": "packaged",
  "displayName": "Microsoft To Do",
  "packageFamilyName": "Microsoft.Todos_8wekyb3d8bbwe"
}
```

第一版可以只完整支持 Win32 应用，并将 Packaged 应用支持作为独立迭代。

## 最近使用的应用

前台监听器维护一个去重后的近期应用列表，包括：

- 显示名称。
- 可执行文件路径或包身份。
- 应用图标。
- 最后激活时间。

以下内容不进入最近列表：

- Lock-In 自身。
- 没有有效顶层窗口的后台进程。
- 已知 Windows 系统壳层窗口。
- 无法安全解析身份的临时窗口。

近期列表只保留有限数量，并按最后激活时间排序。

## 浏览器网站识别

Windows 主程序只能确认浏览器进程处于前台，不能可靠获取当前标签页 URL。网站白名单由浏览器扩展实现。

扩展负责监听：

- `tabs.onActivated`：当前标签页切换。
- `tabs.onUpdated`：标签页 URL 更新。
- `webNavigation`：顶层页面导航。
- 浏览器窗口焦点变化。

扩展只发送规范化后的信息：

```json
{
  "event": "active_url_changed",
  "browser": "edge",
  "windowId": 42,
  "tabId": 108,
  "scheme": "https",
  "domain": "youtube.com",
  "timestamp": "2026-09-16T13:08:00-04:00"
}
```

默认不发送：

- URL 查询参数。
- 页面标题。
- URL 片段。
- 页面正文。
- 表单或键盘输入。

第一版优先支持 Chromium 浏览器：

- Google Chrome。
- Microsoft Edge。
- Brave。

## Native Messaging

浏览器扩展与本地程序通过 Native Messaging 通信。消息使用 UTF-8 JSON，并遵循浏览器要求的四字节小端长度前缀。

Native Messaging Host 需要：

- 独立且稳定的应用标识。
- 声明允许连接的扩展 ID。
- 拒绝未知或格式不合法的消息。
- 为消息结构保留协议版本号。
- 限制单条消息长度。

推荐消息包络：

```json
{
  "protocolVersion": 1,
  "event": "active_url_changed",
  "payload": {
    "browser": "edge",
    "domain": "youtube.com"
  },
  "timestamp": "2026-09-16T13:08:00-04:00"
}
```

主程序应将浏览器扩展状态区分为：

- 已连接并有当前标签页数据。
- 浏览器已启动但扩展未连接。
- 扩展已连接但当前页面不可识别。
- 未安装扩展。

未知状态不应被错误判断为非白名单网站。

## 规则引擎

规则引擎接收统一的 `ForegroundContext`：

```json
{
  "application": {
    "kind": "win32",
    "executablePath": "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe"
  },
  "website": {
    "domain": "github.com"
  },
  "observedAt": "2026-09-16T13:08:00-04:00"
}
```

判断顺序：

```text
是否存在生效中的工作计划？
        ↓ 否
不处理
        ↓ 是
当前应用是否属于基础系统白名单？
        ↓ 是
不处理
        ↓ 否
当前应用是否为受支持浏览器？
        ├── 否 → 检查应用白名单
        └── 是 → 检查当前域名和网站白名单
```

域名匹配应使用解析后的 hostname，而不是字符串后缀。例如允许 `example.com` 的子域名时，`docs.example.com` 可以匹配，但 `example.com.evil.test` 不能匹配。

## 提醒状态机

```text
Allowed
  │ 切换到非白名单内容
  ▼
Prompting
  ├── 返回 → Returned → Allowed
  └── 继续 → Continuing
                 │ 达到再次提醒阈值
                 ▼
              Prompting
                 │ 离开目标
                 ▼
               Allowed
```

提醒去重需要考虑：

- Lock-In 提醒窗口成为前台时，不将其视为新的应用切换。
- 同一个前台事件可能被系统重复发送。
- 浏览器可能同时发送标签页激活和页面导航事件。
- 短时间内相同目标只生成一个提醒。
- 用户离开后再次进入，应生成新的提醒。

## 前台时间统计

计时以应用激活和失活事件为边界：

```text
非白名单目标成为前台 → 开始或恢复计时
其他目标成为前台       → 停止本段计时
屏幕锁定或系统休眠     → 停止计时
系统恢复               → 等待新的前台事件
```

使用单调时钟计算持续时间，避免系统时间或时区变化导致错误。墙上时间仅用于事件展示和每日归档。

## 本地数据

推荐的 SQLite 表：

```text
schedules
schedule_recurrences
application_allowlist
website_allowlist
focus_sessions
attention_events
app_settings
schema_migrations
```

### 应用白名单记录

```json
{
  "id": "uuid",
  "kind": "win32",
  "displayName": "Visual Studio Code",
  "executablePath": "C:\\Program Files\\Microsoft VS Code\\Code.exe",
  "packageFamilyName": null,
  "enabled": true
}
```

### 网站白名单记录

```json
{
  "id": "uuid",
  "domain": "github.com",
  "includeSubdomains": true,
  "enabled": true
}
```

### 提醒事件

```json
{
  "id": "uuid",
  "focusSessionId": "uuid",
  "occurredAt": "2026-09-16T13:08:00-04:00",
  "targetType": "website",
  "targetKey": "youtube.com",
  "decision": "continue",
  "foregroundSeconds": 300
}
```

数据库变更必须通过版本化迁移完成。删除历史记录时，应保留用户当前设置和白名单。

## 线程模型

建议使用：

- UI 主线程：PySide6 事件循环和窗口渲染。
- WinEvent 线程：注册 Hook 并运行 Windows 消息循环。
- Native Messaging 线程或子进程：处理浏览器标准输入输出。
- 数据访问层：短事务写入 SQLite，并序列化写操作。

所有跨线程事件都投递到统一队列，再转发至 UI 或规则引擎。不得从 WinEvent 回调直接操作 PySide6 控件。

## 本地通知

晚间复盘由本地计划任务触发。通知内容从当天已经聚合的数据生成，不依赖网络服务。

系统休眠导致错过通知时间时，可以在恢复后检查：

- 当天复盘尚未发送。
- 当前时间仍在允许补发的时间窗口内。

满足条件时补发一次，避免重复通知。

## 隐私与安全

- 默认不建立用户账号。
- 默认不发送遥测或使用记录。
- 不读取页面正文和用户输入。
- 不保存完整 URL。
- Native Messaging Host 只接受已声明扩展的连接。
- 日志中不写入敏感 URL、命令行参数或窗口正文。
- 数据库和日志均存放在当前用户的应用数据目录。
- 用户清除数据时同时删除数据库中的行为记录和应用日志。

## 错误处理

以下错误不应阻止用户使用电脑：

- 无法读取前台进程路径。
- 目标进程在识别期间退出。
- 浏览器扩展断开连接。
- 数据库暂时不可写。
- 提醒窗口显示失败。
- Windows 通知不可用。

默认策略是记录可诊断但不包含敏感数据的错误，然后跳过本次提醒。产品不采用“无法判断即拦截”的方式。

## 打包与分发

个人测试可以直接从源码运行。正式构建可以使用 PyInstaller 或 Nuitka 打包，并包含：

- Windows 主程序。
- Native Messaging Host 注册配置。
- SQLite 初始化与迁移文件。
- 浏览器扩展安装说明。

公开发布前需要评估：

- Windows 代码签名。
- SmartScreen 对未签名安装包的提示。
- 自动更新机制。
- Chrome Web Store 和 Microsoft Edge Add-ons 的扩展发布流程。
- 安装和卸载时对 Native Messaging 注册信息的清理。

## 测试重点

- 多显示器和不同 DPI 缩放。
- 多个工作计划重叠。
- 跨午夜工作计划。
- 系统休眠、唤醒和锁屏。
- 系统时间和时区变化。
- 应用启动器与真实前台进程不同。
- 应用更新后可执行文件路径变化。
- Chrome、Edge 和 Brave 多窗口场景。
- 浏览器无痕窗口和内部页面。
- 扩展未安装、被禁用或连接中断。
- 提醒窗口自身触发前台事件。
- 程序异常退出后的会话恢复。

## 实施顺序

### 阶段一：应用白名单原型

- [ ] 创建系统托盘应用。
- [ ] 创建工作时间段。
- [ ] 监听前台窗口变化。
- [ ] 获取前台应用身份。
- [ ] 从最近使用的应用中添加白名单。
- [ ] 对非白名单应用显示提醒。
- [ ] 记录返回和继续选择。

### 阶段二：计时与复盘

- [ ] 统计应用前台使用时间。
- [ ] 实现持续使用再次提醒。
- [ ] 保存每日行为记录。
- [ ] 生成晚间复盘。
- [ ] 发送 Windows 本地通知。

### 阶段三：网站白名单

- [ ] 创建 Manifest V3 浏览器扩展。
- [ ] 监听标签页和域名变化。
- [ ] 建立 Native Messaging 通信。
- [ ] 实现网站白名单规则。
- [ ] 统计非白名单网站前台时间。

### 阶段四：打包与测试

- [ ] 打包 Windows 可执行程序。
- [ ] 测试不同 Windows 版本和显示配置。
- [ ] 测试 Chrome、Edge 和 Brave。
- [ ] 完成数据迁移与异常恢复测试。
- [ ] 评估代码签名和公开分发方案。
