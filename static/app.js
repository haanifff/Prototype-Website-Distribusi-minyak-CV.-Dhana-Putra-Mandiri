"use strict";
const toggle = document.querySelector("#toggle");
const nav = document.querySelector("#sidebar");
const backdrop = document.querySelector(".scrim");
if (toggle && nav) {
  const mobile = matchMedia("(max-width:760px)");

  function setMenu(open, restore = false) {
    document.body.classList.toggle("menu", open);
    toggle.setAttribute("aria-expanded", String(open));
    backdrop.hidden = !open;
    nav.inert = mobile.matches && !open;
    document.querySelector(".shell").inert = open;
    if (open) nav.querySelector("a").focus();
    else if (restore) toggle.focus();
  }
  toggle.addEventListener("click", () => setMenu(true));
  backdrop.addEventListener("click", () => setMenu(false, true));
  document.addEventListener("keydown", e => {
    if (e.key === "Escape" && !backdrop.hidden) setMenu(false, true);
  });
  mobile.addEventListener("change", () => setMenu(false));
  setMenu(false);
}
document.querySelector("#print")?.addEventListener("click", () => window.print());
const cashKind = document.querySelector("#id_kind");
if (cashKind && document.querySelector("#id_amount")) {
  function showCashFields() {
    const fields = {
      target: ["Transfer"],
      category: ["Beban", "Pendapatan lain"],
      ref: ["Cicilan", "Bayar pemasok", "Alokasi uang muka"],
      advance: ["Alokasi uang muka"],
      party: ["Uang muka"]
    };
    for (const [name, kinds] of Object.entries(fields)) {
      const field = document.querySelector("#id_" + name);
      field.closest("p").hidden = !kinds.includes(cashKind.value);
      if (field.closest("p").hidden) field.value = "";
    }
  }
  showCashFields();
  cashKind.addEventListener("change", showCashFields);
}
const lines = document.querySelector("#lines");
if (lines) {
  const priceTiers = JSON.parse(document.querySelector("#price-tiers")?.textContent || "[]");
  const rupiah = new Intl.NumberFormat("id-ID", {
    style: "currency",
    currency: "IDR",
    maximumFractionDigits: 0
  });

  function refreshTotals() {
    const target = document.querySelector("#draft-total");
    if (!target) return;
    let total = 0,
      complete = true;
    for (const line of lines.querySelectorAll(".lineform")) {
      const product = line.querySelector("[name=product]");
      const quantity = Number(line.querySelector("[name=qty]").value);
      const unit = product.selectedOptions[0]?.dataset.unit;
      const factor = Number(line.querySelector("[name=conversion]").selectedOptions[0]?.dataset.factor || 1);
      const units = quantity * factor;
      const tier = priceTiers.find(t => t.product_id === Number(product.value) && units >= t.minimum);
      const price = Number(line.querySelector("[name=price]").value || tier?.price || 0);
      const subtotal = units * price - Number(line.querySelector("[name=discount]").value);
      const valid = unit && units > 0 && price > 0 && subtotal >= 0;
      line.querySelector(".line-subtotal").textContent = valid ? units.toLocaleString("id-ID") + " " + unit + " × " + rupiah.format(price) + " · Subtotal " + rupiah.format(subtotal) : "Lengkapi produk, jumlah, harga, dan diskon yang sesuai.";
      if (valid) total += subtotal;
      else complete = false;
    }
    target.textContent = complete ? rupiah.format(total) : "—";
  }

  function units(line) {
    const id = line.querySelector("[name=product]").value;
    const select = line.querySelector("[name=conversion]");
    for (const option of select.options) option.hidden = Boolean(option.value && option.dataset.product !== id);
    select.value = "";
    select.options[0].textContent = line.querySelector("[name=product]").selectedOptions[0]?.dataset.unit || "Satuan dasar produk";
  }
  lines.addEventListener("change", event => {
    if (event.target.name === "product") units(event.target.closest(".lineform"));
    refreshTotals();
  });
  lines.addEventListener("input", refreshTotals);
  document.querySelector("#addline").addEventListener("click", () => {
    const copy = lines.querySelector(".lineform").cloneNode(true);
    for (const input of copy.querySelectorAll("input,select")) input.value = input.name === "discount" ? "0" : "";
    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "secondary";
    remove.textContent = "Hapus baris";
    remove.onclick = () => {
      copy.remove();
      refreshTotals();
    };
    copy.append(remove);
    lines.append(copy);
    units(copy);
    refreshTotals();
  });
  units(lines.querySelector(".lineform"));
  document.querySelector("#draft-form").addEventListener("submit", event => {
    event.submitter.disabled = true;
    event.submitter.textContent = "Menyimpan…";
  });
}
