# ComfyUI LG_HotReload 扩展

<!-- 语言切换 -->
[中文](README.md) | [English](README_en.md)

一个用于 ComfyUI 的热重载扩展，安装即可，让你在开发自定义节点/安装插件时能够实时预览更改，无需重启 ComfyUI。

感谢[@Mo-enen](https://github.com/Mo-enen) 制作的Terminal节点完美解决系统终端重载后失效的BUG

![Image](https://github.com/user-attachments/assets/1b317a55-01ef-4e1a-a1c2-06f92c59d83d)

![Image](setting.png)

## 新增功能

- 新增了排除热重载模块配置，可以配置需要排除的热重载的模块。使用方法如下：
  1. 点击设置按钮
  2. 找到 HotReload 选项
  3. 点击打开配置
  4. 在模块输入框输入需要排除的模块（自定义节点文件夹名称，也可以查看控制台获取）
  5. 点击添加，即可将指定模块排除热重载

## 主要特性

- 🔄 实时热重载：修改代码后自动重新加载节点
- 🎯 智能监控：仅监控指定的文件类型和目录
- 🚀 即时更新：前端界面自动刷新，展示最新更改
- 🛡️ 防抖设计：避免频繁重载带来的性能问题
- 📁 支持web文件：自动同步节点的web目录内容
- 🔍 路由热重载：支持API路由的实时更新


## 使用方法

1. 克隆仓库到 ComfyUI 的 `custom_nodes` 目录：
   ```bash
   cd path/to/ComfyUI/custom_nodes
   git clone https://github.com/LAOGOU-666/ComfyUI-LG_HotReload.git
   ```

2. 安装依赖：
   ```
   cd ComfyUI-LG_HotReload
   pip install -r requirements.txt
   ```

3. 启动 ComfyUI
4. 开始编辑你的自定义节点，保存后将自动重载,你只需要重置节点或者刷新网页即可（这个只是一个插件，没有实体节点，装了就不用管它，后台自动处理）

## 注意事项

- 建议在开发环境中使用，生产环境请谨慎启用
- 某些复杂的更改可能仍需要重启 ComfyUI
- 确保你的代码没有语法错误，否则可能影响重载过程


# 如果您受益于本项目，不妨请作者喝杯咖啡，您的支持是我最大的动力

<div style="display: flex; justify-content: left; gap: 20px;">
    <img src="https://raw.githubusercontent.com/LAOGOU-666/Comfyui-Transform/9ac1266765b53fb1d666f9c8a1d61212f2603a92/assets/alipay.jpg" width="300" alt="支付宝收款码">
    <img src="https://raw.githubusercontent.com/LAOGOU-666/Comfyui-Transform/9ac1266765b53fb1d666f9c8a1d61212f2603a92/assets/wechat.jpg" width="300" alt="微信收款码">
</div>



## 致谢

本项目基于 [ComfyUI-HotReloadHack](https://github.com/logtd/ComfyUI-HotReloadHack) 进行了重构和增强。特别感谢原作者 [@logtd](https://github.com/logtd) 提供的优秀代码基础。 

