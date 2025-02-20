# ComfyUI LG_HotReload 扩展

一个用于 ComfyUI 的热重载扩展，让你在开发自定义节点时能够实时预览更改，无需重启 ComfyUI。

## 主要特性

- 🔄 实时热重载：修改代码后自动重新加载节点
- 🎯 智能监控：仅监控指定的文件类型和目录
- 🚀 即时更新：前端界面自动刷新，展示最新更改
- 🛡️ 防抖设计：避免频繁重载带来的性能问题
- 📁 支持web文件：自动同步节点的web目录内容
- 🔍 路由热重载：支持API路由的实时更新

## 环境变量配置

可以通过以下环境变量自定义热重载行为：

- `HOTRELOAD_EXCLUDE`: 排除不需要监控的模块，多个模块用逗号分隔
- `HOTRELOAD_OBSERVE_ONLY`: 仅监控指定的模块，多个模块用逗号分隔
- `HOTRELOAD_EXTENSIONS`: 监控的文件扩展名，默认为 `.py,.json,.yaml`
- `HOTRELOAD_DEBOUNCE_TIME`: 重载延迟时间（秒），默认为 1.0

## 使用方法

1. 克隆仓库到 ComfyUI 的 `custom_nodes` 目录：
   ```bash
   cd path/to/ComfyUI/custom_nodes
   git clone https://github.com/LAOGOU-666/ComfyUI-LG-HotReload.git
   ```

2. 安装依赖：
   ```
   cd ComfyUI-LG-HotReload
   pip install -r requirements.txt
   ```

3. 启动 ComfyUI
4. 开始编辑你的自定义节点，保存后将自动重载,你只需要重置节点或者刷新网页即可

## 注意事项

- 建议在开发环境中使用，生产环境请谨慎启用
- 某些复杂的更改可能仍需要重启 ComfyUI
- 确保你的代码没有语法错误，否则可能影响重载过程

## 致谢

本项目基于 [ComfyUI-HotReloadHack](https://github.com/logtd/ComfyUI-HotReloadHack) 进行了重构和增强。特别感谢原作者 [@logtd](https://github.com/logtd) 提供的优秀代码基础。 