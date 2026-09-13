# lianzz-downloader(v1.0.0)

Warning:本仓库中的代码是v1.1.0版本的，一些功能可能与此readme文件描述的不符，请以英文版readme文件内容为准。

通过 HTTP Range 实现的 Python 多线程分段下载器。一个文件被切成 N 段，每段由独立线程并发拉取，最后就地写入同一文件 —— 这是 IDM、aria2、axel 的核心思路。

实测在本地服务器（每连接限速 2 MB/s）下，下载 80 MB 文件：

| 线程数 | 耗时 | 均速   | 加速比   |
| ------ | ---- | ------ | -------- |
| 1      | 41s  | 1.93 MB/s | 1.00x |
| 8      | 5.3s | 15.2 MB/s | **7.85x** |
| 16     | 2.8s | 28.3 MB/s | **14.6x** |

> 1 线程和 8 线程下载的同一文件 SHA-1 完全一致，验证分片写入正确无损坏。

## 功能

- ✅ HTTP Range 多线程分段下载
- ✅ HEAD 探测 + Range GET 探测双路径
- ✅ 失败自动重试（指数退避，最多 5 次）
- ✅ 全局令牌桶限速
- ✅ 暂停 / 恢复 / 取消
- ✅ 不支持 Range 时自动降级为单线程流式下载
- ✅ 实时进度回调（速度、ETA、活跃线程数）
- ✅ 命令行 + Tkinter 简洁 GUI
- ✅ 临时文件预分配，避免磁盘碎片

## 安装

从 PyPI 安装（推荐）：

```bash
pip install lianzz-downloader
```

从源码安装：

```bash
git clone https://github.com/lianzhongzhe/lianzz-downloader
cd lianzz-downloader
pip install .
```

依赖只有 `requests`。

## 用法

### 命令行

```bash
# 基本
lianzz-downloader https://nodejs.org/dist/v20.10.0/node-v20.10.0-win-x64.zip

# 或
python -m lianzz_downloader https://nodejs.org/dist/v20.10.0/node-v20.10.0-win-x64.zip

# 指定参数
lianzz-downloader <URL> -o my.zip -n 16 --speed 2048 --header "Authorization: Bearer xxx"
```

参数：

| 参数 | 说明 | 默认 |
| ---- | ---- | ---- |
| `url` | 下载链接（位置参数） | — |
| `-o / --output` | 保存路径 | URL 末段 |
| `-n / --threads` | 线程数 1-32 | 8 |
| `--chunk` | 单次读取字节数 | 64 KB |
| `--speed` | 限速（字节/秒），0 = 不限 | 0 |
| `--retries` | 单分片重试次数 | 5 |
| `--no-resume` | 禁用断点续传 | — |
| `--header` | 自定义请求头（可多次） | — |
| `-v` | 调试日志 | — |

### 图形界面

```bash
lianzz-downloader-gui
```

或：

```bash
python -m lianzz_downloader.gui
```

简洁的 Tkinter 界面：URL、保存路径、线程数、限速、进度条、暂停 / 取消。

### 作为库使用

```python
from lianzz_downloader.core import SegmentedDownloader, DownloadConfig

def on_progress(p):
    print(f"{p.percent:5.1f}%  {p.format_speed()}  ETA {p.format_eta()}")

cfg = DownloadConfig(
    url="https://example.com/big.zip",
    output_path="big.zip",
    threads=8,
    speed_limit=0,            # 0 = 不限速
    headers={"Referer": "..."},
)

dl = SegmentedDownloader(cfg, on_progress)
# dl.pause() / dl.resume() / dl.cancel()  随时控制
path = dl.run()
```

## 运行测试

```bash
# 1) 启动本地测试服务器（每连接限速 2MB/s，生成 80MB 文件）
python examples/test_server.py 18080 2048 80

# 2) 另开终端跑对比测试
python examples/benchmark_local.py

# 3) 功能测试（暂停/恢复/限速）
python examples/test_features.py
```

## 实现要点

- **HTTP Range 请求**：每个分片发独立 `Range: bytes=A-B` 请求，写入同一 `.part` 文件的对应偏移
- **线程池**：`concurrent.futures.ThreadPoolExecutor`，每分片一个 worker
- **预分配**：`os.posix_fallocate` 占用整块空间，下载时直接 `seek+write`，避免磁盘碎片
- **断点续传**：每个分片维护 `downloaded` 偏移；网络断开后，从中断偏移续传
- **HEAD 探测**：先 HEAD 拿 Content-Length 与 Accept-Ranges；若 HEAD 被拦截则用 `Range: bytes=0-0` 做 GET 探测
- **降级路径**：服务器忽略 Range 时（返回 200）自动改用 `iter_content` 流式下载
- **限速**：令牌桶算法，4 线程共享 1 个桶时，总速率精确等于设定值
- **进度上报**：所有分片共享一个 `_downloaded_total`（Lock 保护），主线程每 250 ms 采样计算瞬时速度与 ETA

## 目录结构

```
lianzz-downloader/
├── lianzz_downloader/
│   ├── __init__.py
│   ├── __main__.py     # python -m lianzz_downloader 入口
│   ├── core.py         # 分段下载核心引擎
│   ├── cli.py          # argparse CLI
│   └── gui.py          # Tkinter GUI
├── examples/
│   ├── test_server.py     # 本地测试 HTTP 服务器
│   ├── benchmark.py       # 外部源对比
│   ├── benchmark_local.py # 本地源对比
│   └── test_features.py   # 暂停/限速/线程数功能测试
├── LICENSE
├── pyproject.toml
└── README.md
```

## License

MIT
