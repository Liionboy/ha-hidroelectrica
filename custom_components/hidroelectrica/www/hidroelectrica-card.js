class HidroelectricaCard extends HTMLElement {
  setConfig(config) {
    this._config = { title: "Hidroelectrica", ...config };
    this._cache = this._cache || {};
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

  _payableAmount() {
    // 1) Prefer sold_factura attributes (de obicei cele mai precise)
    const sold = this._pick("sold_factura");
    if (sold?.attributes) {
      const val =
        sold.attributes["Sold"] ||
        sold.attributes["Suma ultimei facturi"] ||
        sold.attributes["Total neachitat"] ||
        sold.attributes["De plată"] ||
        sold.attributes["De plata"] ||
        sold.attributes["total_neachitat"];
      if (val && String(val).trim() !== "") return val;
    }

    // 2) Fallback: factura_restanta
    const entries = Object.entries(this._hass.states || {}).filter(([id]) =>
      id.startsWith("sensor.hidroelectrica_")
    );
    for (const [, st] of entries) {
      const attrs = st.attributes || {};
      if (attrs["Total neachitat"]) return attrs["Total neachitat"];
      if (attrs["De plată"]) return attrs["De plată"];
      if (attrs["De plata"]) return attrs["De plata"];
      if (attrs["total_neachitat"]) return attrs["total_neachitat"];
    }

    return "-";
  }

  _render() {
    if (!this._hass) return;
    const keep = (key, value) => {
      const ok = value !== undefined && value !== null && String(value).trim() !== "" && String(value).trim() !== "-";
      if (ok) {
        this._cache[key] = value;
        return value;
      }
      return this._cache[key] || "-";
    };

    const sold = this._pick("sold") || this._pick("sold_factura");
    const restanta = this._pick("factura_restanta");
    const totalNeachitat = this._payableAmount();
    const soldAttrs = sold?.attributes || {};
    const restAttrs = restanta?.attributes || {};
    const soldAmount = soldAttrs["Sold"] || soldAttrs["Suma ultimei facturi"] || "-";
    const soldStatus = soldAttrs["Status"] || sold?.state || "-";
    const soldDue = soldAttrs["Data scadenței"] || soldAttrs["Data scadentei"] || "-";
    const lastIssued = keep("lastIssued", restAttrs["Ultima factură emisă"]);
    const lastType = keep("lastType", restAttrs["Tip"]);
    const lastDue = keep("lastDue", restAttrs["Scadentă"] || restAttrs["Scadenta"]);
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
            <div><span>Sold</span><strong>${soldAmount}</strong></div>
            <div><span>Status</span><strong>${soldStatus}</strong></div>
            <div><span>Facturi curente (de plată)</span><strong>${totalNeachitat}</strong></div>
            <div><span>Scadență</span><strong>${soldDue}</strong></div>
            <div><span>Ultima factură emisă</span><strong>${lastIssued}</strong></div>
            <div><span>Tip factură</span><strong>${lastType}</strong></div>
            <div><span>Scadență (ultima)</span><strong>${lastDue}</strong></div>
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
