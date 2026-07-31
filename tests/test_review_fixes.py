"""
HIGH 2 项 + MEDIUM 1 项 TDD 修复测试。

HIGH 1: plugin.on_config_update 重新调度
HIGH 2: plugin._next_broadcast_target 容忍非法段
MEDIUM:  WeatherService 内 httpx.AsyncClient 类成员单例 + aclose hook + trust_env=False
"""

from __future__ import annotations

import asyncio
import datetime
import sys
import types
from typing import Any
from unittest.mock import MagicMock

import pytest


# ---------- HIGH 1: on_config_update 重新调度 ----------


@pytest.mark.asyncio
async def test_on_config_update_schedule_reschedules(plugin_cls) -> None:
    """schedule 段变更时，旧调度 task 被取消，新调度 task 起来，并记录日志。"""
    plugin = plugin_cls()
    await plugin.on_load()
    old_task = plugin._scheduler_task
    assert old_task is not None and not old_task.done()

    try:
        await plugin.on_config_update("schedule", {"broadcast_time": "06:00"}, "v2")

        assert old_task.cancelled() or old_task.done(), "旧调度 task 应被取消"
        new_task = plugin._scheduler_task
        assert new_task is not None
        assert new_task is not old_task
        assert any("重启" in m or "重新调度" in m or "已更新" in m for m in plugin.ctx.logger.infos)
    finally:
        await plugin.on_unload()


@pytest.mark.asyncio
async def test_on_config_update_noop_for_irrelevant_scope(plugin_cls) -> None:
    """无关 scope（比如 broadcast）不应重启调度器，避免无意义抖动。"""
    plugin = plugin_cls()
    await plugin.on_load()
    old_task = plugin._scheduler_task
    assert old_task is not None and not old_task.done()

    try:
        await plugin.on_config_update("broadcast", {"max_length": 200}, "v2")
        # 旧 task 仍存活；新 task 未替换
        assert plugin._scheduler_task is old_task
        assert not old_task.cancelled()
    finally:
        await plugin.on_unload()


@pytest.mark.asyncio
async def test_on_config_update_skips_when_disabled(plugin_cls) -> None:
    """插件被禁用后 on_config_update：scheduler task 不创建新 task。"""
    plugin = plugin_cls()
    plugin.config.plugin.enabled = False
    # on_load 因为 enabled=False 不会启动 task，保持 None
    await plugin.on_load()
    assert plugin._scheduler_task is None

    await plugin.on_config_update("schedule", {"broadcast_time": "06:00"}, "v2")
    # 仍然 None，没有启动任何 task
    assert plugin._scheduler_task is None


# ---------- HIGH 2: broadcast_time 解析宽容 ----------


def _next(plugin_cls, time_str: str, now: datetime.datetime) -> datetime.datetime:
    plugin = plugin_cls()
    plugin.config.schedule.broadcast_time = time_str
    return plugin._next_broadcast_target(now)


def test_next_broadcast_target_skips_invalid_segment(plugin_cls) -> None:
    now = datetime.datetime(2026, 7, 26, 7, 30, 0)
    # 25:00 非法，06:00 合法；只保留合法段
    target = _next(plugin_cls, "25:00,06:00", now)
    assert target.hour == 6 and target.minute == 0
    # 当前 07:30 已过今天的 06:00，应该跳到明天
    assert target.day == 27
    # 非法段应该有 warning 日志
    plugin = plugin_cls()
    plugin.config.schedule.broadcast_time = "25:00,06:00"
    plugin._next_broadcast_target(now)
    assert any("25:00" in m or "非法" in m for m in plugin.ctx.logger.warnings)


def test_next_broadcast_target_falls_back_when_all_invalid(plugin_cls) -> None:
    now = datetime.datetime(2026, 7, 26, 7, 30, 0)
    # 全坏 → fallback 08:00
    target = _next(plugin_cls, "25:00", now)
    assert target.hour == 8 and target.minute == 0
    assert target.day == 26  # 07:30 < 08:00


def test_next_broadcast_target_no_exception_for_garbage(plugin_cls) -> None:
    now = datetime.datetime(2026, 7, 26, 7, 30, 0)
    # 完全乱写的输入不抛异常，走 fallback
    target = _next(plugin_cls, "abc,def", now)
    assert target.hour == 8 and target.minute == 0


def test_next_broadcast_target_minute_out_of_range_skipped(plugin_cls) -> None:
    now = datetime.datetime(2026, 7, 26, 7, 30, 0)
    # 99 分钟非法；06:00 合法
    target = _next(plugin_cls, "08:99,06:00", now)
    assert target.hour == 6 and target.minute == 0


def test_next_broadcast_target_normal_still_works(plugin_cls) -> None:
    """回归测试：合法单一时间仍是明天 06:00。"""
    now = datetime.datetime(2026, 7, 26, 7, 30, 0)
    target = _next(plugin_cls, "06:00", now)
    assert target.hour == 6 and target.minute == 0
    assert target.day == 27


# ---------- MEDIUM: WeatherService httpx 客户端单例 + trust_env=False + aclose ----------


class _FakeResponse:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def json(self) -> dict:
        return self._payload


def _make_fake_client_class(captured: dict) -> type:
    class _FakeAsyncClient:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            captured.setdefault("constructs", []).append(kwargs)
            self._closed = False

        async def get(self, url: str, params: dict | None = None) -> _FakeResponse:
            captured.setdefault("gets", []).append((url, params))
            return _FakeResponse({
                "status": "1",
                "districts": [{"adcode": "350181", "name": "福清", "level": "city", "districts": []}],
            })

        async def aclose(self) -> None:
            self._closed = True
            captured["closed"] = captured.get("closed", 0) + 1

    return _FakeAsyncClient


@pytest.mark.asyncio
async def test_weather_service_reuses_client_across_calls(weather_service_cls, monkeypatch) -> None:
    captured: dict = {}
    fake_cls = _make_fake_client_class(captured)
    import httpx

    monkeypatch.setattr(httpx, "AsyncClient", fake_cls)

    svc = weather_service_cls("test_key")
    # 两次 district 请求：单例意味着 client 只构造一次
    await svc._request_district("福清")
    await svc._request_district("福清")

    assert len(captured["constructs"]) == 1, "WeatherService 应只构造一次 AsyncClient"


@pytest.mark.asyncio
async def test_weather_service_client_trust_env_false(weather_service_cls, monkeypatch) -> None:
    captured: dict = {}
    fake_cls = _make_fake_client_class(captured)
    import httpx

    monkeypatch.setattr(httpx, "AsyncClient", fake_cls)

    svc = weather_service_cls("test_key")
    await svc._request_district("福清")

    assert captured["constructs"][0].get("trust_env") is False, (
        "默认 trust_env 应为 False，避免被宿主 HTTP_PROXY/HTTPS_PROXY 污染"
    )


@pytest.mark.asyncio
async def test_weather_service_aclose_releases_client(weather_service_cls, monkeypatch) -> None:
    captured: dict = {}
    fake_cls = _make_fake_client_class(captured)
    import httpx

    monkeypatch.setattr(httpx, "AsyncClient", fake_cls)

    svc = weather_service_cls("test_key")
    await svc._request_district("福清")
    await svc.aclose()
    assert captured.get("closed") == 1


@pytest.mark.asyncio
async def test_weather_service_async_context_manager(weather_service_cls, monkeypatch) -> None:
    """`async with WeatherService(...) as svc:` 用法走 aclose 关闭。"""
    captured: dict = {}
    fake_cls = _make_fake_client_class(captured)
    import httpx

    monkeypatch.setattr(httpx, "AsyncClient", fake_cls)

    async with weather_service_cls("test_key") as svc:
        await svc._request_district("福清")

    assert captured.get("closed") == 1
