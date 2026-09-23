# Xiaomi Pictorial

批量下载 **小米画报（Mi Wallpaper Carousel）早安画报历史内容** 的 Windows / Python 工具。

当前实现基于小米画报 **25200033-CAROUSEL**（包名 `com.mfashiongallery.emag`）中的早安画报历史请求逻辑。

## 当前功能

- 现代扁平 GUI（ttkbootstrap，缺失时自动回退系统 ttk）
- Windows EXE / Python CLI
- 按日期范围扫描历史早安画报并自动向前翻页
- 图片质量策略：`best / 2160 / 1440 / 1080`
- 优先尝试 `url_full`、`url_h`，再尝试 `url_root + locator` 的 2160/1440/1080 CDN 地址
- 图片命名：`date`、`title`、`date_title`
- 按 年/月 整理
- 保存 TXT 文案与 JSON 元数据
- 已下载自动跳过、网络失败自动重试
- 可保存接口原始 JSON
- GitHub Actions 自动测试并生成 Windows EXE
- 自带扁平风图片图标

> “2160 优先”表示程序会尝试构造并请求对应宽度地址；最终能否获得高于 1080×1920 的源图取决于小米 CDN 对该素材是否实际提供更高分辨率。程序不会把 1080 图片人工放大冒充原图。

## 接口

历史接口：

```text
https://w.pandora.xiaomi.com/api/a1/gallery/gallery_morning_history
```

主要参数：

```text
time_offset
start_time
delta
page_size
```

首次 `start_time=0`，之后使用当前最早 `morning_date` 当天 00:00 的 Unix 秒级时间戳继续向前加载。

## Windows EXE

GitHub Actions 的 **Build Windows EXE** 工作流会生成：

```text
Xiaomi-Pictorial-Windows
└─ Xiaomi-Pictorial.exe
```

## Python

```bash
pip install -r requirements.txt
python xiaomi_pictorial.py
```

不带参数默认打开 GUI。

CLI 示例：

```bash
python xiaomi_pictorial.py \
  --start 2026-01-01 \
  --end 2026-09-23 \
  --quality best \
  --name-format date_title \
  --output downloads
```

命名格式：

```text
date        -> 2026-09-23.jpg
title       -> 早安世界.jpg
date_title  -> 2026-09-23 早安世界.jpg
```

## 注意

这是非官方工具。小米画报接口、历史数据保留时间和 CDN 分辨率可能随时调整，请控制请求频率，仅用于个人备份和研究。


## 配置持久化

Windows GUI 会在程序目录保存 `xiaomi-pictorial.json`。除稳定的 `device_id` 外，v0.2.1 起还会保存并自动恢复：

- 开始/结束日期
- 保存目录
- 图片质量
- 图片命名格式
- 按年/月整理
- 保存 TXT
- 保存 JSON
- 跳过已下载
- 保存接口原始 JSON
- 窗口大小

## 关于手机保存出的 1200×2608

APK 中 `MorningImageUrl.getHdUrl()` 会按设备屏幕宽度请求 CDN 图片；今天的服务端素材实测仍返回 1080×1920。
但小米画报自己的 `SaveImageTask` 还会调用 `useScreenRatioSaveImgToExternalFolder()`，读取屏幕宽高、创建全屏 RelativeLayout/ImageView（CENTER_CROP）后再保存。
因此手机看到的 1200×2608 是按手机屏幕比例重新生成的保存图，不等同于服务器存在 1200×2608 原始素材。
