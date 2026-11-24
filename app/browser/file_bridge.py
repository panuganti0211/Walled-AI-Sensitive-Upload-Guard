"""DOM File Bridge for Chromium page targets.

Injects event listeners for file inputs, drag-and-drop, clipboard pastes,
and FormData additions via Page.addScriptToEvaluateOnNewDocument.
Reads the actual selected file bytes locally using the standard HTML5 FileReader API
and bridges them to Python via a dual-channel mechanism:
  1. CDP Console API (Runtime.consoleAPICalled via console.debug('[WALLED_AI_BRIDGE]:...'))
     Guarantees instant delivery across all frames, already-loaded pages, and realms.
  2. CDP Runtime Binding (Runtime.bindingCalled via window.walled_ai_file_bridge)
     Provides native protocol binding delivery when available.
"""

BINDING_NAME = "walled_ai_file_bridge"
BRIDGE_PREFIX = "[WALLED_AI_BRIDGE]:"
DIAG_PREFIX = "[WALLED_AI_BRIDGE_DIAG]:"


class FileBridge:
    """Generates the JavaScript injection script and CDP parameters for the DOM file bridge."""

    BINDING_NAME = BINDING_NAME
    BRIDGE_PREFIX = BRIDGE_PREFIX
    DIAG_PREFIX = DIAG_PREFIX

    def generate_injection_script(self) -> str:
        """Return the self-executing JavaScript script that captures uploaded files."""
        js = f"""(function() {{
    const BINDING_NAME = '{BINDING_NAME}';
    const BRIDGE_PREFIX = '{BRIDGE_PREFIX}';
    const DIAG_PREFIX = '{DIAG_PREFIX}';
    const MAX_FILE_SIZE = 50 * 1024 * 1024; // 50MB ceiling

    function diagLog(stage, meta) {{
        try {{
            const msg = DIAG_PREFIX + JSON.stringify({{stage: stage, meta: meta || {{}}}});
            console.info(msg);
            if (typeof window[BINDING_NAME] === 'function') {{
                window[BINDING_NAME](msg);
            }}
        }} catch (e) {{}}
    }}

    diagLog('BRIDGE_SCRIPT_EVALUATING', {{url: window.location.href}});

    if (window.__walled_ai_file_bridge_installed) {{
        diagLog('BRIDGE_SCRIPT_ALREADY_INSTALLED', {{url: window.location.href}});
        return;
    }}
    window.__walled_ai_file_bridge_installed = true;

    diagLog('BRIDGE_SCRIPT_INJECTED', {{url: window.location.href}});

    const seenFiles = new Map();

    function sendBridgePayload(payload) {{
        const jsonStr = JSON.stringify(payload);
        diagLog('BRIDGE_PAYLOAD_SENT', {{file_id: payload.file_id, name: payload.name, size: payload.size, mime: payload.type}});

        // Channel 1: Console API (Always active, works on already-loaded pages and subframes)
        try {{
            console.debug(BRIDGE_PREFIX + jsonStr);
        }} catch (e) {{}}

        // Channel 2: Runtime Binding (if bound in global scope)
        if (typeof window[BINDING_NAME] === 'function') {{
            try {{
                window[BINDING_NAME](jsonStr);
            }} catch (e) {{}}
        }}
    }}

    function processFile(file) {{
        if (!file) return;
        const isFileLike = file instanceof Blob || (typeof file.size === 'number' && typeof file.name === 'string');
        if (!isFileLike) return;

        diagLog('FILE_METADATA_EXTRACTED', {{name: file.name || 'unnamed', size: file.size || 0, type: file.type || 'unknown'}});

        if (file.size > MAX_FILE_SIZE) {{
            diagLog('FILE_OVERSIZED', {{name: file.name, size: file.size}});
            sendBridgePayload({{
                file_id: 'fb_' + Date.now() + '_' + Math.random().toString(36).substr(2, 9),
                name: file.name || 'unnamed_upload',
                size: file.size || 0,
                type: file.type || 'application/octet-stream',
                last_modified: file.lastModified || 0,
                oversized: true,
                base64: ''
            }});
            return;
        }}

        const fileKey = (file.name || 'blob') + '_' + file.size + '_' + (file.lastModified || 0);
        const now = Date.now();
        const lastSeen = seenFiles.get(fileKey) || 0;
        if (now - lastSeen < 1000) return; // Debounce rapid duplicate reads within 1s
        seenFiles.set(fileKey, now);

        // Periodic pruning of debounce cache
        if (seenFiles.size > 200) {{
            for (const [k, t] of seenFiles.entries()) {{
                if (now - t > 60000) seenFiles.delete(k);
            }}
        }}

        const fileId = 'fb_' + now + '_' + Math.random().toString(36).substr(2, 9);
        const reader = new FileReader();

        diagLog('FILEREADER_STARTED', {{name: file.name || 'unnamed', size: file.size || 0}});

        reader.onload = function() {{
            try {{
                const result = reader.result;
                const commaIndex = typeof result === 'string' ? result.indexOf(',') : -1;
                const base64 = commaIndex !== -1 ? result.substring(commaIndex + 1) : result;
                diagLog('FILEREADER_COMPLETED', {{name: file.name || 'unnamed', base64_len: base64 ? base64.length : 0}});
                sendBridgePayload({{
                    file_id: fileId,
                    name: file.name || 'unnamed_upload',
                    size: file.size || 0,
                    type: file.type || 'application/octet-stream',
                    last_modified: file.lastModified || 0,
                    oversized: false,
                    base64: base64
                }});
            }} catch (e) {{
                diagLog('FILEREADER_ONLOAD_EXCEPTION', {{error: String(e)}});
            }}
        }};

        reader.onerror = function() {{
            try {{
                diagLog('FILEREADER_ERROR', {{name: file.name, error: reader.error ? String(reader.error) : 'unknown'}});
            }} catch (e) {{}}
        }};

        reader.readAsDataURL(file);
    }}

    function extractFiles(dataTransfer) {{
        if (!dataTransfer) return [];
        const files = [];
        if (dataTransfer.files && dataTransfer.files.length > 0) {{
            for (let i = 0; i < dataTransfer.files.length; i++) {{
                files.push(dataTransfer.files[i]);
            }}
        }} else if (dataTransfer.items && dataTransfer.items.length > 0) {{
            for (let i = 0; i < dataTransfer.items.length; i++) {{
                if (dataTransfer.items[i].kind === 'file') {{
                    const f = dataTransfer.items[i].getAsFile();
                    if (f) files.push(f);
                }}
            }}
        }}
        return files;
    }}

    function handleFileEvent(e) {{
        const target = (e.composedPath && e.composedPath().length > 0) ? e.composedPath()[0] : e.target;
        const targetTag = target ? (target.tagName || '') : '';
        const isFileInput = target && targetTag.toUpperCase() === 'INPUT' && target.type === 'file';
        const fileCount = isFileInput && target.files ? target.files.length : 0;

        diagLog('FILE_SELECTED_EVENT_RECEIVED', {{
            eventType: e.type,
            targetTag: targetTag,
            isFileInput: isFileInput,
            fileCount: fileCount
        }});

        if (isFileInput) {{
            const files = target.files;
            if (files && files.length > 0) {{
                for (let i = 0; i < files.length; i++) {{
                    processFile(files[i]);
                }}
            }}
        }}
    }}

    // 1. Hook file input change & input events (capture phase, with Shadow DOM support)
    window.addEventListener('change', handleFileEvent, true);
    document.addEventListener('change', handleFileEvent, true);
    window.addEventListener('input', handleFileEvent, true);
    document.addEventListener('input', handleFileEvent, true);

    // 2. Hook detached file inputs when clicked
    if (window.HTMLInputElement && HTMLInputElement.prototype && HTMLInputElement.prototype.click) {{
        const origClick = HTMLInputElement.prototype.click;
        HTMLInputElement.prototype.click = function() {{
            if (this && this.type === 'file') {{
                diagLog('HTMLINPUT_CLICK_INTERCEPTED', {{type: this.type}});
                this.addEventListener('change', function() {{
                    if (this.files && this.files.length > 0) {{
                        for (let i = 0; i < this.files.length; i++) {{
                            processFile(this.files[i]);
                        }}
                    }}
                }}, {{ once: true, capture: true }});
            }}
            return origClick.apply(this, arguments);
        }};
    }}

    // 3. Hook modern File System Access API (showOpenFilePicker)
    if (typeof window.showOpenFilePicker === 'function') {{
        const origShowPicker = window.showOpenFilePicker;
        window.showOpenFilePicker = async function() {{
            diagLog('SHOW_OPEN_FILE_PICKER_INVOKED', {{}});
            const handles = await origShowPicker.apply(this, arguments);
            try {{
                if (Array.isArray(handles)) {{
                    for (let i = 0; i < handles.length; i++) {{
                        if (handles[i] && handles[i].kind === 'file') {{
                            const f = await handles[i].getFile();
                            processFile(f);
                        }}
                    }}
                }}
            }} catch (err) {{}}
            return handles;
        }};
    }}

    // 4. Hook drag and drop events (capture phase)
    window.addEventListener('drop', function(e) {{
        const files = extractFiles(e.dataTransfer);
        if (files.length > 0) {{
            diagLog('DROP_EVENT_RECEIVED', {{fileCount: files.length}});
            for (let i = 0; i < files.length; i++) {{
                processFile(files[i]);
            }}
        }}
    }}, true);

    // 5. Hook clipboard paste events (e.g. pasted screenshots / images)
    window.addEventListener('paste', function(e) {{
        const files = extractFiles(e.clipboardData);
        if (files.length > 0) {{
            diagLog('PASTE_EVENT_RECEIVED', {{fileCount: files.length}});
            for (let i = 0; i < files.length; i++) {{
                processFile(files[i]);
            }}
        }}
    }}, true);

    // 6. Hook FormData.prototype.append for programmatic additions
    if (window.FormData && FormData.prototype && FormData.prototype.append) {{
        const origAppend = FormData.prototype.append;
        FormData.prototype.append = function(name, value, filename) {{
            if (value && (value instanceof Blob || (typeof value.size === 'number' && typeof value.name === 'string'))) {{
                diagLog('FORMDATA_APPEND_RECEIVED', {{fieldName: name, fileName: value.name || filename || 'blob'}});
                processFile(value);
            }}
            return origAppend.apply(this, arguments);
        }};
    }}

    diagLog('FILE_HOOKS_INSTALLED', {{
        hasInputClick: !!(window.HTMLInputElement && HTMLInputElement.prototype && HTMLInputElement.prototype.click),
        hasShowPicker: typeof window.showOpenFilePicker === 'function',
        hasFormData: !!(window.FormData && FormData.prototype && FormData.prototype.append)
    }});
}})();"""
        return js

    def get_cdp_add_script_params(self) -> dict:
        """Return parameters for CDP Page.addScriptToEvaluateOnNewDocument."""
        return {"source": self.generate_injection_script()}

    def get_cdp_evaluate_params(self) -> dict:
        """Return parameters for CDP Runtime.evaluate."""
        return {
            "expression": self.generate_injection_script(),
            "returnByValue": True,
        }
