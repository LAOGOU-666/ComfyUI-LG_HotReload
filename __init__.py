"""
"""
import os
import sys
import time
import atexit
import hashlib
import logging
import requests
import threading
import importlib
from collections import defaultdict
import traceback
import shutil
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
from aiohttp import web
import folder_paths
from nodes import load_custom_node
from comfy_execution import caching
from server import PromptServer
import json

RELOADED_CLASS_TYPES: dict = {}
CUSTOM_NODE_ROOT: list[str] = folder_paths.folder_names_and_paths["custom_nodes"][0]
CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.json")

def load_exclude_modules() -> set[str]:
    """加载排除模块配置"""
    try:
        with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
            config = json.load(f)
            return set(config.get("exclude_modules", set()))
    except Exception as e:
        print(f"\033[91m[LG_HotReload] Error loading config: {str(e)}\033[0m")
        return set()  # 如果读取失败，返回空集合

def save_exclude_modules(modules: set[str]):
    """保存排除模块配置"""
    try:
        with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
            json.dump({"exclude_modules": list(modules)}, f, indent=4)
        print(f"\033[92m[LG_HotReload] Exclude modules config saved\033[0m")
    except Exception as e:
        print(f"\033[91m[LG_HotReload] Error saving config: {str(e)}\033[0m")

# 初始化排除模块集合
EXCLUDE_MODULES: set[str] = load_exclude_modules()

# 添加API路由
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

if (HOTRELOAD_EXCLUDE := os.getenv("HOTRELOAD_EXCLUDE", None)) is not None:
    EXCLUDE_MODULES.update(x for x in HOTRELOAD_EXCLUDE.split(',') if x)
HOTRELOAD_OBSERVE_ONLY: set[str] = set(x for x in os.getenv("HOTRELOAD_OBSERVE_ONLY", '').split(',') if x)
HOTRELOAD_EXTENSIONS: set[str] = set(x.strip() for x in os.getenv("HOTRELOAD_EXTENSIONS", '.py,.json,.yaml').split(',') if x)
try:
    DEBOUNCE_TIME: float = float(os.getenv("HOTRELOAD_DEBOUNCE_TIME", 1.0))
except ValueError:
    DEBOUNCE_TIME = 1.0
def hash_file(file_path: str) -> str:
    """
    Computes the MD5 hash of a file's contents.
    :param file_path: The path to the file.
    :return: The MD5 hash as a hexadecimal string, or None if an error occurs.
    """
    try:
        with open(file_path, 'rb') as f:
            return hashlib.md5(f.read()).hexdigest()
    except Exception as e:
        logging.error(f"Error reading file {file_path}: {e}")
        return None
def is_hidden_file_windows(file_path: str) -> bool:
    """
    Check if a given file or directory is hidden on Windows.
    :param file_path: Path to the file or directory.
    :return: True if the file or directory is hidden, False otherwise.
    """
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
    """
    Check if a given file or any of its parent directories is hidden.
    Works across all major operating systems (Windows, Linux, macOS).
    :param file_path: Path to the file or directory to check.
    :return: True if the file or any parent directory is hidden, False otherwise.
    """
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
    """
    Performs a depth-first search to find items in a list.
    :param item_list: The list of items to search through.
    :param searches: The set of search items to look for.
    :return: True if any search item is found, False otherwise.
    """
    for item in item_list:
        if isinstance(item, (frozenset, tuple)) and dfs(item, searches):
            return True
        elif item in searches:
            return True
    return False
class HotReloadRouteDecorator:
    """热更新路由装饰器"""
    def __init__(self, original_routes):
        self.original_routes = original_routes
        self.route_registry = {}
    def _register_route(self, method):
        def decorator(path):
            def wrapper(handler):
                original_handler = self.original_routes.__getattribute__(method)(path)(handler)
                module_name = handler.__module__
                route_key = f"{method.upper()}:{path}"
                self.route_registry[route_key] = {
                    'module': module_name,
                    'handler_name': handler.__name__,
                    'path': path,
                    'method': method
                }
                return original_handler
            return wrapper
        return decorator
    def __getattr__(self, name):
        if name in ('get', 'post', 'put', 'delete', 'patch'):
            return self._register_route(name)
        return getattr(self.original_routes, name)
    def __iter__(self):
        """实现迭代器接口"""
        return iter(self.original_routes)
    def __len__(self):
        """实现长度接口"""
        return len(self.original_routes)
    def __contains__(self, item):
        return item in self.original_routes
class RouteReloader:
    """路由重载器"""
    def __init__(self):
        self.route_decorator = None
        self.original_routes = None
        self.setup_hot_reload()
    def setup_hot_reload(self):
        self.original_routes = PromptServer.instance.routes
        self.route_decorator = HotReloadRouteDecorator(self.original_routes)
        PromptServer.instance.routes = self.route_decorator
    def reload_routes(self, module_name: str):
        """重新加载指定模块的路由"""
        try:
            routes_to_reload = {
                key: info for key, info in self.route_decorator.route_registry.items()
                if info['module'] == module_name
            }
            if not routes_to_reload:
                return
            for route_info in routes_to_reload.values():
                path = route_info['path']
                method = route_info['method'].upper()
                routes_to_remove = []
                for resource in self.original_routes.app.router.resources():
                    for route in resource:
                        if route.method == method and route.resource.canonical == path:
                            routes_to_remove.append(resource)
                for resource in routes_to_remove:
                    self.original_routes.app.router.resources().remove(resource)
            module = sys.modules[module_name]
            importlib.reload(module)
            print(f'\033[92m[LG_HotReload] Reloaded routes for module: {module_name}\033[0m')
        except Exception as e:
            print(f'\033[91m[LG_HotReload] Failed to reload routes: {str(e)}\033[0m')
            traceback.print_exc()
class DebouncedHotReloader(FileSystemEventHandler):
    """Hot reloader with debouncing mechanism to reload modules on file changes."""
    def __init__(self, delay: float = 1.0):
        """
        Initialize the DebouncedHotReloader.
        :param delay: Delay in seconds before reloading modules after detecting a change.
        """
        super().__init__()
        self.__delay: float = delay
        self.__last_modified: defaultdict[str, float] = defaultdict(float)
        self.__reload_timers: dict[str, threading.Timer] = {}
        self.__hashes: dict[str, str] = {}
        self.__lock: threading.Lock = threading.Lock()
        self.route_reloader = RouteReloader()
    def __reload(self, module_name: str) -> web.Response:
        """
        重新加载模块及其所有子模块
        :param module_name: 要重新加载的模块名称
        :return: web.Response 表示成功或失败
        """
        with self.__lock:
            try:
                self.route_reloader.reload_routes(module_name)
                
                # 获取模块路径
                module_path = os.path.join(CUSTOM_NODE_ROOT[0], module_name)
                
                # 收集需要重新加载的所有模块
                modules_to_reload = set()
                for name, module in list(sys.modules.items()):
                    # 检查模块是否属于目标模块路径
                    if hasattr(module, '__file__') and module.__file__ and \
                       module.__file__.startswith(module_path):
                        modules_to_reload.add(name)
                
                # 删除所有相关模块
                for name in modules_to_reload:
                    if name in sys.modules:
                        del sys.modules[name]
                
                # 重新加载主模块
                module_path_init = os.path.join(module_path, '__init__.py')
                spec = importlib.util.spec_from_file_location(module_name, module_path_init)
                module = importlib.util.module_from_spec(spec)
                sys.modules[module_name] = module
                spec.loader.exec_module(module)
                
                # 更新节点类型
                for key in getattr(module, 'NODE_CLASS_MAPPINGS', {}).keys():
                    RELOADED_CLASS_TYPES[key] = 3
                
                # 重新加载自定义节点
                load_custom_node(module_path)
                
                print(f'\033[92m[LG_HotReload] Successfully reloaded module and submodules: {module_name}\033[0m')
                print(f'\033[92m[LG_HotReload] Reloaded modules: {modules_to_reload}\033[0m')
                print(f'\033[92m[LG_HotReload] Loaded nodes: {list(getattr(module, "NODE_CLASS_MAPPINGS", {}).keys())}\033[0m')
                
                return web.Response(text='OK')
                
            except Exception as e:
                logging.error(f"Failed to reload module {module_name}: {e}")
                traceback.print_exc()
                return web.Response(text='FAILED')
    def on_created(self, event):
        """Handles file creation events."""
        if event.is_directory:
            return
        self.handle_file_event(event.src_path)
    def on_deleted(self, event):
        """Handles file deletion events."""
        if event.is_directory:
            return
        self.handle_file_event(event.src_path)
    def handle_file_event(self, file_path: str):
        """Common handler for file events (modified/created/deleted)."""
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
        """Handles file modification events."""
        if event.is_directory:
            return
        self.handle_file_event(event.src_path)
    def schedule_reload(self, module_name: str, file_path: str):
        """
        Schedules a reload of the given module after a delay.
        :param module_name: The name of the module to reload.
        :param file_path: The path of the modified file.
        """
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
    def copy_web_files(self, module_name: str, web_dir: str):
        """
        将web目录下的文件复制到extensions目录
        Args:
            module_name: 模块名称
            web_dir: web目录路径
        """
        try:
            web_root = PromptServer.instance.web_root
            extensions_dir = os.path.join(web_root, "extensions", module_name)
            os.makedirs(extensions_dir, exist_ok=True)
            for item in os.listdir(web_dir):
                src = os.path.join(web_dir, item)
                dst = os.path.join(extensions_dir, item)
                if os.path.isfile(src):
                    shutil.copy2(src, dst)
                elif os.path.isdir(src):
                    if os.path.exists(dst):
                        shutil.rmtree(dst)
                    shutil.copytree(src, dst)
        except Exception as e:
            print(f"\033[91m[LG_HotReload] Error copying files: {str(e)}\033[0m")
            traceback.print_exc()
    def check_and_reload(self, module_name: str, scheduled_time: float, file_path: str):
        """
        检查时间戳并在需要时重新加载模块，同时通知前端刷新
        :param module_name: 要检查的模块名称
        :param scheduled_time: 计划的重载时间
        :param file_path: 修改的文件路径
        """
        with self.__lock:
            if self.__last_modified[module_name] != scheduled_time:
                return
        try:
            # 获取模块并检查 NODE_CLASS_MAPPINGS 是否存在
            module = sys.modules.get(module_name)
            if module is None or not hasattr(module, 'NODE_CLASS_MAPPINGS'):
                old_nodes = set()
            else:
                old_nodes = set(module.NODE_CLASS_MAPPINGS.keys())

            self.__reload(module_name)

            # 再次检查 NODE_CLASS_MAPPINGS 是否存在
            new_nodes = set()
            module = sys.modules.get(module_name)  # 重新获取重载后的模块
            if hasattr(module, 'NODE_CLASS_MAPPINGS'):
                new_nodes = set(module.NODE_CLASS_MAPPINGS.keys())

            added_nodes = new_nodes - old_nodes
            removed_nodes = old_nodes - new_nodes
            updated_nodes = new_nodes & old_nodes
            action = "deleted" if not os.path.exists(file_path) else "added" if file_path not in self.__hashes else "modified"
            
            print(f'\033[92m[LG_HotReload] Reloaded module: {module_name}\033[0m')
            if added_nodes:
                print(f'\033[92m[LG_HotReload] Added nodes: {added_nodes}\033[0m')
            if removed_nodes:
                print(f'\033[92m[LG_HotReload] Removed nodes: {removed_nodes}\033[0m')
            if updated_nodes:
                print(f'\033[92m[LG_HotReload] Updated nodes: {updated_nodes}\033[0m')

            # 发送更新消息
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
                print(f'\033[92m[LG_HotReload] Sent update signal to frontend\033[0m')

            # 处理 web 文件 - 独立于节点映射的检查
            module_path = os.path.join(CUSTOM_NODE_ROOT[0], module_name)
            if module and hasattr(module, 'WEB_DIRECTORY'):  # 只检查WEB_DIRECTORY
                web_dir = os.path.join(module_path, module.WEB_DIRECTORY)
                if os.path.exists(web_dir) and os.path.isdir(web_dir):
                    self.copy_web_files(module_name, web_dir)
                    print(f'\033[92m[LG_HotReload] Updated web files for {module_name}\033[0m')
                else:
                    print(f'\033[93m[LG_HotReload] Web directory not found: {web_dir}\033[0m')

        except requests.RequestException as e:
            print(f'\033[91m[LG_HotReload] Reload failed: {e}\033[0m')
        except Exception as e:
            print(f'\033[91m[LG_HotReload] Error occurred: {e}\033[0m')
            traceback.print_exc()
class HotReloaderService:
    """Service to manage the hot reloading of modules."""
    def __init__(self, delay: float = 1.0):
        """
        Initialize the HotReloaderService.
        :param delay: Delay in seconds before reloading modules after detecting a change.
        """
        self.__observer: Observer = None
        self.__reloader: DebouncedHotReloader = DebouncedHotReloader(delay)
    def start(self):
        """Start observing for file changes."""
        self.__observer = Observer()
        self.__observer.schedule(self.__reloader, CUSTOM_NODE_ROOT[0], recursive=True)
        self.__observer.start()
    def stop(self):
        """Stop observing for file changes."""
        if self.__observer:
            self.__observer.stop()
            self.__observer.join()
def monkeypatch():
    """Apply necessary monkey patches for hot reloading."""
    original_set_prompt = caching.BasicCache.set_prompt
    def set_prompt(self, dynprompt, node_ids, is_changed_cache):
        """
        Custom set_prompt function to handle cache clearing for hot reloading.
        :param dynprompt: Dynamic prompt to set.
        :param node_ids: Node IDs to process.
        :param is_changed_cache: Boolean flag indicating if cache has changed.
        """
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
def cleanup_extensions_directory():
    try:
        web_root = PromptServer.instance.web_root
        extensions_dir = os.path.join(web_root, "extensions")
        if not os.path.exists(extensions_dir):
            return
        
        # 获取custom_nodes中的文件夹名称
        custom_nodes_path = CUSTOM_NODE_ROOT[0]
        custom_node_folders = set(os.listdir(custom_nodes_path))
        
        # 检查并清理extensions目录
        for item in os.listdir(extensions_dir):
            item_path = os.path.join(extensions_dir, item)
            # 如果extensions中的文件夹名与custom_nodes中的文件夹名相同，就删除
            if os.path.isdir(item_path) and item in custom_node_folders:
                try:
                    import shutil
                    shutil.rmtree(item_path)
                    print(f"\033[93m[LG_HotReload] Cleaned up duplicate extension directory: {item}\033[0m")
                except Exception as e:
                    print(f"\033[91m[LG_HotReload] Error cleaning up {item}: {str(e)}\033[0m")
    except Exception as e:
        print(f"\033[91m[LG_HotReload] Error during extensions cleanup: {str(e)}\033[0m")
        traceback.print_exc()
def setup():
    """Sets up the hot reload system."""
    logging.info("[LG_HotReload] Monkey patching comfy_execution.caching.BasicCache")
    monkeypatch()
    cleanup_extensions_directory()
    hot_reloader_service = HotReloaderService(delay=DEBOUNCE_TIME)
    atexit.register(hot_reloader_service.stop)
    hot_reloader_service.start()
setup()
WEB_DIRECTORY = "./web"
NODE_CLASS_MAPPINGS = {}
NODE_DISPLAY_NAME_MAPPINGS = {}