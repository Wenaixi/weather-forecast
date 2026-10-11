# 天气预报（whitefox.weather-forecast）

## 官方上游与版本溯源
- 官方仓库（Upstream Repository）：https://github.com/whitefox20011120/weather-forecast
- 官方作者（Author / Maintainer）：whitefox20011120
- 功能定位：高德天气预报与定时播报插件
- 本地演进定位：基于官方上游最新版本，融入本地生产环境兼容性定制与稳定性加固。
- 本地专属定制：本地配置福清地区专属播报，小改调度算法支持双时段（06:00, 22:20）播报。


源: whitefox  
插件 ID: `whitefox.weather-forecast` v2.0.1

## 主人改过的关键文件

- `config.toml`：
  - `[plugin] enabled = true`
  - `[amap] amap_key = "9cd26dd4…"`（高德 **Web 服务** `restapi.amap.com`；前一把非 Web 服务已弃用）
- `_manifest.json`：`max_version` 改成 `1.99.99`（修 Host 1.1 不兼容）。
- `plugin.py`：调度器加逗号分隔双时段支持（原生仅单点）。
- 数据返回：`get_region_summary` 固定 `casts[0]`（当天）。

## 配置要点

- 主人指定播报：`target_groups = ["935350234 福清", "974533432 福清"]`；`broadcast_enabled = true`、`broadcast_time = "06:00,22:20"`（逗号分隔双时段）。
- `[tool] enabled = true`、`default_days = 3` —— LLM 工具。

## 接入 & 依赖

- 走 `restapi.amap.com` Web 服务 API。`adcode=350181`（福清）冒烟通过。

## 关键日志

- `天气预报插件已启动`
- 启动时注册：`下次天气播报: 2026-07-26 22:20`

## 用法

- `/天气 福清` 或 `/weather 地点`（**命令必须带地点**，插件无全局 `default_city` 字段）。
- 群定时播报到目标群。

## 历史脚本

本机脚本（`legacy-0x-backup/from-server/`）：

- `patch_weather_amap.py`
- `patch_weather_key2.py`
- `patch_weather_fuqing_schedule.py`
- `patch_weather_dual_time.py`
- `revert_weather_tomorrow.py`
- `smoke_amap_weather.py`

## 历史脚注

- 2026-07-28: 从服务器同步到本地仓库（baseline head=`3f53745`）；补充 `.gitignore` 主人段与本 CLAUDE.md。
