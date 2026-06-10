# 双鱼座 (Pisces) Dify 插件

双鱼座安全事件响应平台的 Dify 工具插件，提供四个工具：

- **查询 IOC 清单** — 列出指定安全事件下的 IOC（失陷指标）记录
- **添加 IOC** — 向指定安全事件中新增 IOC 记录
- **创建深度溯源任务** — 创建 DeepTrace 溯源会话并启动分析任务，返回 session_id
- **获取深度溯源任务流** — 消费 DeepTrace 会话的 SSE 事件流，返回累积分析结果

## 安装

在 Dify 插件管理页面上传 `.difypkg` 包，或通过本地调试模式运行。

## 凭据配置

插件安装后，进入「插件 → 双鱼座 → 授权」填写：

| 字段 | 说明 | 示例 |
|------|------|------|
| API 地址 (`base_url`) | 双鱼座 API 服务的根地址，**末尾不加斜杠** | `http://192.168.1.125:8080` |
| 用户名 (`username`) | 双鱼座平台的登录用户名 | `admin` |
| 密码 (`password`) | 双鱼座平台的登录密码 | `********` |

插件每次请求时自动通过 `POST /login` 获取 JWT Token，无需手动维护 Token。

## 工具说明

### 查询 IOC 清单

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `incident_id` | string | ✅ | 安全事件 ID |
| `object_type` | select | ❌ | 类型过滤：`attack_source`（攻击源）/ `compromised_asset`（受害资产） |
| `status` | select | ❌ | 状态过滤：`待确认` / `攻击者` / `非攻击者` / `受害者` / `非受害者` |
| `limit` | number | ❌ | 每页数量，默认 50 |
| `offset` | number | ❌ | 分页偏移，默认 0 |

返回：分组后的 IOC 列表（按 `object_name` + `object_type` 聚合）和总数。

### 添加 IOC

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `incident_id` | string | ✅ | 安全事件 ID |
| `object_name` | string | ✅ | IOC 值（如 IP、域名、用户名） |
| `object_type` | select | ✅ | `attack_source` / `compromised_asset` |
| `object_subtype` | select | ✅ | `ip` / `hostname` / `hostip` / `domainname` / `domainid` / `username` / `userid` |
| `object_label` | string | ❌ | 简短标签 |
| `object_detail` | string | ❌ | 详细描述 |
| `source` | select | ❌ | 来源：`人工`（默认）/ `告警` / `回溯` |
| `handle_status` | select | ❌ | 处置状态：`未处置`（默认）/ `警告` / `WAF拦截` / `CBC冻结` / `已取证` |
| `status` | select | ❌ | 确认状态：`待确认`（默认）/ `攻击者` / `非攻击者` / `受害者` / `非受害者` |
| `alert_id` | string | ❌ | 关联告警 ID（省略则自动取事件第一个告警） |

### 创建深度溯源任务

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `question` | string | ✅ | 发送给溯源 Agent 的分析问题 |
| `title` | string | ❌ | 会话标题，默认取 question 前 100 字符 |
| `model` | string | ❌ | 覆盖 LLM 模型（如 `gpt-4o`），留空用服务端默认 |

返回：`session_id`，可用于后续通过「获取深度溯源任务流」消费结果。

### 获取深度溯源任务流

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `session_id` | string | ✅ | 由创建深度溯源任务返回的 session_id |
| `timeout` | number | ❌ | 最大监听秒数，默认 120，超时后返回已收集结果 |

返回：累积的文本输出和事件列表。

## 本地调试

```bash
cd pisces-dify-plugin
cp .env.example .env
# 编辑 .env 填入 Dify 实例的调试 key
pip install -r requirements.txt
python main.py
```

## 打包

```bash
dify plugin package ./pisces-dify-plugin
```

生成 `pisces.difypkg` 后上传至 Dify。
