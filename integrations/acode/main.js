const PLUGIN_ID = "dev.qich.acode";
const COMMAND_ID = "qich.runCurrentFile";
const LANGUAGE_ID = "qich";
const ALPINE_HOME = "/data/user/0/com.foxdebug.acode/files/alpine/home";

const KEYWORDS = new Set([
  "fn", "let", "mut", "if", "else", "whl", "for", "in", "brk", "cnt",
  "rtrn", "mtch", "case", "enm", "struct", "use", "mod", "as", "pub",
  "try", "catch", "throw", "async", "await", "true", "false", "null",
  "and", "or", "not", "requires", "ensures"
]);
const TYPES = new Set(["str", "int", "float", "bool", "void", "list", "map", "Result", "Option"]);

class QichAcodePlugin {
  constructor() {
    this.runButton = null;
    this.terminalModule = null;
    this.editorLanguages = null;
    this.commands = null;
    this.modeRegistered = false;
    this.onSwitchFile = () => this.refreshActiveFile();
    this.onRenameFile = () => this.refreshActiveFile();
  }

  async init() {
    this.registerLanguage();
    this.commands = acode.require("commands");
    this.commands.addCommand({
      name: COMMAND_ID,
      description: "Run current Qich file",
      bindKey: { win: "Ctrl-Alt-R", linux: "Ctrl-Alt-R", mac: "Command-Alt-R" },
      exec: () => this.runCurrentFile()
    });

    this.setupRunButton();
    if (window.editorManager?.on) {
      editorManager.on("switch-file", this.onSwitchFile);
      editorManager.on("rename-file", this.onRenameFile);
    }
    this.refreshActiveFile();
  }

  registerLanguage() {
    try {
      this.editorLanguages = acode.require("editorLanguages");
      const cm = acode.require("codemirror");
      const languageApi = acode.require("@codemirror/language");
      const StreamLanguage = languageApi?.StreamLanguage || cm?.StreamLanguage;
      if (!this.editorLanguages?.register || !StreamLanguage?.define) {
        throw new Error("API CodeMirror language tidak tersedia di versi Acode ini.");
      }

      const mode = StreamLanguage.define({
        startState: () => ({ blockComment: false }),
        token: (stream, state) => {
          if (state.blockComment) {
            if (stream.skipTo("*/")) {
              stream.match("*/");
              state.blockComment = false;
            } else {
              stream.skipToEnd();
            }
            return "comment";
          }
          if (stream.eatSpace()) return null;
          if (stream.match("//")) {
            stream.skipToEnd();
            return "comment";
          }
          if (stream.match("/*")) {
            state.blockComment = true;
            return "comment";
          }
          const ch = stream.peek();
          if (ch === '"' || ch === "'" || ch === "`") {
            const quote = stream.next();
            while (!stream.eol()) {
              const current = stream.next();
              if (current === "\\") stream.next();
              else if (current === quote) break;
            }
            return "string";
          }
          if (stream.match(/^-?\d+(?:\.\d+)?(?:[eE][+-]?\d+)?/)) return "number";
          if (stream.match(/^(?:==|!=|<=|>=|=>|->|\+|-|\*|\/|%|=|<|>|!|\?|\||&)/)) return "operator";
          if (stream.match(/^[A-Za-z_][A-Za-z0-9_]*/)) {
            const word = stream.current();
            if (KEYWORDS.has(word)) return "keyword";
            if (TYPES.has(word)) return "typeName";
            if (stream.peek() === "(") return "function";
            if (/^[A-Z]/.test(word)) return "typeName";
            return "variableName";
          }
          stream.next();
          return null;
        }
      });

      this.editorLanguages.register(LANGUAGE_ID, ["qh"], "Qich", () => [mode]);
      this.modeRegistered = true;
    } catch (error) {
      console.warn("[Qich] Syntax highlighting belum dapat diaktifkan:", error);
      window.toast?.("Qich: highlighting butuh Acode dengan API CodeMirror terbaru.");
    }
  }

  setupRunButton() {
    this.runButton = document.createElement("span");
    this.runButton.className = "icon play_arrow";
    this.runButton.setAttribute("action", "run-qich");
    this.runButton.title = "Run Qich";
    this.runButton.setAttribute("role", "button");
    this.runButton.setAttribute("aria-label", "Run Qich");
    this.runButton.style.cursor = "pointer";
    this.runButton.onclick = () => this.runCurrentFile();
  }

  refreshActiveFile() {
    const file = window.editorManager?.activeFile;
    const isQich = !!file?.filename && file.filename.toLowerCase().endsWith(".qh");
    if (isQich && this.modeRegistered && file.setMode) {
      try { file.setMode(LANGUAGE_ID); } catch (error) { console.warn(error); }
    }
    if (this.runButton?.isConnected) this.runButton.remove();
    if (isQich) {
      const header = document.querySelector("#root header");
      if (header) header.insertBefore(this.runButton, header.lastChild);
    }
  }

  shellQuote(value) {
    return "'" + String(value).replace(/'/g, "'\\''") + "'";
  }

  getRunCommand(file) {
    const filename = String(file.filename || "main.qh").split(/[\\/]/).pop();
    const source = file.session?.getValue?.() ?? "";
    const uri = typeof file.uri === "string" ? file.uri : "";
    const isSavedFile = !file.isUnsaved && uri.startsWith("file://");

    if (isSavedFile) {
      let path = decodeURIComponent(uri.replace(/^file:\/\//, ""));
      if (path.startsWith(ALPINE_HOME)) {
        const relative = path.slice(ALPINE_HOME.length);
        const safeRelative = relative.replace(/(["\\$\x60])/g, "\\$1");
        return `qh run "$HOME${safeRelative}"`;
      }
      return `qh run ${this.shellQuote(path)}`;
    }

    const tempPath = `/tmp/qich-${Date.now()}-${filename.replace(/[^A-Za-z0-9._-]/g, "_")}`;
    const delimiter = `QICH_SOURCE_${Date.now()}`;
    return `cat > ${this.shellQuote(tempPath)} <<'${delimiter}'\r${source.replace(/\r/g, "").split("\n").join("\r")}\r${delimiter}\rqh run ${this.shellQuote(tempPath)}`;
  }

  async runCurrentFile() {
    const file = window.editorManager?.activeFile;
    if (!file?.filename || !file.filename.toLowerCase().endsWith(".qh")) {
      window.toast?.("Buka file .qh dulu.");
      return;
    }
    try {
      this.terminalModule = this.terminalModule || acode.require("terminal");
      const term = await this.terminalModule.create({ name: "Qich", theme: "dark" });
      term.file?.makeActive?.();
      this.terminalModule.write(term.id, "clear\r");
      const command = this.getRunCommand(file);
      this.terminalModule.write(term.id, command + "\r");
    } catch (error) {
      console.error("[Qich] Gagal menjalankan file:", error);
      window.toast?.("Terminal Acode belum siap. Buka Menu → Terminal dan selesaikan setup, lalu coba lagi.");
    }
  }

  destroy() {
    if (this.runButton) {
      this.runButton.onclick = null;
      this.runButton.remove();
    }
    if (window.editorManager?.off) {
      editorManager.off("switch-file", this.onSwitchFile);
      editorManager.off("rename-file", this.onRenameFile);
    }
    try { this.commands?.removeCommand(COMMAND_ID); } catch (_) {}
    try { if (this.modeRegistered) this.editorLanguages?.unregister(LANGUAGE_ID); } catch (_) {}
  }
}

if (window.acode) {
  const plugin = new QichAcodePlugin();
  acode.setPluginInit(PLUGIN_ID, async () => plugin.init());
  acode.setPluginUnmount(PLUGIN_ID, () => plugin.destroy());
}
