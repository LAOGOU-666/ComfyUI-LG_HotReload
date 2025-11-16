import os
import sys
import time
import atexit
import hashlib
import logging
import requests
import threading
from collections import defaultdict
import traceback
import asyncio

from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from aiohttp import web
import folder_paths
from nodes import load_custom_node
from comfy_execution import caching
from server import PromptServer
import json
import nodes

from .Nodes.Terminal import *
RELOADED_CLASS_TYPES: dict = {}
CUSTOM_NODE_ROOT: list[str] = folder_paths.folder_names_and_paths["custom_nodes"][0]
CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.json")
def load_exclude_modules() -> set[str]:
    
    try:
        with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
            config = json.load(f)
            return set(config.get("exclude_modules", set()))
    except Exception as e:
        print(f"\033[91m[LG_HotReload] Error loading config: {str(e)}\033[0m")
        return set()
def save_exclude_modules(modules: set[str]):
    
    try:
        with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
            json.dump({"exclude_modules": list(modules)}, f, indent=4)
        print(f"\033[92m[LG_HotReload] Exclude modules config saved\033[0m")
    except Exception as e:
        print(f"\033[91m[LG_HotReload] Error saving config: {str(e)}\033[0m")
EXCLUDE_MODULES: set[str] = load_exclude_modules()
@PromptServer.instance.routes.get("/hotreload/get_exclude_modules")
async def get_exclude_modules(request):
    return web.json_response({"exclude_modules": list(EXCLUDE_MODULES)})
@PromptServer.instance.routes.post("/hotreload/update_exclude_modules")
async def update_exclude_modules(request):
    try:
        data = await request.json()
        modules = set(data.get("exclude_modules", []))
        global EXCLUDE_MODULES
        EXCLUDE_MODULES = modules
        save_exclude_modules(modules)
        return web.json_response({"status": "success"})
    except Exception as e:
        return web.json_response({"status": "error", "message": str(e)}, status=500)
    
@PromptServer.instance.routes.get("/hotreload/get_all_modules")
async def get_all_modules(request):
    try:
        modules = []
        for item in os.listdir(CUSTOM_NODE_ROOT[0]):
            item_path = os.path.join(CUSTOM_NODE_ROOT[0], item)
            if os.path.isdir(item_path) and not item.startswith('.'):
                if os.path.exists(os.path.join(item_path, '__init__.py')):
                    modules.append(item)
        return web.json_response({"modules": modules})
    except Exception as e:
        return web.json_response({"status": "error", "message": str(e)}, status=500)
@PromptServer.instance.routes.get("/extensions/{module_name}/{path:.*}")
async def dynamic_extensions_handler(request):
    """处理动态加载的插件的WEB_DIRECTORY文件访问"""
    module_name = request.match_info['module_name']
    file_path = request.match_info['path']

    # 优先从 EXTENSION_WEB_DIRS 中查找（自定义节点，支持热更新）
    if module_name in nodes.EXTENSION_WEB_DIRS:
        web_dir = nodes.EXTENSION_WEB_DIRS[module_name]
        full_path = os.path.join(web_dir, file_path)

        if os.path.isfile(full_path):
            return web.FileResponse(full_path)

    # 如果不在 EXTENSION_WEB_DIRS 中，尝试从 ComfyUI 前端包的 extensions 目录查找（系统扩展如 core）
    # PromptServer.instance.web_root 指向前端包的静态文件目录
    # 例如：E:\python3.11\Lib\site-packages\comfyui_frontend_package\static
    if hasattr(PromptServer.instance, 'web_root') and PromptServer.instance.web_root:
        web_root = PromptServer.instance.web_root
        full_path = os.path.join(web_root, "extensions", module_name, file_path)

        if os.path.isfile(full_path):
            return web.FileResponse(full_path)

    # 如果都找不到，返回404
    raise web.HTTPNotFound()

# 存储动态路由映射
DYNAMIC_API_ROUTES = {}

def is_module_match(handler_module: str, module_name: str, sys_module_name: str = None) -> bool:
    """
    检查 handler 的模块名是否匹配目标模块

    Args:
        handler_module: handler.__module__ 的值
        module_name: 模块名（如 "comfyui-clear-screen"）
        sys_module_name: sys.modules 中的模块名（路径中的 "." 被替换为 "_x_"）

    Returns:
        是否匹配
    """
    if not handler_module:
        return False

    # 直接匹配
    if module_name == handler_module:
        return True

    # 匹配 sys_module_name（如果提供）
    if sys_module_name and sys_module_name == handler_module:
        return True

    # 匹配各种路径格式
    patterns = [
        f"custom_nodes.{module_name}",
        f"custom_nodes\\{module_name}",
        f"custom_nodes/{module_name}",
        f"\\{module_name}",
        f"/{module_name}",
    ]

    for pattern in patterns:
        if handler_module.endswith(pattern) or pattern in handler_module:
            return True

    # 如果 sys_module_name 提供了，也检查它的各种格式
    if sys_module_name:
        if sys_module_name in handler_module or handler_module in sys_module_name:
            return True

    return False

@PromptServer.instance.routes.get("/api/{path:.*}")
async def dynamic_api_handler(request):
    """动态处理热更新的API路由"""
    path = "/" + request.match_info['path']  # 重构完整路径
    method = request.method.upper()
    
    # 查找动态注册的处理器
    route_key = f"{method}:{path}"
    if route_key in DYNAMIC_API_ROUTES:
        handler = DYNAMIC_API_ROUTES[route_key]
        return await handler(request)
    
    # 如果没找到动态路由，让系统继续处理
    raise web.HTTPNotFound()

def register_module_routes(module_name, sys_module_name=None):
    """注册模块的所有路由到动态路由表"""
    # 清理旧路由 - 从 DYNAMIC_API_ROUTES（通过模块路径匹配）
    keys_to_remove = []
    for route_key, handler in DYNAMIC_API_ROUTES.items():
        if hasattr(handler, '__module__'):
            handler_module = handler.__module__
            # 使用统一的匹配函数
            if is_module_match(handler_module, module_name, sys_module_name):
                keys_to_remove.append(route_key)

    for key in keys_to_remove:
        del DYNAMIC_API_ROUTES[key]

    # 注册新路由到动态路由表
    registered_count = 0
    for route in PromptServer.instance.routes:
        if hasattr(route, 'handler') and hasattr(route.handler, '__module__'):
            handler_module = route.handler.__module__
            # 使用统一的匹配函数
            if is_module_match(handler_module, module_name, sys_module_name):
                route_key = f"{route.method}:{route.path}"
                DYNAMIC_API_ROUTES[route_key] = route.handler
                registered_count += 1


if (HOTRELOAD_EXCLUDE := os.getenv("HOTRELOAD_EXCLUDE", None)) is not None:
    EXCLUDE_MODULES.update(x for x in HOTRELOAD_EXCLUDE.split(',') if x)
HOTRELOAD_OBSERVE_ONLY: set[str] = set(x for x in os.getenv("HOTRELOAD_OBSERVE_ONLY", '').split(',') if x)
HOTRELOAD_EXTENSIONS: set[str] = set(x.strip() for x in os.getenv("HOTRELOAD_EXTENSIONS", '.py').split(',') if x)
try:
    DEBOUNCE_TIME: float = float(os.getenv("HOTRELOAD_DEBOUNCE_TIME", 1.0))
except ValueError:
    DEBOUNCE_TIME = 1.0
def hash_file(file_path: str) -> str:

    try:
        with open(file_path, 'rb') as f:
            return hashlib.md5(f.read()).hexdigest()
    except Exception as e:
        logging.error(f"Error reading file {file_path}: {e}")
        return None
def is_hidden_file_windows(file_path: str) -> bool:

    try:
        import ctypes
        attribute = ctypes.windll.kernel32.GetFileAttributesW(file_path)
        if attribute == -1:
            return False
        return attribute & 0x2 != 0
    except Exception as e:
        logging.error(f"Error checking if file is hidden on Windows: {e}")
        return False
def is_hidden_file(file_path: str) -> bool:

    file_path = os.path.abspath(file_path)
    if sys.platform.startswith('win'):
        while file_path and file_path != os.path.dirname(file_path):
            if is_hidden_file_windows(file_path):
                return True
            file_path = os.path.dirname(file_path)
    else:
        while file_path and file_path != os.path.dirname(file_path):
            if os.path.basename(file_path).startswith('.'):
                return True
            file_path = os.path.dirname(file_path)
    return False
def dfs(item_list: list, searches: set) -> bool:

    for item in item_list:
        if isinstance(item, (frozenset, tuple)) and dfs(item, searches):
            return True
        elif item in searches:
            return True
    return False
class DebouncedHotReloader(FileSystemEventHandler):
    
    def __init__(self, delay: float = 1.0):

        super().__init__()
        self.__delay: float = delay
        self.__last_modified: defaultdict[str, float] = defaultdict(float)
        self.__reload_timers: dict[str, threading.Timer] = {}
        self.__hashes: dict[str, str] = {}
        self.__lock: threading.Lock = threading.Lock()
        # 添加最后成功重载时间记录
        self.__last_successful_reload: defaultdict[float] = defaultdict(float)
        self.__successful_reload_cooldown = 5.0  # 成功重载后的冷却时间（秒）
    def __reload(self, module_name: str) -> web.Response:
        with self.__lock:
            try:
                print(f'\n\033[94m[LG_HotReload] 开始重载模块: {module_name}\033[0m')

                # 计算 sys_module_name（与 load_custom_node 中的逻辑一致）
                # load_custom_node 会将路径中的 "." 替换为 "_x_"
                module_path_for_sys = os.path.join(CUSTOM_NODE_ROOT[0], module_name)
                sys_module_name = module_path_for_sys.replace(".", "_x_")
                original_routes_count = len(PromptServer.instance.routes)
                
                # 收集需要保留的路由
                routes_to_keep = []
                routes_removed_count = 0
                
                for route in PromptServer.instance.routes:
                    should_remove = False
                    if hasattr(route, 'handler') and hasattr(route.handler, '__module__'):
                        handler_module = route.handler.__module__
                        # 使用统一的匹配函数
                        if is_module_match(handler_module, module_name, sys_module_name):
                            should_remove = True
                            routes_removed_count += 1
                            route_key = f"{route.method}:{route.path}"


                    if not should_remove:
                        routes_to_keep.append(route)
                
                # 重建路由表
                if routes_removed_count > 0:
                    # 由于RouteTableDef不支持直接删除路由，我们采用替换策略
                    # 直接使用_items清理路由
                    try:
                        PromptServer.instance.routes._items.clear()
                        PromptServer.instance.routes._items.extend(routes_to_keep)
                    except Exception as e:
                        print(f'\033[91m[LG_HotReload] 路由清理失败: {str(e)}\033[0m')
                        traceback.print_exc()
                else:
                    print(f'\033[96m[LG_HotReload] 未发现需要清理的路由\033[0m')

                module_path = os.path.join(CUSTOM_NODE_ROOT[0], module_name)

                # 收集需要重新加载的所有模块
                modules_to_reload = set()
                for name, module in list(sys.modules.items()):
                    if hasattr(module, '__file__') and module.__file__ and \
                       module.__file__.startswith(module_path):
                        modules_to_reload.add(name)

                # 删除所有相关模块
                for name in modules_to_reload:
                    if name in sys.modules:
                        del sys.modules[name]

                # 重新加载自定义节点
                # 追踪load_custom_node前的路由数量
                routes_before_load = len(PromptServer.instance.routes)

                try:
                    # 使用 asyncio.run 来同步调用异步函数
                    success = asyncio.run(load_custom_node(module_path))
                except Exception as e:
                    print(f'\033[91m[LG_HotReload] 调用 load_custom_node 失败: {str(e)}\033[0m')
                    success = False
                
                # 追踪load_custom_node后的路由数量
                routes_after_load = len(PromptServer.instance.routes)

                if not success:
                    print(f'\033[91m[LG_HotReload] 加载模块失败: {module_name}\033[0m')
                    return web.Response(text='FAILED')

                # 关键步骤：同步新路由到 aiohttp 的 router
                # 通过直接替换 handler 来实现热重载
                try:
                    # 获取新添加的路由
                    new_routes_count = routes_after_load - routes_before_load
                    if new_routes_count > 0 and hasattr(PromptServer.instance, 'app') and PromptServer.instance.app:
                        new_routes = list(PromptServer.instance.routes)[-new_routes_count:]
                        router = PromptServer.instance.app.router

                        for route in new_routes:
                            if hasattr(route, 'method') and hasattr(route, 'path') and hasattr(route, 'handler'):
                                if hasattr(route.handler, '__module__'):
                                    handler_module = route.handler.__module__
                                    if is_module_match(handler_module, module_name, sys_module_name):
                                        handler_id = id(route.handler)

                                        # 查找并替换旧的 handler
                                        for resource in list(router._resources):
                                            resource_path = getattr(resource, '_path', None) or getattr(resource, 'canonical', None)

                                            # 匹配路径（包括 /api 前缀的版本）
                                            if resource_path and (resource_path == route.path or resource_path == f"/api{route.path}"):
                                                for route_obj in resource:
                                                    if hasattr(route_obj, 'handler') and hasattr(route_obj.handler, '__module__'):
                                                        route_handler_module = route_obj.handler.__module__
                                                        if is_module_match(route_handler_module, module_name, sys_module_name):
                                                            # 直接替换 handler（保留路由缓存结构）
                                                            if hasattr(route_obj, '_handler'):
                                                                old_id = id(route_obj._handler)
                                                                route_obj._handler = route.handler


                except Exception as e:
                    print(f'\033[91m[LG_HotReload] 路由同步失败: {str(e)}\033[0m')
                    traceback.print_exc()


                # 确保模块被正确注册到sys.modules中
                try:
                    import importlib.util
                    # 构建完整的模块名（包含custom_nodes前缀）
                    full_module_name = f"custom_nodes.{module_name}"
                    
                    if os.path.isfile(module_path):
                        # 处理单个.py文件
                        spec = importlib.util.spec_from_file_location(full_module_name, module_path)
                    else:
                        # 处理模块目录
                        init_path = os.path.join(module_path, '__init__.py')
                        spec = importlib.util.spec_from_file_location(full_module_name, init_path)

                    if spec:
                        # 追踪模块注册前的路由数量
                        routes_before_register = len(PromptServer.instance.routes)

                        # load_custom_node已经执行了模块代码，这里只需要注册到sys.modules
                        # 获取已经加载的模块（通过load_custom_node加载）
                        loaded_module = None
                        
                        # 尝试从sys.modules中找到已加载的模块
                        for mod_name, mod in sys.modules.items():
                            if (hasattr(mod, '__file__') and mod.__file__ and 
                                mod.__file__.startswith(module_path)):
                                loaded_module = mod
                                break
                        
                        if loaded_module:
                            # 使用已加载的模块，避免重复执行
                            sys.modules[full_module_name] = loaded_module
                            sys.modules[module_name] = loaded_module

                        else:
                            # 如果找不到已加载的模块，则正常加载（备用方案）
                            module = importlib.util.module_from_spec(spec)
                            sys.modules[full_module_name] = module
                            sys.modules[module_name] = module
                            spec.loader.exec_module(module)


                except Exception as e:
                    print(f'\033[91m[LG_HotReload] 重新注册模块失败: {str(e)}\033[0m')
                    traceback.print_exc()

                # 确保节点被正确注册到全局的 NODE_CLASS_MAPPINGS 中
                module = sys.modules.get(module_name)
                if module and hasattr(module, 'NODE_CLASS_MAPPINGS'):
                    # 先清理旧的节点映射
                    for name in list(nodes.NODE_CLASS_MAPPINGS.keys()):
                        if name in module.NODE_CLASS_MAPPINGS:
                            del nodes.NODE_CLASS_MAPPINGS[name]

                    # 重新注册节点
                    for name, node_cls in module.NODE_CLASS_MAPPINGS.items():
                        nodes.NODE_CLASS_MAPPINGS[name] = node_cls
                        node_cls.RELATIVE_PYTHON_MODULE = f"custom_nodes.{module_name}"

                    if hasattr(module, 'NODE_DISPLAY_NAME_MAPPINGS'):
                        nodes.NODE_DISPLAY_NAME_MAPPINGS.update(module.NODE_DISPLAY_NAME_MAPPINGS)

                # 更新节点类型
                if module and hasattr(module, 'NODE_CLASS_MAPPINGS'):
                    for key in module.NODE_CLASS_MAPPINGS.keys():
                        RELOADED_CLASS_TYPES[key] = 3
                # 重新注册API路由（到动态路由表）
                register_module_routes(module_name, sys_module_name)

                print(f'\033[92m[LG_HotReload] 模块重载成功: {module_name}\033[0m')
                return web.Response(text='OK')

            except Exception as e:
                logging.error(f"Failed to reload module {module_name}: {e}")
                traceback.print_exc()
                return web.Response(text='FAILED')
    def on_created(self, event):
        
        if event.is_directory:
            return
        self.handle_file_event(event.src_path)
    def on_deleted(self, event):
        
        if event.is_directory:
            return
        self.handle_file_event(event.src_path)
    def handle_file_event(self, file_path: str):
        
        if not any(ext == '*' for ext in HOTRELOAD_EXTENSIONS):
            if not any(file_path.endswith(ext) for ext in HOTRELOAD_EXTENSIONS):
                return
        if is_hidden_file(file_path):
            return
        relative_path: str = os.path.relpath(file_path, CUSTOM_NODE_ROOT[0])
        root_dir: str = relative_path.split(os.path.sep)[0]
        if HOTRELOAD_OBSERVE_ONLY and root_dir not in HOTRELOAD_OBSERVE_ONLY:
            return
        elif root_dir in EXCLUDE_MODULES:
            return
        self.schedule_reload(root_dir, file_path)
    def on_modified(self, event):
        
        if event.is_directory:
            return
        self.handle_file_event(event.src_path)
    def schedule_reload(self, module_name: str, file_path: str):

        current_time: float = time.time()
        self.__last_modified[module_name] = current_time
        with self.__lock:
            if module_name in self.__reload_timers:
                self.__reload_timers[module_name].cancel()
            timer = threading.Timer(
                self.__delay,
                self.check_and_reload,
                args=[module_name, current_time, file_path]
            )
            self.__reload_timers[module_name] = timer
            timer.start()

    def check_and_reload(self, module_name: str, scheduled_time: float, file_path: str):

        with self.__lock:
            if self.__last_modified[module_name] != scheduled_time:
                return
            # 检查是否在冷却期内
            current_time = time.time()
            if (current_time - self.__last_successful_reload[module_name]) < self.__successful_reload_cooldown:
                print(f"\033[93m[LG_HotReload] Module {module_name} was recently reloaded, skipping...\033[0m")
                return
        try:
            # 获取重载前的节点信息
            old_nodes = set()
            old_module = sys.modules.get(module_name)
            if old_module and hasattr(old_module, 'NODE_CLASS_MAPPINGS'):
                old_nodes = set(old_module.NODE_CLASS_MAPPINGS.keys())

            # 重载模块
            self.__reload(module_name)

            # 添加调试信息
            print(f'\033[94m[LG_HotReload] 检查节点注册状态:\033[0m')
            module = sys.modules.get(module_name)
            if module and hasattr(module, 'NODE_CLASS_MAPPINGS'):
                for node_class in module.NODE_CLASS_MAPPINGS.keys():
                    if node_class in nodes.NODE_CLASS_MAPPINGS:
                        print(f'\033[92m[LG_HotReload] 节点 {node_class} 已成功注册\033[0m')
                    else:
                        print(f'\033[91m[LG_HotReload] 节点 {node_class} 注册失败\033[0m')

            # 获取重载后的节点信息
            new_nodes = set()
            if module and hasattr(module, 'NODE_CLASS_MAPPINGS'):
                new_nodes = set(module.NODE_CLASS_MAPPINGS.keys())

            # 计算节点变化
            added_nodes = new_nodes - old_nodes
            removed_nodes = old_nodes - new_nodes
            updated_nodes = new_nodes & old_nodes

            # 确定文件变更类型
            action = "deleted" if not os.path.exists(file_path) else "added" if file_path not in self.__hashes else "modified"

            # 发送更新消息给前端
            update_message = {
                "type": "hot_reload_update",
                "data": {
                    "module": module_name,
                    "action": action,
                    "file": file_path,
                    "timestamp": time.time(),
                    "changes": {
                        "added": list(added_nodes),
                        "removed": list(removed_nodes),
                        "updated": list(updated_nodes)
                    }
                }
            }

            if hasattr(PromptServer.instance, "send_sync"):
                PromptServer.instance.send_sync(
                    "hot_reload_update",
                    update_message["data"]
                )



            self.__last_successful_reload[module_name] = time.time()
            print(f'\033[92m[LG_HotReload] Successfully reloaded module: {module_name}\033[0m')
            
        except requests.RequestException as e:
            print(f'\033[91m[LG_HotReload] Reload failed: {e}\033[0m')
        except Exception as e:
            print(f'\033[91m[LG_HotReload] Error occurred: {e}\033[0m')
            traceback.print_exc()
class HotReloaderService:
    
    def __init__(self, delay: float = 1.0):

        self.__observer: Observer = None
        self.__reloader: DebouncedHotReloader = DebouncedHotReloader(delay)
    def start(self):
        
        self.__observer = Observer()
        self.__observer.schedule(self.__reloader, CUSTOM_NODE_ROOT[0], recursive=True)
        self.__observer.start()
    def stop(self):
        
        if self.__observer:
            self.__observer.stop()
            self.__observer.join()
def monkeypatch():
    
    original_set_prompt = caching.BasicCache.set_prompt
    def set_prompt(self, dynprompt, node_ids, is_changed_cache):

        if not hasattr(self, 'cache_key_set'):
            RELOADED_CLASS_TYPES.clear()
            return original_set_prompt(self, dynprompt, node_ids, is_changed_cache)
        found_keys = []
        for key, item_list in self.cache_key_set.keys.items():
            if dfs(item_list, RELOADED_CLASS_TYPES):
                found_keys.append(key)
        if len(found_keys):
            for value_key in list(RELOADED_CLASS_TYPES.keys()):
                RELOADED_CLASS_TYPES[value_key] -= 1
                if RELOADED_CLASS_TYPES[value_key] == 0:
                    del RELOADED_CLASS_TYPES[value_key]
        for key in found_keys:
            cache_key = self.cache_key_set.get_data_key(key)
            if cache_key and cache_key in self.cache:
                del self.cache[cache_key]
                del self.cache_key_set.keys[key]
                del self.cache_key_set.subcache_keys[key]
        return original_set_prompt(self, dynprompt, node_ids, is_changed_cache)
    caching.HierarchicalCache.set_prompt = set_prompt

def setup():
    
    logging.info("[LG_HotReload] Monkey patching comfy_execution.caching.BasicCache")
    monkeypatch()
    hot_reloader_service = HotReloaderService(delay=DEBOUNCE_TIME)
    atexit.register(hot_reloader_service.stop)
    hot_reloader_service.start()
setup()
WEB_DIRECTORY = "./web"
NODE_CLASS_MAPPINGS = {"HotReload_Terminal": HotReload_Terminal}
NODE_DISPLAY_NAME_MAPPINGS = {"HotReload_Terminal": "Terminal"}