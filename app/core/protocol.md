# 协议说明

协议采用 JSON 封包（基于 WebSocket 传输），每个消息为一个 JSON 对象，顶层字段如下：

- `version` (int)：协议版本，目前为 `1`。
- `type` (string)：消息类型，枚举值：`handshake`、`handshake_ack`、`command`、`response`、`heartbeat`、`error`。
- `id` (string)：消息 ID（可选，对应请求/响应匹配）。
- `payload` (object)：消息负载，格式随 `type` 变化。

示例 — 客户端握手：

```json
{
  "version": 1,
  "type": "handshake",
  "id": "<uuid>",
  "payload": {
    "client_id": "hostname-or-uuid",
    "capabilities": ["screen","input"],
    "token": "secret-token-123"
  }
}
```

示例 — 服务端握手确认：

```json
{
  "version": 1,
  "type": "handshake_ack",
  "id": "<same-uuid>",
  "payload": { "accepted": true, "server_version": 1 }
}
```

示例 — 命令请求：

```json
{
  "version": 1,
  "type": "command",
  "id": "<uuid>",
  "payload": { "command_type": "echo", "args": {...} }
}
```

示例 — 屏幕截图请求：

```json
{
  "version": 1,
  "type": "command",
  "id": "<uuid>",
  "payload": { "command_type": "screen_capture", "args": {} }
}
```

示例 — 屏幕截图响应（带尺寸）：

```json
{
  "version": 1,
  "type": "response",
  "id": "<same-uuid>",
  "payload": {
    "status": "ok",
    "result": {
      "image": "<base64-jpeg>",
      "width": 1920,
      "height": 1080
    }
  }
}
```

示例 — 鼠标点击请求：

```json
{
  "version": 1,
  "type": "command",
  "id": "<uuid>",
  "payload": { "command_type": "mouse_click", "args": { "button": "left" } }
}
```

示例 — 键盘输入请求：

```json
{
  "version": 1,
  "type": "command",
  "id": "<uuid>",
  "payload": { "command_type": "key_write", "args": { "text": "hello" } }
}
```

示例 — 响应：

```json
{
  "version": 1,
  "type": "response",
  "id": "<same-uuid>",
  "payload": { "status": "ok", "result": {...} }
}
```

心跳：客户端或服务端可发送 `heartbeat`，对方应返回 `heartbeat` 或 `response`，以保持连接活性。

错误：当解析失败或版本不匹配时，发送 `error`，并在必要时关闭连接。

安全说明：目前为明文协议，生产环境必须通过 TLS（wss://）或在应用层加密消息。
