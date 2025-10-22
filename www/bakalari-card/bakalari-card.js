/* eslint-disable no-undef */
class BakalariCard extends HTMLElement {
  static getStubConfig() {
    return { entity: "sensor.bakalari_zpravy", title: "📬 Zprávy" };
  }

  constructor() {
    super();
    this._root = null;
    this._hass = null;
    this._stateObj = null;
    this._config = {
      title: "📬 Zprávy z Bakalářů",
      limit: 100,
      sort: "desc",
      show_search: true,
      show_only_unread: false,
      allow_html: true,
    };
    this._open = new Set();
    this._query = "";
    this._onlyUnread = false;
  }

  connectedCallback() {
    this._ensureRoot();
    this._render();
  }

  setConfig(config) {
    if (!config || !config.entity)
      throw new Error("bakalari-card: 'entity' je povinné");
    this._config = Object.assign({}, this._config, config);
    this._onlyUnread = !!this._config.show_only_unread;
    this._render();
  }

  set hass(hass) {
    this._hass = hass;
    this._stateObj = hass.states[this._config.entity];
    this._render();
  }

  getCardSize() {
    return 3;
  }

  /* ------------ infra ------------ */
  _ensureRoot() {
    if (this._root) return;
    this._root = this.attachShadow({ mode: "open" });
    this._root.innerHTML = `
      <style>
        :host { display:block; }
        ha-card { display:block; }
        .wrap { padding: 12px 16px; }
        .header { display:flex; align-items:center; justify-content:space-between; margin-bottom:8px; }
        .title { font-weight:600; font-size:1.1rem; }
        .tools { display:flex; gap:8px; align-items:center; }
        input.search {
          min-width:200px; border:1px solid var(--divider-color);
          background: var(--card-background-color); color: var(--primary-text-color);
          border-radius:8px; padding:6px 8px;
        }
        .list { display:flex; flex-direction:column; gap:8px; }
        .item { border:1px solid var(--divider-color); border-radius:12px; overflow:hidden; background: var(--card-background-color); }
        .row { display:flex; gap:10px; align-items:center; padding:10px 12px; cursor:pointer; }
        .bullet { width:8px; height:8px; border-radius:50%; background: var(--accent-color); opacity:.6; }
        .meta { display:flex; flex-direction:column; gap:2px; flex:1; min-width:0; }
        .titleline { font-weight:600; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
        .subline { color: var(--secondary-text-color); font-size:.9rem; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
        .date { color: var(--secondary-text-color); font-size:.85rem; }
        .body { padding:0 12px 12px 12px; display:none; }
        .item.open .body { display:block; }
        .attachments { margin-top:6px; }
        .attachments a { text-decoration:none; }
        .empty { color: var(--secondary-text-color); padding:8px 0; }
        .unreadOff .bullet { display:none; }
        .tag { font-size:.75rem; padding:2px 6px; border-radius:999px; border:1px solid var(--divider-color); color: var(--secondary-text-color); }
        .controls { display:flex; align-items:center; gap:10px; }
        .switch { display:flex; align-items:center; gap:6px; font-size:.9rem; color: var(--secondary-text-color); }
      </style>
      <ha-card>
        <div class="wrap">
          <div class="header">
            <div class="title"></div>
            <div class="tools">
              <div class="controls">
                <label class="switch">
                  <input type="checkbox" id="onlyUnread">
                  <span>Jen nepřečtené</span>
                </label>
              </div>
              <input class="search" id="search" placeholder="Hledat ve zprávách">
            </div>
          </div>
          <div id="body"></div>
        </div>
      </ha-card>
    `;
    // Delegated listener – no inline onclick
    this._root.addEventListener("click", (e) => {
      const path = e.composedPath ? e.composedPath() : [];
      const row = path.find((el) => el?.classList?.contains?.("row"));
      if (!row) return;
      const item = row.closest(".item");
      if (!item) return;
      this._toggle(item.dataset.id);
    });
    // Search / switch
    this._root.getElementById("search").addEventListener("input", (e) => {
      this._query = e.target.value || "";
      this._renderBody();
    });
    this._root.getElementById("onlyUnread").addEventListener("change", (e) => {
      this._onlyUnread = !!e.target.checked;
      this._renderBody();
    });
  }

  /* ------------ utils ------------ */
  _fmtDate(d) {
    if (!d) return "";
    try {
      const date =
        typeof d === "string" || typeof d === "number" ? new Date(d) : d;
      return date.toLocaleString(undefined, {
        year: "numeric",
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
      });
    } catch {
      return String(d);
    }
  }
  _escape(s) {
    return String(s ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;");
  }
  _linkify(text) {
    const esc = this._escape(text).replace(/\n/g, "<br>");
    return esc.replace(
      /\b(https?:\/\/[^\s<]+)/g,
      (m) =>
        `<a href="${m}" target="_blank" rel="noopener noreferrer">${m}</a>`,
    );
  }
  _filtered(messages) {
    let arr = Array.isArray(messages) ? messages.slice() : [];
    if (this._query) {
      const q = this._query.toLowerCase();
      arr = arr.filter(
        (m) =>
          (m.title || "").toLowerCase().includes(q) ||
          (m.sender || "").toLowerCase().includes(q) ||
          (m.text || "").toLowerCase().includes(q),
      );
    }
    if (this._onlyUnread) arr = arr.filter((m) => m.unread === true);
    const asc = (this._config.sort || "desc").toLowerCase() === "asc";
    arr.sort((a, b) => new Date(a.sent || 0) - new Date(b.sent || 0));
    if (!asc) arr.reverse();
    const limit = Number(this._config.limit || 0);
    if (limit > 0) arr = arr.slice(0, limit);
    return arr;
  }
  _toggle(id) {
    if (this._open.has(id)) this._open.delete(id);
    else this._open.add(id);
    this._renderBody();
  }

  _allowedUrl(href) {
    try {
      const u = new URL(href, window.location.href);
      return u.protocol === "http:" || u.protocol === "https:";
    } catch {
      return false;
    }
  }

  _sanitize(html) {
    // Safe reconstruction of allowed tags only
    const allowedTags = new Set([
      "B",
      "STRONG",
      "I",
      "EM",
      "U",
      "BR",
      "P",
      "UL",
      "OL",
      "LI",
      "CODE",
      "PRE",
      "A",
    ]);
    const doc = new DOMParser().parseFromString(
      String(html ?? ""),
      "text/html",
    );
    const out = [];

    const walk = (node) => {
      if (node.nodeType === Node.TEXT_NODE) {
        out.push(this._escape(node.nodeValue));
        return;
      }
      if (node.nodeType !== Node.ELEMENT_NODE) return;

      const tag = node.tagName;
      if (!allowedTags.has(tag)) {
        // nepovolený element – renderuj jen text uvnitř
        node.childNodes.forEach(walk);
        return;
      }

      if (tag === "A") {
        const href = node.getAttribute("href") || "";
        if (!this._allowedUrl(href)) {
          node.childNodes.forEach(walk);
          return;
        }
        out.push(
          `<a href="${this._escape(href)}" target="_blank" rel="noopener noreferrer">`,
        );
        node.childNodes.forEach(walk);
        out.push(`</a>`);
        return;
      }

      // samouzavírací BR
      if (tag === "BR") {
        out.push("<br>");
        return;
      }

      out.push(`<${tag.toLowerCase()}>`);
      node.childNodes.forEach(walk);
      out.push(`</${tag.toLowerCase()}>`);
    };

    // vezmeme jen body
    doc.body.childNodes.forEach(walk);
    return out.join("");
  }

  /* ------------ render ------------ */
  _render() {
    if (!this._root) return;
    this._root.querySelector(".title").textContent =
      this._config.title || "📬 Zprávy";
    const chk = this._root.getElementById("onlyUnread");
    if (chk) chk.checked = this._onlyUnread;
    this._renderBody();
  }

  _renderBody() {
    if (!this._root) return;
    const container = this._root.getElementById("body");
    const state = this._stateObj;

    if (!state) {
      container.innerHTML = `<div class="empty">Entita <b>${this._config.entity}</b> neexistuje.</div>`;
      return;
    }
    const messages = state.attributes?.messages || [];
    if (!Array.isArray(messages)) {
      container.innerHTML = `<div class="empty">Atribut <code>messages</code> není pole.</div>`;
      return;
    }

    const list = this._filtered(messages);
    if (!list.length) {
      container.innerHTML = `<div class="empty">Žádné zprávy k zobrazení.</div>`;
      return;
    }

    const unreadClass = list.some((m) => m.unread) ? "" : "unreadOff";
    const html = [
      `<div class="list ${unreadClass}">`,
      ...list.map((m, idx) => {
        const id = `${idx}-${m.sent ?? ""}-${m.title ?? ""}`.replace(
          /\s+/g,
          "_",
        );
        const open = this._open.has(id) ? " open" : "";
        const attachments = Array.isArray(m.attachments) ? m.attachments : [];

        // ↓↓↓ NOVÉ: bezpečné HTML, jinak linkify textu
        const textHtml = this._config.allow_html
          ? this._sanitize(m.html ?? m.text ?? "")
          : this._linkify(m.text || "");

        return `
          <div class="item${open}" data-id="${id}">
            <div class="row">
              <div class="bullet" style="${m.unread ? "" : "opacity:0.15;"}"></div>
              <div class="meta">
                <div class="titleline">${this._escape(m.title || "Bez předmětu")}</div>
                <div class="subline">${this._escape(m.sender || "Neznámý odesílatel")}</div>
              </div>
              <div class="date">${this._fmtDate(m.sent)}</div>
            </div>
            <div class="body">
              <div class="text">${textHtml}</div>
              ${
                attachments.length
                  ? `<div class="attachments">
                     <span class="tag">Přílohy</span>
                     <ul>
                       ${attachments
                         .map(
                           (a) => `
                         <li><a href="${a.url}" target="_blank" rel="noopener noreferrer">${this._escape(a.name || a.url)}</a></li>
                       `,
                         )
                         .join("")}
                     </ul>
                   </div>`
                  : ""
              }
            </div>
          </div>`;
      }),
      `</div>`,
    ].join("");

    container.innerHTML = html;
  }
}

if (!customElements.get("bakalari-card")) {
  customElements.define("bakalari-card", BakalariCard);
}
window.customCards = window.customCards || [];
window.customCards.push({
  type: "bakalari-card",
  name: "Bakalari Card",
  description:
    "Přehledná karta pro zprávy z Bakalářů (klikací, vyhledávání, přílohy).",
});
