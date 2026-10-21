"use strict";
/*
 * note-curator — Obsidian 原生插件（预览版）。
 *
 * 与外部 Agent Skill 共用同一核心：所有能力通过调用
 * plugins/note-curator/skills/note-curator/scripts/ 下的 Python 脚本完成，
 * 走同一套 WritePlan 事务、画像、语言包与偏好状态。
 *
 * 安全约定：LLM API key 只存在本插件数据文件或进程环境变量，
 * 调用核心时通过 NC_LLM_API_KEY 环境变量传递，不写入 vault 内任何文件、
 * 不进入日志。建议用户优先配置环境变量。
 *
 * 保存事件：只把「用户改过的笔记路径」追加到待学习清单
 * （discovery），绝不自动学习；插件自身的写入会被过滤。
 */

const { Plugin, PluginSettingTab, Setting, Modal, Notice, ItemView,
        TFile } = require("obsidian");
const { spawn } = require("child_process");
const path = require("path");
const fs = require("fs");
const os = require("os");

const VIEW_TYPE = "note-curator-view";
const PLUGIN_VERSION = "2.4.0";

const DEFAULT_SETTINGS = {
  pythonCmd: "python",
  scriptsDir: "",
  curatorHome: "",
  llmBaseUrl: "",
  llmModel: "",
  llmApiKey: "",
  uiLanguage: "zh",
  register: "technical",
  lang: "zh",
  profilePath: "",
};

const I18N = {
  zh: {
    organize: "整理当前笔记",
    learn: "学习这次修改",
    prefs: "偏好管理",
    writelog: "写入日志",
    check: "检查配置",
    preview: "写入预览",
    apply: "应用写入",
    cancel: "取消",
    applied: "已写入。",
    applyConflict: "写入被拒绝：预览后文件已被修改，未覆盖任何内容。",
    noActive: "请先打开一篇笔记。",
    notConfigured: "请先在设置中填写脚本目录（scriptsDir）。",
    generating: "正在生成草稿…",
    generateFailed: "生成失败：",
    learnNoDiff: "没有新的改稿差异。",
    learnRecorded: "差异已记录，请在面板中确认候选。",
    prefsTitle: "个人偏好",
    disable: "停用",
    enable: "启用",
    viewTitle: "笔记管家",
    pendingQueue: "待学习清单（仅发现，不自动学习）",
    settingsScripts: "核心脚本目录",
    settingsScriptsDesc: "skills/note-curator/scripts 的绝对路径。",
    settingsPython: "Python 命令",
    settingsHome: "数据目录（NOTE_CURATOR_HOME，可留空）",
    settingsKey: "LLM API key",
    settingsKeyDesc: "存储在本插件数据文件；更推荐留空并用环境变量 NC_LLM_API_KEY。",
    settingsBase: "LLM Base URL（OpenAI 兼容）",
    settingsModel: "LLM 模型名",
    settingsLang: "输出语言",
  },
  en: {
    organize: "Organize current note",
    learn: "Learn this edit",
    prefs: "Preferences",
    writelog: "Write log",
    check: "Check setup",
    preview: "Write preview",
    apply: "Apply write",
    cancel: "Cancel",
    applied: "Written.",
    applyConflict: "Write rejected: the file changed after preview; nothing overwritten.",
    noActive: "Open a note first.",
    notConfigured: "Set scriptsDir in settings first.",
    generating: "Generating draft…",
    generateFailed: "Generation failed: ",
    learnNoDiff: "No new edit diff.",
    learnRecorded: "Diff recorded; confirm candidates in the panel.",
    prefsTitle: "Preferences",
    disable: "Disable",
    enable: "Enable",
    viewTitle: "Note Curator",
    pendingQueue: "Pending learning (discovery only)",
    settingsScripts: "Core scripts directory",
    settingsScriptsDesc: "Absolute path to skills/note-curator/scripts.",
    settingsPython: "Python command",
    settingsHome: "Data dir (NOTE_CURATOR_HOME, optional)",
    settingsKey: "LLM API key",
    settingsKeyDesc: "Stored in this plugin's data file; prefer leaving empty and using env NC_LLM_API_KEY.",
    settingsBase: "LLM Base URL (OpenAI compatible)",
    settingsModel: "LLM model name",
    settingsLang: "Output language",
  },
};

/* ---------- 核心调用桥：所有能力经同一入口 ---------- */

class NCBridge {
  constructor(settings) {
    this.settings = settings;
  }

  env() {
    const env = Object.assign({}, process.env);
    if (this.settings.curatorHome) {
      env.NOTE_CURATOR_HOME = this.settings.curatorHome;
    }
    if (this.settings.llmApiKey) {
      env.NC_LLM_API_KEY = this.settings.llmApiKey;
    }
    if (this.settings.llmBaseUrl) {
      env.NC_LLM_BASE_URL = this.settings.llmBaseUrl;
    }
    if (this.settings.llmModel) {
      env.NC_LLM_MODEL = this.settings.llmModel;
    }
    return env;
  }

  run(script, args) {
    const self = this;
    return new Promise(function (resolve) {
      const proc = spawn(self.settings.pythonCmd,
        [path.join(self.settings.scriptsDir, script)].concat(args),
        { env: self.env() });
      let stdout = "";
      let stderr = "";
      proc.stdout.on("data", function (d) { stdout += d; });
      proc.stderr.on("data", function (d) { stderr += d; });
      proc.on("error", function (err) {
        resolve({ code: -1, stdout: "", stderr: String(err) });
      });
      proc.on("close", function (code) {
        resolve({ code: code, stdout: stdout, stderr: stderr });
      });
    });
  }

  async json(script, args) {
    const res = await this.run(script, args.concat(["--json"]));
    try {
      return { code: res.code, data: JSON.parse(res.stdout), stderr: res.stderr };
    } catch (e) {
      return { code: res.code, data: null, stderr: res.stderr || String(e) };
    }
  }
}

/* ---------- 预览弹窗：展示计划 → 应用/取消 ---------- */

class PreviewModal extends Modal {
  constructor(app, bridge, t, plan) {
    super(app);
    this.bridge = bridge;
    this.t = t;
    this.plan = plan;
  }

  onOpen() {
    const { contentEl } = this;
    contentEl.createEl("h3", { text: this.t.preview });
    const info = contentEl.createEl("pre");
    info.setText(JSON.stringify({
      run_id: this.plan.run_id,
      op: this.plan.op,
      target: this.plan.target,
      content_hash: this.plan.content_hash,
    }, null, 2));
    const body = contentEl.createEl("pre");
    body.setText((this.plan.content || "").slice(0, 2000));
    const buttons = contentEl.createDiv();
    const applyBtn = buttons.createEl("button", { text: this.t.apply });
    const cancelBtn = buttons.createEl("button", { text: this.t.cancel });
    const self = this;
    applyBtn.onclick = async function () {
      const res = await self.bridge.json("write_note.py",
        ["apply", "--run", self.plan.run_id]);
      if (res.code === 0) {
        new Notice(self.t.applied);
      } else if (res.code === 3) {
        new Notice(self.t.applyConflict);
      } else {
        new Notice((res.data && res.data.error && res.data.error.message)
          || res.stderr || "error");
      }
      self.close();
    };
    cancelBtn.onclick = function () { self.close(); };
  }

  onClose() {
    this.contentEl.empty();
  }
}

/* ---------- 学习弹窗：差异 + 候选确认 ---------- */

class LearnModal extends Modal {
  constructor(app, bridge, t, diffResult) {
    super(app);
    this.bridge = bridge;
    this.t = t;
    this.result = diffResult;
  }

  onOpen() {
    const { contentEl } = this;
    contentEl.createEl("h3", { text: this.t.learn });
    const self = this;
    const ev = this.result;
    const head = contentEl.createDiv();
    head.createEl("div", { text: "event: " + ev.event_id });
    const cats = Object.keys(ev.categories || {})
      .map(function (k) { return k + " x" + ev.categories[k]; }).join(", ");
    head.createEl("div", { text: "categories: " + cats });
    const candidates = ev.candidates || [];
    if (!candidates.length) {
      contentEl.createEl("p", { text: this.t.learnNoDiff });
    }
    candidates.forEach(function (c) {
      const row = contentEl.createDiv();
      row.createEl("div", { text: "[" + c.type + "] " + (c.why || "") });
      const confirmBtn = row.createEl("button", { text: "✓" });
      confirmBtn.onclick = async function () {
        await self.bridge.json("learn_edit.py",
          ["confirm", "--profile", self.result.profile || "",
           "--candidate", c.candidate_id]);
        row.setStyle("opacity", "0.4");
      };
    });
    contentEl.createEl("button", { text: "close" })
      .onclick = function () { self.close(); };
  }

  onClose() {
    this.contentEl.empty();
  }
}

/* ---------- 侧栏视图：预览状态 + 待学习清单 ---------- */

class CuratorView extends ItemView {
  constructor(leaf, plugin) {
    super(leaf);
    this.plugin = plugin;
  }

  getViewType() { return VIEW_TYPE; }
  getDisplayText() { return "note-curator"; }
  getIcon() { return "bookmark"; }

  async onOpen() {
    const container = this.contentEl;
    container.empty();
    const t = this.plugin.t();
    container.createEl("h4", { text: t.viewTitle });
    const pendingPath = path.join(
      this.plugin.bridge.settings.curatorHome || path.join(os.homedir(), ".note-curator"),
      "pending-learning.jsonl");
    container.createEl("div", { text: t.pendingQueue });
    const list = container.createEl("pre");
    try {
      const raw = fs.readFileSync(pendingPath, "utf-8");
      list.setText(raw.trim().split("\n").slice(-20).join("\n"));
    } catch (e) {
      list.setText("（空）");
    }
    const refresh = container.createEl("button", { text: "refresh" });
    const self = this;
    refresh.onclick = function () { self.onOpen(); };
  }

  onClose() {
    this.contentEl.empty();
  }
}

/* ---------- 设置页 ---------- */

class CuratorSettingTab extends PluginSettingTab {
  constructor(app, plugin) {
    super(app, plugin);
    this.plugin = plugin;
  }

  display() {
    const { containerEl } = this;
    containerEl.empty();
    const t = this.plugin.t();
    const s = this.plugin.settings;

    new Setting(containerEl)
      .setName(t.settingsScripts)
      .setDesc(t.settingsScriptsDesc)
      .addText(function (text) {
        text.setValue(s.scriptsDir).onChange(function (v) {
          s.scriptsDir = v.trim();
          self.save();
        });
      });
    const self = this;
    function bindText(name, key, desc) {
      new Setting(containerEl).setName(name).setDesc(desc || "")
        .addText(function (text) {
          text.setValue(String(s[key])).onChange(function (v) {
            s[key] = v.trim();
            self.save();
          });
        });
    }
    bindText(t.settingsPython, "pythonCmd");
    bindText(t.settingsHome, "curatorHome");
    bindText(t.settingsBase, "llmBaseUrl");
    bindText(t.settingsModel, "llmModel");
    const keySetting = new Setting(containerEl)
      .setName(t.settingsKey)
      .setDesc(t.settingsKeyDesc)
      .addText(function (text) {
        text.inputEl.type = "password";
        text.setValue(s.llmApiKey).onChange(function (v) {
          s.llmApiKey = v;
          self.save();
        });
      });
    new Setting(containerEl).setName(t.settingsLang)
      .addDropdown(function (dd) {
        dd.addOption("zh", "中文");
        dd.addOption("en", "English");
        dd.setValue(s.lang).onChange(function (v) {
          s.lang = v;
          self.save();
        });
      });
  }
}

/* ---------- 插件主体 ---------- */

class NoteCuratorPlugin extends Plugin {
  async onload() {
    this.settings = Object.assign({}, DEFAULT_SETTINGS,
      await this.loadData());
    this.bridge = new NCBridge(this.settings);
    this.t = this.i18n();
    this.lastPluginWrite = "";

    this.addRibbonIcon("bookmark", this.t.viewTitle,
      this.openView.bind(this));
    this.addSettingTab(new CuratorSettingTab(this.app, this));

    this.addCommand({
      id: "check-setup",
      name: this.t.check,
      callback: this.cmdCheckSetup.bind(this),
    });
    this.addCommand({
      id: "organize-current",
      name: this.t.organize,
      callback: this.cmdOrganize.bind(this),
    });
    this.addCommand({
      id: "learn-edit",
      name: this.t.learn,
      callback: this.cmdLearn.bind(this),
    });
    this.addCommand({
      id: "preferences",
      name: this.t.prefs,
      callback: this.cmdPrefs.bind(this),
    });
    this.addCommand({
      id: "write-log",
      name: this.t.writelog,
      callback: this.cmdLog.bind(this),
    });

    this.registerEvent(this.app.vault.on("modify", this.onModify.bind(this)));
  }

  i18n() {
    return I18N[this.settings.uiLanguage === "en" ? "en" : "zh"];
  }

  ready() {
    return !!this.settings.scriptsDir;
  }

  activeFile() {
    const view = this.app.workspace.getActiveViewOfType(ItemView);
    const file = this.app.workspace.getActiveFile();
    return file instanceof TFile ? file : null;
  }

  absPath(file) {
    return path.join(this.app.vault.adapter.getBasePath(), file.path);
  }

  profileArg() {
    return this.settings.profilePath ? ["--profile", this.settings.profilePath] : [];
  }

  async cmdCheckSetup() {
    if (!this.ready()) { new Notice(this.t.notConfigured); return; }
    const res = await this.bridge.json("check_setup.py", []);
    const d = res.data || {};
    new Notice("note-curator: " + (d.message || ("status=" + d.status)));
  }

  async cmdOrganize() {
    const file = this.activeFile();
    if (!file) { new Notice(this.t.noActive); return; }
    if (!this.ready()) { new Notice(this.t.notConfigured); return; }
    new Notice(this.t.generating);
    const abs = this.absPath(file);
    const tmpDoc = path.join(os.tmpdir(), "nc-source-" + Date.now() + ".json");
    const sdoc = await this.bridge.json("source_document.py",
      ["from-file", abs, "--out", tmpDoc]);
    const draftPath = path.join(os.tmpdir(), "nc-draft-" + Date.now() + ".md");
    const gen = await this.bridge.json("model_generate.py",
      ["--source-doc", tmpDoc, "--register", this.settings.register,
       "--lang", this.settings.lang, "--title", file.basename,
       "--out", draftPath].concat(this.profileArg()));
    if (gen.code !== 0 || !gen.data || !gen.data.ok) {
      new Notice(this.t.generateFailed + ((gen.data && gen.data.error) || gen.stderr));
      return;
    }
    const dir = path.dirname(file.path).replace(/\\/g, "/");
    const planRes = await this.bridge.json("write_note.py",
      ["new", "--vault", this.app.vault.adapter.getBasePath(),
       "--dir", dir === "/" ? "00 Inbox" : dir,
       "--title", file.basename + " · 整理", "--file", draftPath]);
    if (planRes.code === 0 && planRes.data && planRes.data.run_id) {
      this.lastPluginWrite = planRes.data.target;
      new PreviewModal(this.app, this.bridge, this.t, planRes.data).open();
    } else {
      new Notice((planRes.data && planRes.data.error
        && planRes.data.error.message) || planRes.stderr || "error");
    }
  }

  async cmdLearn() {
    const file = this.activeFile();
    if (!file) { new Notice(this.t.noActive); return; }
    if (!this.ready()) { new Notice(this.t.notConfigured); return; }
    const abs = this.absPath(file);
    const args = ["diff", "--note", abs].concat(this.profileArg());
    const res = await this.bridge.json("learn_edit.py", args);
    if (res.code === 2) {
      new Notice(this.t.learnNoDiff);
      return;
    }
    if (res.code === 0 && res.data) {
      res.data.profile = this.settings.profilePath;
      new LearnModal(this.app, this.bridge, this.t, res.data).open();
    } else {
      new Notice(res.stderr || "error");
    }
  }

  async cmdPrefs() {
    if (!this.ready()) { new Notice(this.t.notConfigured); return; }
    const res = await this.bridge.json("preferences.py",
      ["list"].concat(this.profileArg()));
    const modal = new Modal(this.app);
    modal.contentEl.createEl("h3", { text: this.t.prefsTitle });
    const pre = modal.contentEl.createEl("pre");
    const prefs = (res.data && res.data.preferences) || [];
    pre.setText(prefs.map(function (p) {
      return p.id + "  [" + p.status + (p.enabled === false ? "/off" : "") + "] "
        + p.type + "  " + JSON.stringify(p.value || {}).slice(0, 80);
    }).join("\n") || "（空）");
    modal.open();
  }

  async cmdLog() {
    if (!this.ready()) { new Notice(this.t.notConfigured); return; }
    const res = await this.bridge.json("write_note.py", ["log"]);
    const modal = new Modal(this.app);
    modal.contentEl.createEl("h3", { text: this.t.writelog });
    const pre = modal.contentEl.createEl("pre");
    pre.setText(res.stdout || "（空）");
    modal.open();
  }

  onModify(file) {
    // 只发现变化，过滤插件自身写入，绝不自动学习
    if (!(file instanceof TFile)) return;
    if (this.lastPluginWrite && file.path === this.lastPluginWrite) return;
    try {
      const home = this.bridge.settings.curatorHome
        || path.join(os.homedir(), ".note-curator");
      const pending = path.join(home, "pending-learning.jsonl");
      fs.mkdirSync(path.dirname(pending), { recursive: true });
      fs.appendFileSync(pending, JSON.stringify({
        path: file.path, at: new Date().toISOString(),
      }) + "\n", "utf-8");
    } catch (e) { /* 记录失败不影响编辑 */ }
  }

  async openView() {
    const leaf = this.app.workspace.getRightLeaf(false);
    await leaf.setViewState({ type: VIEW_TYPE, active: true });
    this.app.workspace.revealLeaf(leaf);
  }

  onunload() {
    /* 状态都在磁盘（plans/log/profile），关闭侧栏或卸载不丢数据 */
  }

  async saveSettings() {
    await this.saveData(this.settings);
  }
}

module.exports = NoteCuratorPlugin;
