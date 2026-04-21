class HidroelectricaCard extends HTMLElement {
  setConfig(config) {
    this._config = { title: "Hidroelectrica", ...config };
    if (!this.shadowRoot) this.attachShadow({ mode: "open" });
  }

  set hass(hass) {
    this._hass = hass;
    this._render();
  }

  getCardSize() { return 5; }

  _pick(namePart) {
    const entries = Object.entries(this._hass.states || {});
    const found = entries.find(([id]) => id.startsWith("sensor.hidroelectrica_") && id.includes(namePart));
    return found ? found[1] : null;
  }

  _render() {
    if (!this._hass) return;
    const sold = this._pick("sold") || this._pick("sold_factura");
    const restanta = this._pick("factura_restanta");
    const totalNeachitat = restanta?.attributes?.["Total neachitat"] || "-";
    const idxCons = this._pick("index_energie_electrica") || this._pick("index_consum");
    const idxProd = this._pick("index_energie_produsa") || this._pick("index_injectie");

    const archive = Object.entries(this._hass.states || {})
      .filter(([id]) => id.startsWith("sensor.hidroelectrica_") && id.includes("arhiva_"))
      .slice(0, 6)
      .map(([, st]) => `<li>${st.attributes?.friendly_name || "Arhivă"}: <b>${st.state}</b></li>`)
      .join("");

    this.shadowRoot.innerHTML = `
      <ha-card>
        <div class="wrap">
          <div class="title">${this._config.title}</div>
          <div class="grid">
            <div><span>Sold</span><strong>${sold?.state ?? "-"}</strong></div>
            <div><span>Restanță</span><strong>${restanta?.state ?? "-"}</strong></div>
            <div><span>Facturi curente (de plată)</span><strong>${totalNeachitat}</strong></div>
            <div><span>Index consum</span><strong>${idxCons?.state ?? "-"}</strong></div>
            <div><span>Index producție</span><strong>${idxProd?.state ?? "-"}</strong></div>
          </div>
          <div class="subtitle">Arhivă</div>
          <ul>${archive || "<li>Nu există date arhivă</li>"}</ul>
        </div>
      </ha-card>
      <style>
        .wrap{padding:14px}.title{font-size:16px;font-weight:700;margin-bottom:8px}
        .grid{display:grid;grid-template-columns:1fr 1fr;gap:8px}
        .grid div{background:var(--secondary-background-color);border-radius:10px;padding:8px}
        .grid span{font-size:12px;color:var(--secondary-text-color);display:block}
        .grid strong{font-size:14px}
        .subtitle{margin-top:10px;font-size:13px;font-weight:600}
        ul{margin:6px 0 0;padding-left:18px;font-size:12px}
      </style>
    `;
  }
}
customElements.define("hidroelectrica-card", HidroelectricaCard);
window.customCards = window.customCards || [];
window.customCards.push({type:"hidroelectrica-card",name:"Hidroelectrica Card",description:"Card pentru senzori Hidroelectrica"});
