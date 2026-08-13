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

插件自动通过 `POST /login` 获取 JWT Token，无需手动维护 Token。Token 在插件进程内按凭据缓存，
到期前 60 秒才会重新登录；若服务端提前拒绝（返回 401），插件会自动重新登录并重试一次该请求。

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

### 查询威胁情报

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `feed` | string | ❌ | 数据源（Feed ID）过滤，多个用英文逗号分隔 |
| `tag` | string | ❌ | 标签过滤，多个用英文逗号分隔，命中任意一个即返回 |
| `days` | number | ❌ | 只返回最近 N 天更新过（`last_seen`）的情报；设置了 `start_time` 时忽略 |
| `start_time` | string | ❌ | 更新时间下界，ISO 8601（如 `2026-07-01T00:00:00Z`） |
| `end_time` | string | ❌ | 更新时间上界，ISO 8601 |
| `page` | number | ❌ | 页码，从 1 开始，默认 1 |
| `limit` | number | ❌ | 每页数量，默认 50，服务端上限 500 |

对应接口 `GET /intel/indicators`。返回：情报指标列表（`type` / `value` / `tlp` / `confidence` / `tags` / `actor` / `malware` / `sources` / `first_seen` / `last_seen` / `expires`）和总数；第一页额外返回 `stats` 分面统计，其中 `stats.feeds` 和 `stats.tags` 可用于发现可选的数据源和标签取值。

### 添加威胁情报

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `value` | string | ✅ | 情报值，一行一条或英文逗号分隔的多条；支持 defang 形式（`evil[.]com`、`hxxp://`） |
| `source` | string | ✅ | 数据源，同时作为 Feed ID，不能含英文逗号 |
| `type` | select | ❌ | `ipv4` / `domain` / `url` / `sha256` / `md5` / `email`，留空自动识别 |
| `tags` | string | ❌ | 标签，英文逗号分隔，最多 20 个，统一小写 |
| `confidence` | number | ❌ | 置信度 0-100，默认 50（≥75 为高置信度） |
| `tlp` | select | ❌ | `CLEAR` / `GREEN` / `AMBER`（默认）/ `AMBER_STRICT` / `RED` |
| `actor` | string | ❌ | 威胁组织 / APT 团伙 |
| `malware` | string | ❌ | 恶意软件家族 |
| `phase` | select | ❌ | 攻击链阶段：`Reconnaissance` / `Initial Access` / `Execution` / `Persistence` / `C2` / `Exfiltration` / `Impact` |
| `expire_days` | number | ❌ | 有效期天数，默认取平台配置（90 天） |
| `ref_url` | string | ❌ | 参考链接 |
| `evidence` | string | ❌ | 佐证信息 |
| `note` | string | ❌ | 备注 |

对应接口 `POST /intel/indicators`。多个 `value` 共用同一组属性，一次批量提交。相同值在**不同**数据源下会合并进同一条情报（`sources` 数组各存一份），在**相同**数据源下则覆盖该源的上次上报。返回 `created` / `merged` / `skipped` 计数。

### 异步威胁狩猎结果回调

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `status` | select | ✅ | `ok`（执行完成，含「没有命中」）/ `failed`（执行失败） |
| `hunt_id` | string | ✅ | 狩猎计划 ID |
| `run_id` | string | ✅ | 本次执行 ID |
| `task_id` | string | ✅ | 本次执行中该任务的 ID（UUID 字符串） |
| `rows` | string | ❌ | 命中记录，JSON 数组，每个元素为 JSON 对象；服务端最多保留 100 条样本 |

对应接口 `PUT /hunting/hunts/<hunt_id>/runs/<run_id>/tasks/<task_id>/result`，回调地址由工具用三个 ID
拼接，请求发往凭据里配置的 API 地址，与其他工具一样走登录后的 JWT 认证，无需额外凭据。命中总数由服务端
按回传的 `rows` 条数统计。

用法：狩猎计划下发到 Dify 工作流时，输入里带有 `hunt_id` / `run_id` / `task_id`；
工作流若先以 `async=true` 返回，该任务会一直停在「运行中」，直到本工具把结果回传。所有任务都回传后，
本次狩猎执行才会结束并按计划进入研判。每个任务只接受一次回调：重复回调或执行已结束会返回 409。

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
