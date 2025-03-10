import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";
app.registerExtension({
    name: "Comfy.HotReload",
    async setup() {
        api.removeEventListener("hot_reload_update", this._handleHotReload);
        api.addEventListener("hot_reload_update", async (event) => {
            const message = event.detail;
            console.log("[HotReload] Received update signal:", message);
            const changes = message.changes;
            const nodesToUpdate = [...changes.added, ...changes.updated];
            if (nodesToUpdate.length > 0) {
                try {
                    const savedStates = new Map();
                    for (const nodeClass of nodesToUpdate) {
                        const existingNodes = app.graph.findNodesByType(nodeClass);
                        existingNodes.forEach(node => {
                            savedStates.set(node.id, {
                                id: node.id,
                                pos: [...node.pos],
                                size: [...node.size],
                                widgets: node.widgets?.reduce((acc, w) => {
                                    acc[w.name] = w.serializeValue ? w.serializeValue() : w.value;
                                    return acc;
                                }, {}),
                                properties: {...node.properties}
                            });
                        });
                    }
                    
                    // 更新节点定义
                    for (const nodeClass of nodesToUpdate) {
                        try {
                            console.log(`[HotReload] 正在获取节点数据: ${nodeClass}`);
                            const response = await api.fetchApi(`/object_info/${nodeClass}`);
                            
                            if (!response.ok) {
                                console.error(`[HotReload] 获取节点数据失败: ${nodeClass}, 状态码: ${response.status}`);
                                const text = await response.text();
                                console.error(`[HotReload] 错误详情:`, text);
                                continue;
                            }

                            const nodeData = await response.json();
                            console.log(`[HotReload] 获取到节点数据:`, nodeData);
                            
                            if (nodeData && nodeData[nodeClass]) {
                                app.registerNodeDef(nodeClass, nodeData[nodeClass]);
                                const existingNodes = app.graph.findNodesByType(nodeClass);
                                console.log(`[HotReload] 更新现有节点数量: ${existingNodes.length}`);
                                
                                existingNodes.forEach(node => {
                                    if (node.widgets) {
                                        node.widgets.forEach(widget => {
                                            if (widget.type === "combo" &&
                                                nodeData[nodeClass]["input"]["required"][widget.name]) {
                                                widget.options.values = nodeData[nodeClass]["input"]["required"][widget.name][0];
                                                console.log(`[HotReload] 更新 combo 选项: ${widget.name}`, widget.options.values);
                                            }
                                        });
                                    }
                                    node.refreshComboInNode?.(nodeData);
                                });
                            } else {
                                console.error(`[HotReload] 节点数据格式错误:`, nodeData);
                            }
                        } catch (error) {
                            console.error(`[HotReload] 处理节点更新时出错: ${nodeClass}`, error);
                        }
                    }

                    // 恢复节点状态，但不处理连接
                    for (const state of savedStates.values()) {
                        const node = app.graph.getNodeById(state.id);
                        if (node) {
                            node.pos = state.pos;
                            node.size = state.size;
                            Object.assign(node.properties, state.properties);
                            if (node.widgets) {
                                node.widgets.forEach(w => {
                                    if (state.widgets[w.name] !== undefined) {
                                        if (w.loadValue) {
                                            w.loadValue(state.widgets[w.name]);
                                        } else {
                                            w.value = state.widgets[w.name];
                                        }
                                    }
                                });
                            }
                        }
                    }
                    app.graph.setDirtyCanvas(true);
                } catch (error) {
                    console.error("[HotReload] Failed to update nodes:", error);
                    console.error("[HotReload] Error details:", error.stack);
                }
            }
        });
    }
});
app.registerExtension({
    name: "ComfyUI.HotReload",
    async setup() {
        await app.ui.settings.setup;
        async function getExcludedModules() {
            try {
                const response = await api.fetchApi('/hotreload/get_exclude_modules');
                const data = await response.json();
                return data.exclude_modules || [];
            } catch (error) {
                console.error('获取排除列表失败:', error);
                return [];
            }
        }
        app.ui.settings.addSetting({
            id: "HotReload.config",
            name: "热加载模块配置",
            type: () => {
                const row = document.createElement("tr");
                row.className = "hotreload-settings-row";
                const buttonCell = document.createElement("td");
                const button = document.createElement("button");
                button.className = "comfy-btn";
                button.textContent = "打开配置";
                button.onclick = () => {
                    showHotReloadDialog();
                };
                buttonCell.appendChild(button);
                row.appendChild(buttonCell);
                return row;
            }
        });
        async function showHotReloadDialog() {
            const modules = await getExcludedModules();
            const dialog = document.createElement("div");
            dialog.className = "hotreload-dialog";
            dialog.style.position = "fixed";
            dialog.style.top = "50%";
            dialog.style.left = "50%";
            dialog.style.transform = "translate(-50%, -50%)";
            dialog.style.backgroundColor = "#1a1a1a";
            dialog.style.border = "1px solid #444";
            dialog.style.borderRadius = "8px";
            dialog.style.padding = "20px";
            dialog.style.zIndex = "10000";
            dialog.style.minWidth = "400px";
            dialog.style.maxWidth = "600px";
            dialog.style.boxShadow = "0 4px 23px 0 rgba(0, 0, 0, 0.2)";
            const title = document.createElement("h2");
            title.textContent = "热加载模块配置";
            title.style.margin = "0 0 20px 0";
            title.style.borderBottom = "1px solid #444";
            title.style.paddingBottom = "10px";
            dialog.appendChild(title);
            const description = document.createElement("p");
            description.textContent = "添加需要排除热加载的模块名称。这些模块在代码修改后不会自动重新加载。";
            description.style.marginBottom = "20px";
            description.style.color = "#aaa";
            dialog.appendChild(description);
            const listContainer = document.createElement("div");
            listContainer.style.maxHeight = "200px";
            listContainer.style.overflowY = "auto";
            listContainer.style.marginBottom = "20px";
            listContainer.style.border = "1px solid #333";
            listContainer.style.borderRadius = "4px";
            listContainer.style.padding = "5px";
            function renderModuleList() {
                listContainer.innerHTML = '';
                if (modules.length === 0) {
                    const emptyMsg = document.createElement("div");
                    emptyMsg.textContent = "没有排除的模块";
                    emptyMsg.style.padding = "10px";
                    emptyMsg.style.color = "#888";
                    listContainer.appendChild(emptyMsg);
                    return;
                }
                modules.forEach(module => {
                    const item = document.createElement("div");
                    item.style.display = "flex";
                    item.style.justifyContent = "space-between";
                    item.style.alignItems = "center";
                    item.style.padding = "8px";
                    item.style.borderBottom = "1px solid #333";
                    const nameSpan = document.createElement("span");
                    nameSpan.textContent = module;
                    const deleteBtn = document.createElement("button");
                    deleteBtn.textContent = "删除";
                    deleteBtn.className = "comfy-btn";
                    deleteBtn.style.padding = "2px 8px";
                    deleteBtn.style.fontSize = "12px";
                    deleteBtn.style.marginLeft = "10px";
                    deleteBtn.onclick = async () => {
                        const index = modules.indexOf(module);
                        if (index > -1) {
                            modules.splice(index, 1);
                            await api.fetchApi('/hotreload/update_exclude_modules', {
                                method: 'POST',
                                headers: { 'Content-Type': 'application/json' },
                                body: JSON.stringify({ exclude_modules: modules })
                            });
                            renderModuleList();
                        }
                    };
                    item.appendChild(nameSpan);
                    item.appendChild(deleteBtn);
                    listContainer.appendChild(item);
                });
            }
            renderModuleList();
            dialog.appendChild(listContainer);
            const inputContainer = document.createElement("div");
            inputContainer.style.display = "flex";
            inputContainer.style.marginBottom = "20px";
            const input = document.createElement("input");
            input.type = "text";
            input.placeholder = "输入模块名称";
            input.style.flex = "1";
            input.style.padding = "8px";
            input.style.border = "1px solid #444";
            input.style.borderRadius = "4px";
            input.style.backgroundColor = "#333";
            input.style.color = "#eee";
            const addBtn = document.createElement("button");
            addBtn.textContent = "添加";
            addBtn.className = "comfy-btn";
            addBtn.style.marginLeft = "10px";
            addBtn.style.padding = "8px 15px";
            inputContainer.appendChild(input);
            inputContainer.appendChild(addBtn);
            dialog.appendChild(inputContainer);
            const buttonsContainer = document.createElement("div");
            buttonsContainer.style.display = "flex";
            buttonsContainer.style.justifyContent = "flex-end";
            buttonsContainer.style.marginTop = "20px";
            const closeBtn = document.createElement("button");
            closeBtn.textContent = "关闭";
            closeBtn.className = "comfy-btn";
            closeBtn.style.padding = "8px 20px";
            buttonsContainer.appendChild(closeBtn);
            dialog.appendChild(buttonsContainer);
            addBtn.onclick = async () => {
                const moduleName = input.value.trim();
                if (moduleName && !modules.includes(moduleName)) {
                    modules.push(moduleName);
                    await api.fetchApi('/hotreload/update_exclude_modules', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ exclude_modules: modules })
                    });
                    input.value = '';
                    renderModuleList();
                }
            };
            input.addEventListener('keydown', async (e) => {
                if (e.key === 'Enter') {
                    e.preventDefault();
                    const moduleName = input.value.trim();
                    if (moduleName && !modules.includes(moduleName)) {
                        modules.push(moduleName);
                        await api.fetchApi('/hotreload/update_exclude_modules', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ exclude_modules: modules })
                        });
                        input.value = '';
                        renderModuleList();
                    }
                }
            });
            closeBtn.onclick = () => {
                document.body.removeChild(dialog);
                if (document.getElementById('hotreload-dialog-overlay')) {
                    document.body.removeChild(document.getElementById('hotreload-dialog-overlay'));
                }
            };
            const overlay = document.createElement("div");
            overlay.id = "hotreload-dialog-overlay";
            overlay.style.position = "fixed";
            overlay.style.top = "0";
            overlay.style.left = "0";
            overlay.style.width = "100%";
            overlay.style.height = "100%";
            overlay.style.backgroundColor = "rgba(0, 0, 0, 0.5)";
            overlay.style.zIndex = "9999";
            document.body.appendChild(overlay);
            document.body.appendChild(dialog);
            input.focus();
        }
    }
});