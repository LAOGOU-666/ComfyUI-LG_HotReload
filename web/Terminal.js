import { app } from "../../scripts/app.js"
import { Util } from "./Util.js"


// Terminal
var TerminalTextVersion = 0
var TerminalLines = new Array()


// Register Extension
app.registerExtension({

    name: 'ComfyUI.HotReload.Terminal',

    // Setup
    async setup() {
        // Terminal
        Util.AddMessageListener("/hotreload.terminal.log", logTerminal)
        function logTerminal(event) {
            TerminalTextVersion++
            // Check for Clear
            if (event.detail.clear) {
                TerminalLines.length = 0
            }
            // Push Line
            let totalText = String(event.detail.text || "")
            TerminalLines.push(...(totalText.split("\n")))
            if (TerminalLines.length > 1024) {
                TerminalLines = TerminalLines.slice(TerminalLines.length - 1024, TerminalLines.length)
            }
            // Refresh all Terminal Nodes
            for (let i = 0; i < app.graph._nodes.length; i++) {
                var node = app.graph._nodes[i]
                if (node.type != "HotReload_Terminal") continue;
                node.onDrawForeground?.apply(node, [app.ctx, app.canvas]);
            }
        }

    },

    // Before Node Def
    async beforeRegisterNodeDef(nodeType, nodeData, app) {

        switch (nodeData.name) {
            case "HotReload_Terminal":
                Register_Terminal(nodeType)
                break;
        }

        // Terminal
        function Register_Terminal(nodeType) {
            // Create
            const onNodeCreated = nodeType.prototype.onNodeCreated;
            nodeType.prototype.onNodeCreated = async function () {
                const me = onNodeCreated?.apply(this);
                var textArea = Util.AddReadOnlyTextArea(this, "terminal", "");
                textArea.element.style.backgroundColor = "#000000ff"
                textArea.element.style.fontColor = "#ffffffff"
                let clearBtn = Util.AddButtonWidget(this, "Clear", clearButtonCallback)
                clearBtn.width = 128
                this.terminalVersion = -1
                return me;
            }
            function clearButtonCallback() {
                TerminalLines.length = 0
                TerminalTextVersion++
            }
            // Draw
            const onDrawForeground = nodeType.prototype.onDrawForeground;
            nodeType.prototype.onDrawForeground = function (ctx, graphcanvas) {
                if (this.terminalVersion == TerminalTextVersion) {
                    return onDrawForeground?.apply(this);
                }
                this.terminalVersion = TerminalTextVersion
                for (var i = 0; i < this.widgets.length; i++) {
                    var wid = this.widgets[i];
                    if (wid.name != "terminal") continue;
                    Util.SetTextAreaContent(wid, TerminalLines.join("\n"))
                    Util.SetTextAreaScrollPos(wid, 1.0)
                    break;
                }
                return onDrawForeground?.apply(this);
            }
        }

        // Final
        return nodeType;
    },

});
