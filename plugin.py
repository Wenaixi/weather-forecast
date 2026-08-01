"""
天气预报插件
定时获取指定地区天气并推送到群聊，支持 /天气 和 /weather 手动查询。
"""

import asyncio
import datetime
import re
from typing import Any, ClassVar

from maibot_sdk import Command, Field, MaiBotPlugin, PluginConfigBase, Tool
from maibot_sdk.types import ToolParameterInfo, ToolParamType

from .weather_service import WeatherService


class PluginSectionConfig(PluginConfigBase):
    """插件基础配置。"""

    __ui_label__: ClassVar[str] = "插件开关"
    __ui_order__: ClassVar[int] = 0

    enabled: bool = Field(
        default=True,
        description="是否启用本插件。",
        json_schema_extra={"hint": "插件总开关。", "label": "启用插件", "order": 0},
    )
    config_version: str = Field(
        default="2.0.0",
        json_schema_extra={"disabled": True, "hidden": True, "label": "配置版本", "order": 99},
    )


class WeatherConfig(PluginConfigBase):
    """天气 API 配置。"""

    __ui_label__: ClassVar[str] = "天气 API"
    __ui_order__: ClassVar[int] = 1

    amap_key: str = Field(
        default="your_amap_key_here",
        description="高德地图 Web服务 API 密钥。",
        json_schema_extra={
            "hint": "申请地址：https://console.amap.com/dev/key/app",
            "label": "高德地图 API Key（必填）",
            "placeholder": "在此填入您的 Key",
            "order": 0,
            "required": True,
        },
    )


class GroupsConfig(PluginConfigBase):
    """群聊推送配置。"""

    __ui_label__: ClassVar[str] = "群聊推送"
    __ui_order__: ClassVar[int] = 2

    target_groups: list[str] = Field(
        default_factory=list,
        description='每行一组，格式："群号 地点名称"。',
        json_schema_extra={
            "hint": (
                "每行一组群聊推送配置。\n"
                "格式：群号 地点名称\n"
                "示例：123456789 河北省\n"
                "地点支持省、市、区级别"
            ),
            "label": "群聊推送列表",
            "placeholder": "123456789 河北省",
            "order": 0,
        },
    )


class ScheduleConfig(PluginConfigBase):
    """定时任务配置。"""

    __ui_label__: ClassVar[str] = "定时任务"
    __ui_order__: ClassVar[int] = 3

    broadcast_enabled: bool = Field(
        default=True,
        description="是否启用定时推送。",
        json_schema_extra={
            "hint": "关闭后手动指令和 LLM 工具仍可正常使用。",
            "label": "启用定时推送",
            "order": 0,
        },
    )
    broadcast_time: str = Field(
        default="08:00",
        description="每日播报时间，可填多个，用逗号分隔。",
        json_schema_extra={
            "hint": "格式 HH:MM，24小时制；多个时间用逗号分隔，如 06:00,22:20。",
            "label": "播报时间",
            "placeholder": "06:00,22:20",
            "order": 1,
        },
    )


class BroadcastConfig(PluginConfigBase):
    """播报内容配置。"""

    __ui_label__: ClassVar[str] = "播报"
    __ui_order__: ClassVar[int] = 4

    max_length: int = Field(
        default=200,
        description="播报内容最大字数。",
        json_schema_extra={
            "hint": "LLM 生成的播报文本将被截断到该长度。",
            "label": "最大字数",
            "order": 0,
            "step": 50,
        },
    )
    model_name: str = Field(
        default="replyer",
        description="播报生成使用的模型任务名。",
        json_schema_extra={
            "hint": "可选：replyer、utils、planner 等，留空使用 Host 默认模型。",
            "label": "模型任务名",
            "placeholder": "replyer",
            "order": 1,
        },
    )


class ToolConfig(PluginConfigBase):
    """天气查询工具配置。"""

    __ui_label__: ClassVar[str] = "查询工具"
    __ui_order__: ClassVar[int] = 5

    enabled: bool = Field(
        default=True,
        description="是否启用天气查询工具。",
        json_schema_extra={
            "hint": "启用后 LLM 可在对话中自动调用天气查询。",
            "label": "启用 LLM 查询工具",
            "order": 0,
        },
    )
    default_days: int = Field(
        default=3,
        description="默认返回未来几天预报。",
        json_schema_extra={
            "hint": "范围 1-4 天。",
            "label": "默认预报天数",
            "order": 1,
            "step": 1,
        },
    )


class WeatherForecastPluginConfig(PluginConfigBase):
    """天气预报插件配置。"""

    plugin: PluginSectionConfig = Field(default_factory=PluginSectionConfig)
    weather: WeatherConfig = Field(default_factory=WeatherConfig)
    groups: GroupsConfig = Field(default_factory=GroupsConfig)
    schedule: ScheduleConfig = Field(default_factory=ScheduleConfig)
    broadcast: BroadcastConfig = Field(default_factory=BroadcastConfig)
    tool: ToolConfig = Field(default_factory=ToolConfig)


def _parse_target_groups(raw: list[str]) -> list[tuple[str, str, str]]:
    """解析群聊配置列表，返回 [(group_id, location, group_name), ...]。

    格式：
      "群号 地点"           — 地点给高德查天气
      "群号 地点|群名"       — 群名仅标注/日志，不参与查天气
    """
    results = []
    for line in raw:
        line = line.strip()
        if not line:
            continue
        parts = line.split(None, 1)
        if len(parts) == 1:
            results.append((parts[0], "", ""))
            continue
        group_id, rest = parts[0], parts[1]
        if "|" in rest:
            location, group_name = rest.split("|", 1)
            results.append((group_id, location.strip(), group_name.strip()))
        else:
            results.append((group_id, rest.strip(), ""))
    return results


class WeatherForecastPlugin(MaiBotPlugin):
    """天气预报插件"""

    config_model = WeatherForecastPluginConfig

    def __init__(self) -> None:
        super().__init__()
        self._scheduler_task: asyncio.Task[None] | None = None

    async def on_load(self) -> None:
        if self.config.plugin.enabled:
            self._scheduler_task = asyncio.create_task(self._scheduler_loop())
            self.ctx.logger.info("天气预报插件已启动")

    async def on_unload(self) -> None:
        if self._scheduler_task:
            self._scheduler_task.cancel()
            try:
                await self._scheduler_task
            except asyncio.CancelledError:
                pass
        self.ctx.logger.info("天气预报插件已卸载")

    async def on_config_update(self, scope: str, config_data: dict[str, object], version: str) -> None:
        # 仅当影响调度器/群组开关的段变更时才重启调度 loop，其他段保持热路径零开销。
        if scope not in ("schedule", "groups", "plugin"):
            return
        await self._restart_scheduler(scope, version)

    async def _restart_scheduler(self, scope: str, version: str) -> None:
        """取消旧调度 task，必要时按当前 config 启动新 task。"""
        old_task = self._scheduler_task
        if old_task is not None and not old_task.done():
            old_task.cancel()
            try:
                await old_task
            except asyncio.CancelledError:
                pass
            except Exception as e:
                self.ctx.logger.warning(f"等待旧调度任务退出失败: {e}")

        if self.config.plugin.enabled:
            self._scheduler_task = asyncio.create_task(self._scheduler_loop())
        else:
            self._scheduler_task = None

        self.ctx.logger.info(f"配置已更新（scope={scope} version={version}），调度器已重启")

    # ===== 定时广播 =====

    def _parse_broadcast_times(self, raw: str) -> list[tuple[int, int]]:
        """宽容解析 broadcast_time；非法段单独跳过并警告。

        返回 [(hour, minute), ...]；所有段都坏时返回 []，由调用方按 08:00 fallback。
        """
        raw = (raw or "").strip()
        if not raw:
            return []
        parts = [p.strip() for p in raw.replace(";", ",").split(",") if p.strip()]
        parsed: list[tuple[int, int]] = []
        for part in parts:
            try:
                if part.count(":") != 1:
                    raise ValueError(f"expected HH:MM, got '{part}'")
                hour_str, minute_str = part.split(":", 1)
                hour = int(hour_str)
                minute = int(minute_str)
                if not (0 <= hour <= 23 and 0 <= minute <= 59):
                    raise ValueError(f"hour={hour} minute={minute} out of range")
                parsed.append((hour, minute))
            except (ValueError, AttributeError) as e:
                self.ctx.logger.warning(f"忽略非法播报时间 '{part}': {e}")
        return parsed

    def _next_broadcast_target(self, now: datetime.datetime) -> datetime.datetime:
        """从 broadcast_time（支持逗号分隔多个 HH:MM）里取最近的一次。"""
        parsed = self._parse_broadcast_times(self.config.schedule.broadcast_time or "08:00")
        if not parsed:
            self.ctx.logger.warning("broadcast_time 无任何合法段，fallback 到 08:00")
            parsed = [(8, 0)]
        candidates: list[datetime.datetime] = []
        for hour, minute in parsed:
            t = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if now >= t:
                t += datetime.timedelta(days=1)
            candidates.append(t)
        return min(candidates)

    async def _scheduler_loop(self) -> None:
        await asyncio.sleep(10)
        while True:
            try:
                now = datetime.datetime.now()
                target = self._next_broadcast_target(now)
                wait = (target - now).total_seconds()
                self.ctx.logger.info(f"下次天气播报: {target.strftime('%Y-%m-%d %H:%M')}")
                await asyncio.sleep(wait)
                if self.config.schedule.broadcast_enabled:
                    await self._broadcast_all()
                else:
                    self.ctx.logger.info("定时推送已关闭，跳过本次播报")
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.ctx.logger.error(f"定时任务出错: {e}")
                await asyncio.sleep(60)


    async def _broadcast_all(self) -> None:
        groups = _parse_target_groups(self.config.groups.target_groups)
        if not groups:
            self.ctx.logger.warning("未配置目标群聊，跳过播报")
            return

        service = WeatherService(self.config.weather.amap_key)
        if not service.is_configured():
            self.ctx.logger.error("未配置高德地图API密钥")
            return

        # location -> [(group_id, group_name), ...]；同地点只查一次 API
        location_to_groups: dict[str, list[tuple[str, str]]] = {}
        for group_id, location, group_name in groups:
            location_to_groups.setdefault(location, []).append((group_id, group_name))

        broadcast_cache: dict[str, str] = {}
        for location, group_entries in location_to_groups.items():
            try:
                if location not in broadcast_cache:
                    city_info = await service.resolve_city(location)
                    if not city_info:
                        self.ctx.logger.warning(f"无法解析地点: {location}")
                        continue
                    weather_text = await service.get_region_summary(city_info["adcode"], location)
                    if not weather_text:
                        self.ctx.logger.warning(f"获取天气数据失败: {location}")
                        continue
                    broadcast = await self._generate_broadcast(weather_text)
                    if not broadcast:
                        continue
                    broadcast_cache[location] = broadcast

                text = broadcast_cache[location]
                for group_id, group_name in group_entries:
                    try:
                        stream = await self.ctx.chat.get_stream_by_group_id(group_id)
                        if not stream:
                            label = f"{group_id}({group_name})" if group_name else group_id
                            self.ctx.logger.warning(f"未找到群聊流: {label}")
                            continue
                        stream_id = stream.get("stream_id", "") if isinstance(stream, dict) else str(stream)
                        await self.ctx.send.text(text, stream_id)
                        label = f"{group_id}({group_name})" if group_name else group_id
                        self.ctx.logger.info(f"天气播报已发送: {label} 地点={location}")
                        await asyncio.sleep(2)
                    except Exception as e:
                        label = f"{group_id}({group_name})" if group_name else group_id
                        self.ctx.logger.error(f"发送到群 {label} 失败: {e}")
            except Exception as e:
                self.ctx.logger.error(f"处理地点 {location} 播报失败: {e}")


    async def _generate_broadcast(self, weather_info: str) -> str | None:
        max_length = self.config.broadcast.max_length
        bot_name = await self.ctx.config.get("bot.nickname", "我")
        personality = await self.ctx.config.get("personality.personality", "")
        reply_style = await self.ctx.config.get("personality.reply_style", "")

        prompt = (
            f"你现在是 {bot_name}。\n"
            f"【核心人设】\n你{personality}\n\n"
            f"【说话风格】\n{reply_style}\n\n"
            f"【本次任务】\n"
            f"根据以下天气信息，生成一段天气播报发送到群聊中。\n\n"
            f"【天气信息】\n{weather_info}\n\n"
            f"【输出要求】\n"
            f"1. 严格遵守上面的人设和说话风格，自然真诚。\n"
            f"2. 字数不超过 {max_length} 个汉字。\n"
            f"3. 直接输出播报内容，不要前后缀或Markdown标记。\n"
            f"4. 对各城市天气做整体概括，挑出重点。\n"
            f"5. 重点提醒温度变化大或需注意的天气（降雨、大风等）。\n"
            f"6. 可加入关心建议，如提醒带伞、添衣。\n"
        )

        model_name = (self.config.broadcast.model_name or "").strip()
        kwargs: dict[str, Any] = {"prompt": prompt}
        if model_name:
            kwargs["model"] = model_name
        result = await self.ctx.llm.generate(**kwargs)
        if not result.get("success"):
            self.ctx.logger.error("LLM生成播报失败")
            return None

        text = str(result.get("response", "")).strip().strip('"“”')
        return text[:max_length] if text else None

    # ===== 手动查询命令 =====

    @Command(
        "weather_query_cmd",
        description="查询指定地点天气",
        pattern=r"^[/／](天气|weather)\s+(?P<location>.+)$",
    )
    async def handle_weather_cmd(self, stream_id: str = "", **kwargs: Any):
        matched_groups = kwargs.get("matched_groups", {})
        location = str(matched_groups.get("location", "")).strip() if isinstance(matched_groups, dict) else ""

        if not location:
            raw_text = str(kwargs.get("text", ""))
            m = re.match(r"^[/／](?:天气|weather)\s+(.+)$", raw_text)
            if m:
                location = m.group(1).strip()

        if not location:
            await self.ctx.send.text("请提供地点名称，如：/天气 北京", stream_id)
            return False, "未提供地点", True

        service = WeatherService(self.config.weather.amap_key)
        if not service.is_configured():
            await self.ctx.send.text("天气服务未配置API密钥", stream_id)
            return False, "未配置", True

        city_info = await service.resolve_city(location)
        if not city_info:
            await self.ctx.send.text(f"未找到「{location}」对应的地区", stream_id)
            return False, "地区未找到", True

        adcode = city_info["adcode"]
        live = await service.get_live(adcode)
        forecast = await service.get_forecast(adcode)

        if not live and not forecast:
            await self.ctx.send.text(f"未能获取「{location}」的天气数据", stream_id)
            return False, "无数据", True

        text = WeatherService.format_city_weather(live, forecast, days=3)
        await self.ctx.send.text(text, stream_id)
        return True, "天气查询完成", True

    # ===== LLM 天气查询工具 =====

    @Tool(
        "weather_query",
        description="天气查询工具。当有人询问某地天气、气温、是否下雨等问题时使用，基于高德地图API。",
        parameters=[
            ToolParameterInfo(name="city", param_type=ToolParamType.STRING, description="城市或地区名称，如：北京、石家庄", required=True),
            ToolParameterInfo(name="days", param_type=ToolParamType.INTEGER, description="返回未来几天预报(1-4)", required=False),
        ],
    )
    async def handle_weather_tool(self, city: str = "", days: int = 3, **kwargs: Any):
        city = city.strip()
        if not city:
            return {"name": "weather_query", "content": "未提供城市名称。"}

        try:
            days = max(1, min(int(days), 4))
        except (TypeError, ValueError):
            days = self.config.tool.default_days

        service = WeatherService(self.config.weather.amap_key)
        if not service.is_configured():
            return {"name": "weather_query", "content": "天气服务未配置API密钥。"}

        city_info = await service.resolve_city(city)
        if not city_info:
            return {"name": "weather_query", "content": f"未找到「{city}」对应的地区。"}

        adcode = city_info["adcode"]
        live = await service.get_live(adcode)
        forecast = await service.get_forecast(adcode)

        if not live and not forecast:
            return {"name": "weather_query", "content": f"未能获取「{city}」的天气数据。"}

        text = WeatherService.format_city_weather(live, forecast, days=days)
        return {"name": "weather_query", "content": text or f"「{city}」天气数据为空。"}


def create_plugin() -> WeatherForecastPlugin:
    return WeatherForecastPlugin()

