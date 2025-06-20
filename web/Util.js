import { app } from "../../scripts/app.js"
import { api } from "../../scripts/api.js";


export class Util {


    static LogAllProperty(obj) {

        let result = `${typeof obj}:${obj.name}\n`

        let props = {}
        let current = obj;

        while (current) {
            // Get all own property names (including non-enumerable ones)
            const properties = Object.getOwnPropertyNames(current);

            for (const prop of properties) {
                // Check if the property is a function and not already added
                result += `${prop}:${obj[prop]}\n`
            }


            // Move up the prototype chain
            current = Object.getPrototypeOf(current);
        }

        // Log
        console.log(result)

    }


    // Server
    static AddMessageListener(messagePath, handlerFunc) {
        api.addEventListener(messagePath, handlerFunc);
    }


    static SendPostMessage(messagePath, data) {
        const body = new FormData();
        var keys = Object.keys(data);
        for (var i = 0; i < keys.length; i++) {
            var key = keys[i]
            body.append(key, data[key]);
        }
        return api.fetchApi(messagePath, { method: "POST", body, });
    }


    static SendGetMessage(messagePath) {
        return api.fetchApi(messagePath, { method: "GET", });
    }


    // Widget
    static SetTextAreaContent(widget, text) {
        widget.element.textContent = text
    }


    static SetTextAreaScrollPos(widget, pos01) {
        widget.element.scroll(0, widget.element.scrollHeight * pos01)
    }


    static AddReadOnlyTextArea(node, name, text, placeholder = "") {
        const inputEl = document.createElement("textarea");
        inputEl.className = "comfy-multiline-input";
        inputEl.placeholder = placeholder
        inputEl.spellcheck = false
        inputEl.readOnly = true
        inputEl.textContent = text
        return node.addDOMWidget(name, "", inputEl, {
            serialize: false,
        });
    }


    static GetWidget(node, name) {
        for (var i = 0; i < node.widgets.length; i++) {
            var w = node.widgets[i]
            if (w.name == name) {
                return w;
            }
        }
        return null;
    }


    static AddButtonWidget(node, label, callback, value = null) {
        return node.addWidget("button", label, value, callback);
    }


    // Draw
    static DrawText(ctx, text, localX, localY, sizeAndFont = "18px serif") {
        ctx.font = sizeAndFont;
        ctx.fillText(text, localX, localY);
    }


    // Misc
    static SetClipBoard(text) {
        navigator.clipboard.writeText(text);
    }


    static ChangeFileExtension(fileName, newExt) {
        var pos = fileName.includes(".") ? fileName.lastIndexOf(".") : fileName.length
        var fileRoot = fileName.substr(0, pos)
        var output = `${fileRoot}.${newExt}`
        return output
    }


    // Format
    static FormatTimeInSecond(time, decimals = 2) {
        return `${(time / 1000.0).toFixed(decimals)}s`
    }


    static FormatByteSize(bytes, decimals) {
        // Reference: https://gist.github.com/zentala/1e6f72438796d74531803cc3833c039c
        if (bytes === 0) {
            return '0 B'
        }
        const k = 1024,
            dm = decimals || 2,
            sizes = ['Bytes', 'KB', 'MB', 'GB', 'TB', 'PB', 'EB', 'ZB', 'YB'],
            i = Math.floor(Math.log(bytes) / Math.log(k));
        return parseFloat((bytes / Math.pow(k, i)).toFixed(dm)) + ' ' + sizes[i];
    }



    //// String
    //this.addWidget("string", "string label", "default value", undefined, {
    //    serialize: false
    //});
    //
    //// Combo
    //this.outputTypeWidget = this.addWidget("combo", "output", "STRING", undefined, {
    //    values: ["INT", "FLOAT", "STRING", "BOOL", "*"],
    //    serialize: false,
    //});
    //
    //// Number
    //this.addWidget("number", "number label", 123123, undefined, {
    //    serialize: false,
    //});
    //
    //// Toggle
    //this.addWidget("toggle", "toggle name", true, undefined, {
    //    on: "on label",
    //    off: "off label",
    //    serialize: false,
    //});
    //
    //// Text
    //this.addWidget("text", "text label", "default value", undefined, {
    //    serialize: false,
    //});

}
