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
import nodes
from pathlib import Path
from .Nodes.Terminal import *
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
        return set()
def save_exclude_modules(modules: set[str]):
    """保存排除模块配置"""
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
        # 添加最后成功重载时间记录
        self.__last_successful_reload: defaultdict[float] = defaultdict(float)
        self.__successful_reload_cooldown = 5.0  # 成功重载后的冷却时间（秒）
    def __reload(self, module_name: str) -> web.Response:
        with self.__lock:
            try:
                print(f'\n\033[94m[LG_HotReload] 开始重载模块: {module_name}\033[0m')
                
                module_path = os.path.join(CUSTOM_NODE_ROOT[0], module_name)
                
                # 保存原始路由
                routes = PromptServer.instance.routes
                original_routes = list(routes._items)
                
                try:
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
                    
                    # 清理路由
                    routes._items = [route for route in routes._items
                                   if not (hasattr(route.handler, '__module__')
                                         and route.handler.__module__ == module_name)]
                    
                    # 重新加载自定义节点 - 这会处理路由注册
                    success = load_custom_node(module_path)
                    if not success:
                        print(f'\033[91m[LG_HotReload] 加载模块失败: {module_name}\033[0m')
                        return web.Response(text='FAILED')
                    
                    # 确保模块被正确注册到sys.modules中
                    try:
                        import importlib.util
                        if os.path.isfile(module_path):
                            # 处理单个.py文件
                            spec = importlib.util.spec_from_file_location(module_name, module_path)
                        else:
                            # 处理模块目录
                            init_path = os.path.join(module_path, '__init__.py')
                            spec = importlib.util.spec_from_file_location(module_name, init_path)
                        
                        if spec:
                            module = importlib.util.module_from_spec(spec)
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
                    
                    # 重新设置路由器
                    app = PromptServer.instance.app
                    new_router = web.UrlDispatcher()
                    
                    # 注册所有路由
                    for route in routes._items:
                        if isinstance(route, web.RouteDef):
                            method = route.method.lower()
                            path = f"/api{route.path}"
                            try:
                                new_router.add_route(method, path, route.handler)
                                new_router.add_route(method, route.path, route.handler)
                            except Exception as route_error:
                                print(f'\033[93m[LG_HotReload] 注册路由失败: {route_error}\033[0m')
                    
                    # 添加静态路由
                    try:
                        for name, dir in nodes.EXTENSION_WEB_DIRS.items():
                            new_router.add_static('/extensions/' + name, dir)
                        custom_nodes_dir = Path(CUSTOM_NODE_ROOT[0])
                        kjweb_path = custom_nodes_dir / "comfyui-kjnodes" / "kjweb_async"
                        if kjweb_path.exists():
                            new_router.add_static('/kjweb_async', kjweb_path.as_posix())
                        new_router.add_static('/', PromptServer.instance.web_root)
                    except Exception as e:
                        print(f'\033[93m[LG_HotReload] 添加静态路由失败: {e}\033[0m')
                    
                    # 更新路由器
                    app._router = new_router
                    
                except Exception as e:
                    # 确保在出错时恢复原始路由
                    routes._items = original_routes
                    raise e

                # 更新节点类型
                module = sys.modules.get(module_name)
                if module and hasattr(module, 'NODE_CLASS_MAPPINGS'):
                    for key in module.NODE_CLASS_MAPPINGS.keys():
                        RELOADED_CLASS_TYPES[key] = 3

                print(f'\033[92m[LG_HotReload] 模块重载成功: {module_name}\033[0m')
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

            # 处理web文件
            module_path = os.path.join(CUSTOM_NODE_ROOT[0], module_name)
            if module and hasattr(module, 'WEB_DIRECTORY'):
                web_dir = os.path.join(module_path, module.WEB_DIRECTORY)
                if os.path.exists(web_dir) and os.path.isdir(web_dir):
                    self.copy_web_files(module_name, web_dir)

            self.__last_successful_reload[module_name] = time.time()
            print(f'\033[92m[LG_HotReload] Successfully reloaded module: {module_name}\033[0m')
            
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
        
        custom_nodes_path = CUSTOM_NODE_ROOT[0]
        custom_node_folders = set(os.listdir(custom_nodes_path))
        
        # 排除需要忽略的模块
        folders_to_clean = custom_node_folders - EXCLUDE_MODULES
        
        for item in os.listdir(extensions_dir):
            item_path = os.path.join(extensions_dir, item)
            # 只清理非排除且存在于自定义节点目录的文件夹
            if os.path.isdir(item_path) and item in folders_to_clean:
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
NODE_CLASS_MAPPINGS = {"HotReload_Terminal": HotReload_Terminal}
NODE_DISPLAY_NAME_MAPPINGS = {"HotReload_Terminal": "Terminal"}