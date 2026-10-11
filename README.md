# MaiBot 高德天气预报与定时播报插件 (weather-forecast)

基于高德开放平台 Web 服务 API 构建的高精度天气预报插件。支持全天候实时天气查询、未来多日天气走势预测，以及多群聊、多时段自定义定时早晚播报。

## 核心功能

- 实时与多日天气：支持精确到区县级的实时天气、气温、风向风力及空气质量查询。
- 极速命令交互：支持 `/天气 [地点]` 或 `/weather [地点]` 快速触发。
- 双时段定时播报：已深度优化原生单点调度逻辑，完美支持如 `06:00,22:20` 的早晚双时段独立广播。
- 大模型自然语言融合：支持大模型调用天气工具，以拟人化口吻向群友送出贴心保暖/防雨提醒。

## 配置指南

```toml
[plugin]
enabled = true
amap_key = "YOUR_AMAP_KEY_HERE"  # 请替换为高德开放平台 Web 服务 API Key

[broadcast]
broadcast_enabled = true
broadcast_time = "06:00,22:20"    # 支持逗号分隔的双时段定时播报
target_groups = [
    "935350234 福清",
    "974533432 福清"
]

[tool]
enabled = true
default_days = 3
```

## 开源协议

本项目采用 MIT 许可证开源，详情请参阅 [LICENSE](LICENSE)。
