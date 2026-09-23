# Xiaomi Pictorial

批量下载 **小米画报（Mi Wallpaper Carousel）早安画报历史内容** 的 Windows / Python 工具。

当前实现基于小米画报 **25200033-CAROUSEL**（包名 \`com.mfashiongallery.emag\`）中的早安画报历史请求逻辑。

## 功能

- 图形界面（Windows EXE / Python Tkinter）
- 命令行批量下载
- 按日期范围扫描历史早安画报
- 自动向前翻页获取更早内容
- 优先保存客户端使用的高清图片地址
- 保存标题、文案和原始元数据
- 默认按 \`年/月\` 目录整理
- 已下载日期自动跳过
- HTTP 失败自动重试
- 可保存接口原始 JSON，方便接口变化时排查
- GitHub Actions 自动测试并生成 Windows EXE

## 接口来源

25200033-CAROUSEL APK 中可确认早安模块包含：

- \`MorningGreetDetailRemoteFetcher\`
- \`MorningGreetDetailInitialLoadTask\`
- \`MorningGreetDetailLoadMoreTask\`
- \`MorningHistoryClickAction\`
- \`morning_date\`
- \`url_h\`

历史接口：

\`\`\`text
https://w.pandora.xiaomi.com/api/a1/gallery/gallery_morning_history
\`\`\`

主要分页参数：

\`\`\`text
time_offset
start_time
delta
page_size
\`\`\`

本项目默认采用 APK 中对应的分页方向：首次 \`start_time=0\`，之后使用当前最早 \`morning_date\` 当天 00:00 的 Unix 秒级时间戳继续向前加载。

> 服务端实际保留多长时间的历史数据由小米决定，本项目只能下载接口当前仍可返回的内容。

## Windows EXE

每次 PR / push 后，GitHub Actions 会生成：

\`\`\`text
Xiaomi-Pictorial-Windows
└─ Xiaomi-Pictorial.exe
\`\`\`

在仓库 **Actions → Build Windows EXE** 对应运行记录的 Artifacts 中下载即可。

运行 EXE 后直接填写：

- 开始日期：可留空，表示尽量向前扫描
- 结束日期：默认今天
- 保存目录
- 回退图片宽度：1080 / 1440 / 2160

然后点击 **开始下载**。

## Python 运行

要求 Python 3.11+。

\`\`\`bash
pip install -r requirements.txt
python xiaomi_pictorial.py
\`\`\`

不带参数时默认打开 GUI。

## CLI 示例

下载 2024 年全部可获取早安画报：

\`\`\`bash
python xiaomi_pictorial.py \
  --start 2024-01-01 \
  --end 2024-12-31 \
  --output downloads
\`\`\`

先只扫描前 2 页，不下载图片：

\`\`\`bash
python xiaomi_pictorial.py \
  --dry-run \
  --max-pages 2
\`\`\`

保存接口原始返回，方便排查：

\`\`\`bash
python xiaomi_pictorial.py \
  --debug-json \
  --max-pages 1
\`\`\`

常用参数：

\`\`\`text
--start YYYY-MM-DD
--end YYYY-MM-DD
-o / --output DIR
--width 1080|1440|2160
--page-size 30
--delta 6
--max-pages N
--flat
--no-text
--no-json
--overwrite
--dry-run
--debug-json
--time-offset SECONDS
--gui
\`\`\`

## 保存结构

默认：

\`\`\`text
downloads/
└─ 2026/
   └─ 09/
      ├─ 2026-09-23.jpg
      ├─ 2026-09-23.txt
      └─ 2026-09-23.json
\`\`\`

图片实际后缀根据服务器返回的 Content-Type 保存，可能是 \`.jpg\`、\`.webp\`、\`.png\` 或 \`.avif\`。

TXT 内容包含日期、标题、文案、图片 URL 与项目 ID。

JSON 会保留解析后的字段以及该条接口原始数据。

## time_offset

默认使用运行电脑当前时区的 UTC 偏移秒数。

例如中国标准时间通常为：

\`\`\`text
28800
\`\`\`

如果接口行为发生变化，可手动覆盖：

\`\`\`bash
python xiaomi_pictorial.py --time-offset 28800 --debug-json --max-pages 1
\`\`\`

## 本地配置

程序会在程序所在目录生成：

\`\`\`text
xiaomi-pictorial.json
\`\`\`

其中保存一个随机生成的持久 \`device_id\`，用于模拟客户端稳定安装 ID。不会读取小米账号，也不需要登录。

## 注意

这是非官方工具，小米画报接口可能随时调整、限制访问或停止提供旧数据。请控制请求频率，仅用于个人备份和研究。
