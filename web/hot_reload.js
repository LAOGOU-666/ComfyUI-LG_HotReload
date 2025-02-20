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
                    // 1. 保存所有现有节点的状态
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
                                properties: {...node.properties},
                                inputs: node.inputs?.map(i => ({...i})),
                                outputs: node.outputs?.map(o => ({...o})),
                                connections: {
                                    inputs: node.inputs?.map((input, slot) => 
                                        input.link != null ? {
                                            slot,
                                            target_id: app.graph.links[input.link].origin_id,
                                            target_slot: app.graph.links[input.link].origin_slot
                                        } : null).filter(x => x),
                                    outputs: node.outputs?.map((output, slot) => 
                                        output.links?.map(link => ({
                                            slot,
                                            target_id: app.graph.links[link].target_id,
                                            target_slot: app.graph.links[link].target_slot
                                        }))).flat().filter(x => x)
                                }
                            });
                        });
                    }

                    // 2. 只获取需要更新的节点的定义
                    for (const nodeClass of nodesToUpdate) {
                        const response = await api.fetchApi(`/object_info/${nodeClass}`);
                        const nodeData = await response.json();
                        if (nodeData && nodeData[nodeClass]) {
                            // 注册新的节点定义
                            app.registerNodeDef(nodeClass, nodeData[nodeClass]);
                            
                            // 更新现有节点的组件
                            const existingNodes = app.graph.findNodesByType(nodeClass);
                            existingNodes.forEach(node => {
                                if (node.widgets) {
                                    node.widgets.forEach(widget => {
                                        if (widget.type === "combo" && 
                                            nodeData[nodeClass]["input"]["required"][widget.name]) {
                                            widget.options.values = nodeData[nodeClass]["input"]["required"][widget.name][0];
                                        }
                                    });
                                }
                                // 刷新节点的组合框
                                node.refreshComboInNode?.(nodeData);
                            });
                        }
                    }
                    
                    // 3. 恢复节点状态
                    for (const state of savedStates.values()) {
                        const node = app.graph.getNodeById(state.id);
                        if (node) {
                            // 恢复基本属性
                            node.pos = state.pos;
                            node.size = state.size;
                            Object.assign(node.properties, state.properties);
                            
                            // 恢复部件状态
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
                            
                            // 恢复连接
                            state.connections.inputs.forEach(conn => {
                                const targetNode = app.graph.getNodeById(conn.target_id);
                                if (targetNode) {
                                    node.connect(conn.slot, targetNode, conn.target_slot);
                                }
                            });
                            
                            state.connections.outputs.forEach(conn => {
                                const targetNode = app.graph.getNodeById(conn.target_id);
                                if (targetNode) {
                                    node.connect(conn.slot, targetNode, conn.target_slot);
                                }
                            });
                        }
                    }
                    
                    // 4. 刷新画布
                    app.graph.setDirtyCanvas(true);
                    
                } catch (error) {
                    console.error("[HotReload] Failed to update nodes:", error);
                    console.error("[HotReload] Error details:", error.stack);
                }
            }
        });
    }
});