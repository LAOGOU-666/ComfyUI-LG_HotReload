import { api } from "../../scripts/api.js";


export class Util {

    // Server
    static AddMessageListener(messagePath, handlerFunc) {
        api.addEventListener(messagePath, handlerFunc);
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

    static AddButtonWidget(node, label, callback, value = null) {
        return node.addWidget("button", label, value, callback);
    }


}
