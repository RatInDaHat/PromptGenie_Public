import { app } from "../../scripts/app.js";

console.log("[PromptGenie] extension loading");

// ── I2V Source: update current_index widget after each run ────────────────────
app.registerExtension({
    name: "PromptGenie.I2VSource",
    async nodeCreated(node) {
        if (node.comfyClass !== "PromptGenieI2VSource") return;

        const orig = node.onExecuted?.bind(node);
        node.onExecuted = function (message) {
            orig?.(message);
            if (message?.current_index !== undefined) {
                const w = this.widgets?.find(w => w.name === "current_index");
                if (w) {
                    w.value = message.current_index[0];
                    app.graph.setDirtyCanvas(true);
                }
            }
        };
    },
});

// ── Folder Picker: Browse button opening a server-side folder dialog ──────────
app.registerExtension({
    name: "PromptGenie.FolderPicker",

    beforeRegisterNodeDef(nodeType, nodeData) {
        if (nodeData.name !== "PromptGenieFolderPicker") return;

        const orig = nodeType.prototype.onNodeCreated;
        nodeType.prototype.onNodeCreated = function () {
            orig?.apply(this, arguments);
            _pgAddBrowse(this);
        };
    },

    nodeCreated(node) {
        if (node.comfyClass !== "PromptGenieFolderPicker") return;
        _pgAddBrowse(node);
    },
});

function _pgAddBrowse(node) {
    if (node._pgBrowseAdded) return;
    node._pgBrowseAdded = true;

    const btn = node.addWidget(
        "button", "pg_browse", "",
        async () => {
            try {
                const resp = await fetch("/promptgenie/browse_folder");
                const { path } = await resp.json();
                if (path) {
                    const w = node.widgets?.find(w => w.name === "folder_path");
                    if (w) {
                        w.value = path;
                        app.graph.setDirtyCanvas(true, true);
                    }
                }
            } catch (e) {
                console.error("[PromptGenie] browse_folder error:", e);
            }
        },
        { serialize: false, canvasOnly: true }
    );
    btn.label = "Browse...";
    node.setSize(node.computeSize());
}
