# 双鱼座 (Pisces) Dify 插件

双鱼座安全事件响应平台的 Dify 工具插件，提供两个工具：

- **查询 IOC 清单** — 列出指定安全事件下的 IOC（失陷指标）记录
- **添加 IOC** — 向指定安全事件中新增 IOC 记录

## 安装

在 Dify 插件管理页面上传 `.difypkg` 包，或通过本地调试模式运行。

## 凭据配置

插件安装后，进入「插件 → 双鱼座 → 授权」填写：

| 字段 | 说明 | 示例 |
|------|------|------|
| API 地址 (`base_url`) | 双鱼座 API 服务的根地址，**末尾不加斜杠** | `http://192.168.1.125:8080` |
| JWT 令牌 (`api_token`) | 登录双鱼座后端获取的 Bearer Token，有效期 8 小时 | `eyJhbGciOiJIUzI1NiIs...` |

> **获取 JWT Token**：调用后端登录接口 `POST /auth/login`（参考后端文档），响应中的 `access_token` 字段即为所需令牌。

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
