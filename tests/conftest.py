"""
weather-forecast 测试夹具：
在不依赖 MaiBot SDK 的本地环境里也能 import plugin.py / weather_service.py。

做法：
1. 注入 maibot_sdk stub 到 sys.modules（Field / PluginConfigBase / Command / Tool / MaiBotPlugin / ToolParameterInfo / ToolParamType）
2. 把目录 whitefox_weather-forecast 作为 _wf_pkg 这个虚拟包名装载，让 plugin.py 内部的
   `from .weather_service import WeatherService` 相对导入能解析
"""

from __future__ import annotations

import importlib.util
import sys
import types
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

import pytest

PACKAGE_DIR = Path(__file__).resolve().parent.parent
PACKAGE_NAME = "_wf_pkg"


# ---------- maibot_sdk stub ----------

CONFIG_RELOAD_SCOPE_SELF = "self"


class _Field:
    """最简 Pydantic Field 替身：descriptor。"""

    def __init__(self, default: Any = None, default_factory: Optional[Callable[[], Any]] = None, **metadata: Any) -> None:
        self.default = default
        self.default_factory = default_factory
        self.metadata = metadata

    def __set_name__(self, owner, name: str) -> None:
        self.name = name

    def __get__(self, instance: Any, owner: type) -> Any:
        if instance is None:
            return self
        if self.name not in instance.__dict__:
            instance.__dict__[self.name] = self.default_factory() if self.default_factory else self.default
        return instance.__dict__[self.name]


def Field(default: Any = None, default_factory: Optional[Callable[[], Any]] = None, **metadata: Any) -> _Field:
    return _Field(default=default, default_factory=default_factory, **metadata)


class PluginConfigBase:
    """对 plugin 来说只关心 __init__(**kwargs) 把字段 setattr 进来。"""

    def __init__(self, **kwargs: Any) -> None:
        for k, v in kwargs.items():
            setattr(self, k, v)


class _Command:
    def __init__(self, name: str, description: str = "", pattern: str = "") -> None:
        self.name = name
        self.description = description
        self.pattern = pattern

    def __call__(self, func: Callable) -> Callable:
        func.__command__ = self
        return func


class _Tool:
    def __init__(self, name: str, description: str = "", parameters: Optional[list] = None) -> None:
        self.name = name
        self.description = description
        self.parameters = parameters or []

    def __call__(self, func: Callable) -> Callable:
        func.__tool__ = self
        return func


class _ToolParameterInfo:
    def __init__(self, name: str, param_type: Any, description: str = "", required: bool = False) -> None:
        self.name = name
        self.param_type = param_type
        self.description = description
        self.required = required


class _ToolParamType:
    STRING = "string"
    INTEGER = "integer"


@dataclass
class _Logger:
    infos: list = field(default_factory=list)
    warnings: list = field(default_factory=list)
    errors: list = field(default_factory=list)
    debugs: list = field(default_factory=list)

    def _record(self, level: str, msg: str) -> None:
        getattr(self, level + "s").append(msg)

    def info(self, msg: str, *args: Any, **kwargs: Any) -> None:
        self._record("info", msg % args if args else msg)

    def warning(self, msg: str, *args: Any, **kwargs: Any) -> None:
        self._record("warning", msg % args if args else msg)

    def error(self, msg: str, *args: Any, **kwargs: Any) -> None:
        self._record("error", msg % args if args else msg)

    def debug(self, msg: str, *args: Any, **kwargs: Any) -> None:
        self._record("debug", msg % args if args else msg)


@dataclass
class _LLM:
    async def generate(self, *args: Any, **kwargs: Any) -> dict:
        return {"success": True, "response": "OK"}


@dataclass
class _ConfigStore:
    async def get(self, key: str, default: Any = None) -> Any:
        return default


@dataclass
class _SendText:
    async def text(self, text: str, stream_id: str) -> None:
        return None


@dataclass
class _Send:
    text: Any = field(default_factory=_SendText)


@dataclass
class _Context:
    logger: _Logger = field(default_factory=_Logger)
    llm: _LLM = field(default_factory=_LLM)
    send: _Send = field(default_factory=_Send)
    config: _ConfigStore = field(default_factory=_ConfigStore)


class MaiBotPlugin:
    config_model: type = PluginConfigBase

    def __init__(self) -> None:
        self.ctx = _Context()
        self.config = self.config_model()


def install_sdk_stub() -> None:
    if "maibot_sdk" in sys.modules:
        return

    mod = types.ModuleType("maibot_sdk")
    mod.CONFIG_RELOAD_SCOPE_SELF = CONFIG_RELOAD_SCOPE_SELF
    mod.Field = Field
    mod.PluginConfigBase = PluginConfigBase
    mod.Command = _Command
    mod.Tool = _Tool
    mod.MaiBotPlugin = MaiBotPlugin
    sys.modules["maibot_sdk"] = mod

    types_mod = types.ModuleType("maibot_sdk.types")
    types_mod.ToolParameterInfo = _ToolParameterInfo
    types_mod.ToolParamType = _ToolParamType
    sys.modules["maibot_sdk.types"] = types_mod


# ---------- 把整个插件目录装载成虚拟包 ----------

def _load_package() -> dict:
    """装载 weather-forecast 目录为虚拟包，返回 {'plugin': module, 'weather_service': module}。"""
    if PACKAGE_NAME in sys.modules:
        return {
            "plugin": sys.modules[f"{PACKAGE_NAME}.plugin"],
            "weather_service": sys.modules[f"{PACKAGE_NAME}.weather_service"],
        }

    pkg_spec = importlib.util.spec_from_file_location(
        PACKAGE_NAME,
        PACKAGE_DIR / "__init__.py",
        submodule_search_locations=[str(PACKAGE_DIR)],
    )
    pkg = importlib.util.module_from_spec(pkg_spec)
    sys.modules[PACKAGE_NAME] = pkg
    assert pkg_spec.loader is not None
    pkg_spec.loader.exec_module(pkg)

    plugin_path = PACKAGE_DIR / "plugin.py"
    ws_path = PACKAGE_DIR / "weather_service.py"

    plugin_spec = importlib.util.spec_from_file_location(f"{PACKAGE_NAME}.plugin", plugin_path)
    plugin_mod = importlib.util.module_from_spec(plugin_spec)
    sys.modules[f"{PACKAGE_NAME}.plugin"] = plugin_mod
    assert plugin_spec.loader is not None
    plugin_spec.loader.exec_module(plugin_mod)

    ws_spec = importlib.util.spec_from_file_location(f"{PACKAGE_NAME}.weather_service", ws_path)
    ws_mod = importlib.util.module_from_spec(ws_spec)
    sys.modules[f"{PACKAGE_NAME}.weather_service"] = ws_mod
    assert ws_spec.loader is not None
    ws_spec.loader.exec_module(ws_mod)

    # 显式把 plugin 的 WeatherService 引用也写入 plugin_mod 命名空间，保证
    # `from .weather_service import WeatherService` 已经发生
    setattr(plugin_mod, "WeatherService", ws_mod.WeatherService)

    return {"plugin": plugin_mod, "weather_service": ws_mod}


@pytest.fixture(scope="session")
def loaded_package() -> dict:
    install_sdk_stub()
    return _load_package()


@pytest.fixture()
def plugin_cls(loaded_package: dict) -> type:
    return loaded_package["plugin"].WeatherForecastPlugin


@pytest.fixture()
def weather_service_cls(loaded_package: dict) -> type:
    return loaded_package["weather_service"].WeatherService
