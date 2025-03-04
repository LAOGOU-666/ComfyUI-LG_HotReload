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
                                widgets: node.widgets?.reduce((acc, w, index) => {
                                    try {
                                        if (w && w.name) {
                                            if (w.serializeValue && typeof w.serializeValue === 'function') {
                                                const serializedValue = w.serializeValue(node, index);
                                                if (serializedValue !== undefined) {
                                                    acc[w.name] = serializedValue;
                                                }
                                            } else if (w.value !== undefined) {
                                                acc[w.name] = w.value;
                                            }
                                        }
                                    } catch (err) {
                                        console.warn(`[HotReload] Failed to serialize widget ${w?.name}:`, err);
                                        if (w && w.value !== undefined) {
                                            acc[w.name] = w.value;
                                        }
                                    }
                                    return acc;
                                }, {}),
                                properties: {...node.properties}
                            });
                        });
                    }
                    
                    // 更新节点定义
                    for (const nodeClass of nodesToUpdate) {
                        try {
                            const response = await api.fetchApi(`/object_info/${nodeClass}`);
                            if (!response.ok) {
                                console.warn(`[HotReload] Failed to fetch info for node ${nodeClass}: ${response.status} ${response.statusText}`);
                                continue;
                            }
                            
                            let nodeData;
                            try {
                                nodeData = await response.json();
                            } catch (jsonError) {
                                console.warn(`[HotReload] Invalid JSON response for node ${nodeClass}:`, jsonError);
                                continue;
                            }

                            if (!nodeData || !nodeData[nodeClass]) {
                                console.warn(`[HotReload] Invalid node data for ${nodeClass}`);
                                continue;
                            }

                            app.registerNodeDef(nodeClass, nodeData[nodeClass]);
                            const existingNodes = app.graph.findNodesByType(nodeClass);
                            existingNodes.forEach(node => {
                                if (node.widgets) {
                                    node.widgets.forEach(widget => {
                                        if (widget.type === "combo" &&
                                            nodeData[nodeClass]["input"]?.["required"]?.[widget.name]) {
                                            widget.options.values = nodeData[nodeClass]["input"]["required"][widget.name][0];
                                        }
                                    });
                                }
                                node.refreshComboInNode?.(nodeData);
                            });
                        } catch (error) {
                            console.warn(`[HotReload] Error updating node ${nodeClass}:`, error);
                            continue;
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
            
            // 获取所有可用模块
            let allAvailableModules = [];
            try {
                const response = await api.fetchApi('/hotreload/get_all_modules');
                const data = await response.json();
                allAvailableModules = data.modules;
            } catch (error) {
                console.error('获取所有模块失败:', error);
            }

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

            // 添加搜索框
            const searchContainer = document.createElement("div");
            searchContainer.style.marginBottom = "15px";
            searchContainer.style.display = "flex";
            searchContainer.style.alignItems = "center";

            const searchInput = document.createElement("input");
            searchInput.type = "text";
            searchInput.placeholder = "搜索已排除的模块...";
            searchInput.style.flex = "1";
            searchInput.style.padding = "8px";
            searchInput.style.border = "1px solid #444";
            searchInput.style.borderRadius = "4px";
            searchInput.style.backgroundColor = "#333";
            searchInput.style.color = "#eee";
            searchInput.style.marginBottom = "10px";

            searchContainer.appendChild(searchInput);
            dialog.appendChild(searchContainer);

            const listContainer = document.createElement("div");
            listContainer.style.maxHeight = "200px";
            listContainer.style.overflowY = "auto";
            listContainer.style.marginBottom = "20px";
            listContainer.style.border = "1px solid #333";
            listContainer.style.borderRadius = "4px";
            listContainer.style.padding = "5px";

            function renderModuleList(searchTerm = '') {
                listContainer.innerHTML = '';
                const filteredModules = searchTerm 
                    ? modules.filter(m => m.toLowerCase().includes(searchTerm.toLowerCase()))
                    : modules;

                if (filteredModules.length === 0) {
                    const emptyMsg = document.createElement("div");
                    emptyMsg.textContent = searchTerm 
                        ? "没有找到匹配的模块" 
                        : "没有排除的模块";
                    emptyMsg.style.padding = "10px";
                    emptyMsg.style.color = "#888";
                    listContainer.appendChild(emptyMsg);
                    return;
                }

                filteredModules.forEach(module => {
                    const item = document.createElement("div");
                    item.style.display = "flex";
                    item.style.justifyContent = "space-between";
                    item.style.alignItems = "center";
                    item.style.padding = "8px";
                    item.style.borderBottom = "1px solid #333";
                    item.style.cursor = "pointer";
                    
                    // 如果是搜索结果，高亮匹配文本
                    const nameSpan = document.createElement("span");
                    if (searchTerm) {
                        const regex = new RegExp(`(${searchTerm})`, 'gi');
                        const parts = module.split(regex);
                        parts.forEach(part => {
                            const span = document.createElement("span");
                            if (part.toLowerCase() === searchTerm.toLowerCase()) {
                                span.style.backgroundColor = "#555";
                                span.style.borderRadius = "2px";
                                span.style.padding = "0 2px";
                            }
                            span.textContent = part;
                            nameSpan.appendChild(span);
                        });
                    } else {
                        nameSpan.textContent = module;
                    }

                    // 点击模块名称时滚动到视图中
                    item.onclick = () => {
                        item.scrollIntoView({ behavior: 'smooth', block: 'center' });
                        item.style.backgroundColor = '#444';
                        setTimeout(() => {
                            item.style.backgroundColor = 'transparent';
                        }, 1000);
                    };

                    const deleteBtn = document.createElement("button");
                    deleteBtn.textContent = "删除";
                    deleteBtn.className = "comfy-btn";
                    deleteBtn.style.padding = "2px 8px";
                    deleteBtn.style.fontSize = "12px";
                    deleteBtn.style.marginLeft = "10px";
                    deleteBtn.onclick = async (e) => {
                        e.stopPropagation(); // 防止触发item的点击事件
                        const index = modules.indexOf(module);
                        if (index > -1) {
                            modules.splice(index, 1);
                            await api.fetchApi('/hotreload/update_exclude_modules', {
                                method: 'POST',
                                headers: { 'Content-Type': 'application/json' },
                                body: JSON.stringify({ exclude_modules: modules })
                            });
                            renderModuleList(searchInput.value);
                        }
                    };

                    item.appendChild(nameSpan);
                    item.appendChild(deleteBtn);
                    listContainer.appendChild(item);
                });
            }

            // 添加搜索输入事件处理
            let searchTimeout;
            searchInput.addEventListener('input', (e) => {
                clearTimeout(searchTimeout);
                searchTimeout = setTimeout(() => {
                    renderModuleList(e.target.value.trim());
                }, 300); // 300ms防抖
            });

            renderModuleList();
            dialog.appendChild(listContainer);
            const inputContainer = document.createElement("div");
            inputContainer.style.display = "flex";
            inputContainer.style.flexDirection = "column";
            inputContainer.style.marginBottom = "20px";
            inputContainer.style.position = "relative";  // 为下拉菜单定位

            const input = document.createElement("input");
            input.type = "text";
            input.placeholder = "输入模块名称";
            input.style.flex = "1";
            input.style.padding = "8px";
            input.style.border = "1px solid #444";
            input.style.borderRadius = "4px";
            input.style.backgroundColor = "#333";
            input.style.color = "#eee";

            // 创建建议列表容器
            const suggestionsContainer = document.createElement("div");
            suggestionsContainer.style.position = "absolute";
            suggestionsContainer.style.top = "100%";
            suggestionsContainer.style.left = "0";
            suggestionsContainer.style.right = "0";
            suggestionsContainer.style.maxHeight = "200px";
            suggestionsContainer.style.overflowY = "auto";
            suggestionsContainer.style.backgroundColor = "#333";
            suggestionsContainer.style.border = "1px solid #444";
            suggestionsContainer.style.borderRadius = "4px";
            suggestionsContainer.style.zIndex = "1000";
            suggestionsContainer.style.display = "none";

            const inputWrapper = document.createElement("div");
            inputWrapper.style.display = "flex";
            inputWrapper.style.gap = "10px";

            const addBtn = document.createElement("button");
            addBtn.textContent = "添加";
            addBtn.className = "comfy-btn";
            addBtn.style.padding = "8px 15px";

            inputWrapper.appendChild(input);
            inputWrapper.appendChild(addBtn);
            inputContainer.appendChild(inputWrapper);
            inputContainer.appendChild(suggestionsContainer);

            // 更新建议列表
            function updateSuggestions(searchTerm) {
                suggestionsContainer.innerHTML = '';
                if (!searchTerm) {
                    suggestionsContainer.style.display = "none";
                    return;
                }

                const filteredModules = allAvailableModules
                    .filter(m => !modules.includes(m)) // 排除已添加的模块
                    .filter(m => m.toLowerCase().includes(searchTerm.toLowerCase()));

                if (filteredModules.length === 0) {
                    suggestionsContainer.style.display = "none";
                    return;
                }

                filteredModules.forEach(module => {
                    const suggestion = document.createElement("div");
                    suggestion.style.padding = "8px";
                    suggestion.style.cursor = "pointer";
                    suggestion.style.borderBottom = "1px solid #444";
                    suggestion.style.color = "#eee";

                    // 高亮匹配文本
                    const regex = new RegExp(`(${searchTerm})`, 'gi');
                    const parts = module.split(regex);
                    suggestion.innerHTML = parts.map(part => 
                        part.toLowerCase() === searchTerm.toLowerCase()
                            ? `<span style="background-color: #555; border-radius: 2px; padding: 0 2px;">${part}</span>`
                            : part
                    ).join('');

                    suggestion.onmouseover = () => {
                        suggestion.style.backgroundColor = "#444";
                    };
                    suggestion.onmouseout = () => {
                        suggestion.style.backgroundColor = "transparent";
                    };
                    suggestion.onclick = () => {
                        input.value = module;
                        suggestionsContainer.style.display = "none";
                    };

                    suggestionsContainer.appendChild(suggestion);
                });

                suggestionsContainer.style.display = "block";
            }

            // 添加输入事件监听
            let inputTimeout;
            input.addEventListener('input', (e) => {
                clearTimeout(inputTimeout);
                inputTimeout = setTimeout(() => {
                    updateSuggestions(e.target.value.trim());
                }, 200);
            });

            // 点击外部时隐藏建议列表
            document.addEventListener('click', (e) => {
                if (!inputContainer.contains(e.target)) {
                    suggestionsContainer.style.display = "none";
                }
            });

            // 更新添加按钮的点击事件
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
                    suggestionsContainer.style.display = "none";
                    renderModuleList(searchInput.value);
                }
            };

            // 更新输入框的回车事件
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
                        suggestionsContainer.style.display = "none";
                        renderModuleList(searchInput.value);
                    }
                }
            });

            dialog.appendChild(inputContainer);

            const buttonsContainer = document.createElement("div");
            buttonsContainer.style.display = "flex";
            buttonsContainer.style.justifyContent = "space-between";
            buttonsContainer.style.marginTop = "20px";
            const addAllBtn = document.createElement("button");
            addAllBtn.textContent = "添加所有模块";
            addAllBtn.className = "comfy-btn";
            addAllBtn.style.padding = "8px 20px";
            addAllBtn.onclick = async () => {
                try {
                    const response = await api.fetchApi('/hotreload/get_all_modules');
                    const data = await response.json();
                    const allModules = data.modules;
                    
                    const newModules = allModules.filter(m => !modules.includes(m));
                    if (newModules.length > 0) {
                        modules.push(...newModules);
                        await api.fetchApi('/hotreload/update_exclude_modules', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ exclude_modules: modules })
                        });
                        renderModuleList(searchInput.value);
                    }
                } catch (error) {
                    console.error('获取所有模块失败:', error);
                }
            };
            const closeBtn = document.createElement("button");
            closeBtn.textContent = "关闭";
            closeBtn.className = "comfy-btn";
            closeBtn.style.padding = "8px 20px";
            buttonsContainer.appendChild(addAllBtn);
            buttonsContainer.appendChild(closeBtn);
            dialog.appendChild(buttonsContainer);
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