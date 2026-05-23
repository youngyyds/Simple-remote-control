Simple Remote Control

Windows-like 远程控制软件（原型）。

结构：
- `app/core`：核心协议与命令处理
- `app/network`：网络客户端/服务端
- `app/ui`：PyQt GUI 客户端
- `app/utils`：工具与安全相关

快速开始：

1. 创建虚拟环境并安装依赖：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

2. 运行示例服务器：

```powershell
python main.py server
```

3. 运行客户端 GUI：

```powershell
python main.py client
```

接下来：实现协议细化、屏幕流传输、输入注入、认证与加密等。
