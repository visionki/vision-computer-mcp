# Vision Computer MCP

一个面向 **Windows + macOS** 的视觉桌面控制 MCP server，提供类似 OpenAI `computer use` 的闭环：

1. 获取当前桌面截图和状态
2. 执行一批操作动作
3. 返回新的桌面状态和截图
4. 模型继续下一轮决策

这让任意支持"看图 + 工具调用"的模型，都可以通过标准 MCP 协议驱动本机桌面，而不依赖 DOM、Selenium 或人工准备的模板图。

## 背景

视觉自动化的主流路线：

- **DOM / Accessibility**：Playwright、Selenium 等，稳定但依赖目标环境暴露结构化节点
- **图像模板匹配**：SikuliX 等，不依赖 DOM，但需要人工维护模板，面对动态 UI 会变脆

随着多模态模型定位能力的增强，第三条路线成立：**语义视觉定位** —— 模型直接看截图，理解"中间的添加代理按钮""左上角关闭弹窗"，并返回精确坐标或动作。

本项目将这套思路实现为通用 MCP server，不绑定任何特定厂商的内建 tool type。

## 核心设计

### 三个工具，不是一堆原子 RPC

本项目对外只暴露三个工具：

| 工具 | 作用 |
|------|------|
| `computer_list_displays` | 枚举当前可用显示器 |
| `computer_get_state` | 获取截图和桌面状态，返回 `state_id` |
| `computer_act` | 基于某个 `state_id` 执行一批动作，返回新状态和截图 |

底层的 `click`、`drag`、`type` 等被封装进 `computer_act(actions[])` 内部，而不是暴露为独立的分散 tools。这样更容易做日志、错误处理、中断策略，也更适合多轮 agent loop。

### 状态绑定

每次 `computer_get_state` 生成一个新的 `state_id`。`computer_act` 默认只接受最新的 `state_id`，若模型使用旧截图上的坐标操作，直接返回 `rejected`，避免"页面已变，模型还在旧图上操作"的问题。

### 坐标统一原则

- **对模型暴露的永远是截图像素坐标**
- **对系统注入的坐标由 adapter 内部自动换算**

模型不需要关心 HiDPI / Retina / DPI scaling 细节。执行前 server 会将截图像素坐标按比例换算到系统实际执行坐标。

### Human Override

默认开启。当 AI 正在执行动作时，本地用户一旦真实介入键鼠（点击、按键、滚轮、鼠标移动超阈值），当前执行立即中断，返回 `status: interrupted` + `reason: human_override` + 中断现场截图。

## 工具设计

### `computer_list_displays`

返回当前可用显示器列表，字段包含：`id`、`name`、`is_primary`、`width_px`、`height_px`、`logical_width`、`logical_height`、`scale_factor`、原点信息。

### `computer_get_state`

**输入：** `display_id`、`include_cursor`

**输出：** `state_id`、当前显示器信息、光标位置、活跃应用/窗口标题、截图图片

### `computer_act`

**输入：** `state_id`、`display_id`、`actions[]`、`options`

**支持的动作：** `move`、`click`、`double_click`、`right_click`、`drag`、`scroll`、`type`、`keypress`、`wait`

**输出状态：** `ok` / `interrupted` / `rejected` / `error`，并附带新的 `post_state` 和截图。

支持 `post_action_wait_ms` 选项，适合有动画或延迟的场景（弹窗、地址栏建议、打开应用等）。

## 架构

```text
LLM
  ↓ tool call
MCP Host / Client
  ↓
Vision Computer MCP Server
  ├─ Tool Layer
  ├─ State Manager
  ├─ Action Executor
  ├─ Human Override Monitor
  ├─ Windows Adapter
  └─ macOS Adapter
  ↓
Desktop OS
```

**运行循环：**

1. 模型调用 `computer_list_displays`
2. 模型调用 `computer_get_state(display_id)`，获得 `state_id` 和截图
3. 模型看截图，决定下一批 `actions[]`
4. 模型调用 `computer_act(state_id, actions[])`
5. server 执行动作，监听人工介入
6. server 返回 `post_state` + 新截图，模型继续下一轮

## 已知风险

本项目的 MCP 协议与服务端能力已经可以打通“截图 → 动作 → 新截图”的闭环，但在真实 agent 客户端中仍存在若干工程风险：

- **图片 tool result 桥接不一致**：有些客户端会把图片结果字符串化，或只回传 `structuredContent`，导致模型实际看不到图。
- **上下文膨胀 / token 爆炸**：如果客户端把截图 base64 当文本回传，或在多轮对话中不断累积历史截图，可能出现超高 token 使用量，甚至触发请求体过大（如 `413 Request Entity Too Large`）。
- **历史截图管理**：即使图片被正确保留，如果客户端每轮都携带全部历史截图，请求体也会快速增长。实际接入时通常需要“只保留最新截图”或对旧截图做摘要化。
- **动作后界面稳定时间**：弹窗、地址栏建议、打开应用等存在动画和延迟。若动作结束后立即截图，模型可能误判状态。可以使用 `post_action_wait_ms` 让执行层在截图前等待界面稳定。
- **特殊字符输入稳定性**：逐字符 `type` 在浏览器地址栏、命令行、代码编辑器中对 `:`, `/`, `@` 等字符不一定稳定。URL 或高精度文本输入场景更适合未来引入 `paste_text` / `replace_text` 一类动作。

我们已经用原始 OpenAI-compatible `Responses` API 对比验证过：

- 直接用户消息带图片可正常定位
- 模拟 `function_call_output + input_image` 也可正常定位

因此，当前主要不确定性更多来自**客户端桥接实现**，而不是本项目的视觉 MCP 思路本身。

## 设计目标

- Win + macOS 本机桌面控制
- 截图 → 动作 → 新截图的闭环
- 模型自己做视觉理解和坐标决策
- 协议表面小，优先稳定性与可组合性
- 默认支持 human override

## 非目标（v1）

- 视觉模板匹配
- OCR
- DOM / Playwright 自动化
- Linux / Wayland
- 复杂审批 UI
- 内置某家 LLM 的 API client

## 依赖

- `mcp[cli]`
- `pydantic`
- `mss`
- `Pillow`
- `pynput`
- macOS 额外需要：`pyobjc-framework-Quartz`、`pyobjc-framework-AppKit`

## 安装

```bash
pip install -e .
```

或：

```bash
uv sync
```

## 运行

默认 stdio 传输：

```bash
python -m computer_use_mcp
```

streamable-http 传输：

```bash
python -m computer_use_mcp --transport streamable-http --host 127.0.0.1 --port 8765
```

## 平台权限

### macOS

首次运行需在系统设置中允许：
- Accessibility
- Screen Recording

### Windows

普通桌面通常可直接运行；某些高权限窗口或 UAC 场景可能受限。

## 调试

默认开启调试记录，输出到：

- `./.computer_use_mcp_debug/events.jsonl`：每次 get_state / act 的参数、坐标映射、执行结果
- `./.computer_use_mcp_debug/images/`：截图文件

环境变量：

| 变量 | 说明 |
|------|------|
| `COMPUTER_USE_DEBUG=0` | 关闭调试记录 |
| `COMPUTER_USE_DEBUG_DIR=/path/to/dir` | 指定调试目录 |
| `COMPUTER_USE_DEBUG_SAVE_IMAGES=0` | 只记 JSONL，不落截图 |

## 项目结构

```
README.md
pyproject.toml
src/computer_use_mcp/   # MCP server 主体
tests/              # 单元测试
```

## 后续路线

- 更底层的原生输入 / 监听实现
- `computer://capabilities` 等资源
- 配套 system prompt
- OCR 和模板匹配作为辅助能力
- Linux / Wayland 适配

## 参考

- [OpenAI Computer Use](https://platform.openai.com/docs/guides/tools-computer-use)
- [MCP Introduction](https://modelcontextprotocol.io/docs/getting-started/intro)
- [MCP Build Server](https://modelcontextprotocol.io/docs/develop/build-server)
- [MCP Tool Results Spec](https://modelcontextprotocol.io/specification/2025-06-18/server/tools)
