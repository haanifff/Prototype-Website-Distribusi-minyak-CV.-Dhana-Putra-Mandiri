"use strict";
const chart = document.querySelector("#chart");
if (chart) {
  const raw = JSON.parse(document.querySelector("#chartdata").textContent);
  const mode = document.querySelector("#chart-mode");
  const number = new Intl.NumberFormat("id-ID");
  const compact = new Intl.NumberFormat("id-ID", {
    notation: "compact",
    maximumFractionDigits: 1
  });
  const ns = "http://www.w3.org/2000/svg";

  function svg(tag, attrs, content) {
    const node = document.createElementNS(ns, tag);
    Object.entries(attrs).forEach(([name, value]) => node.setAttribute(name, value));
    if (content !== undefined) node.textContent = content;
    return node;
  }

  function weekly() {
    const groups = new Map();
    for (const day of raw) {
      const monday = new Date(day.date + "T00:00:00Z");
      monday.setUTCDate(monday.getUTCDate() - (monday.getUTCDay() + 6) % 7);
      const key = monday.toISOString().slice(0, 10);
      if (!groups.has(key)) groups.set(key, {
        date: day.date,
        sales: 0,
        cost: 0
      });
      const week = groups.get(key);
      week.sales += day.sales;
      week.cost += day.cost;
      week.last = day.date;
    }
    return [...groups.values()];
  }
  const money = value => "Rp " + number.format(value);
  const short = iso => iso.slice(8) + "/" + iso.slice(5, 7);

  function draw() {
    const data = mode.value === "week" ? weekly() : raw;
    if (!data.length) return;
    const width = Math.max(240, chart.clientWidth - 26),
      left = 46,
      right = width - 15,
      top = 12,
      base = 126;
    const graph = svg("svg", {
      viewBox: "0 0 " + width + " 156",
      preserveAspectRatio: "none"
    });
    const range = data.flatMap(d => [d.sales, d.cost]);
    const min = Math.min(0, ...range),
      max = Math.max(1, ...range);
    const x = i => data.length === 1 ? (left + right) / 2 : left + (right - left) * i / (data.length - 1);
    const y = v => base - (base - top) * (v - min) / (max - min);
    for (let i = 0; i <= 3; i++) {
      const value = min + (max - min) * i / 3;
      graph.append(svg("line", {
        x1: left,
        x2: right,
        y1: y(value),
        y2: y(value),
        stroke: "var(--line)",
        "stroke-dasharray": "3 4"
      }), svg("text", {
        x: left - 7,
        y: y(value) + 3,
        "text-anchor": "end",
        "font-size": 10,
        fill: "var(--muted)"
      }, compact.format(value)));
    }
    const defs = svg("defs", {});
    const fill = svg("linearGradient", {
      id: "sales-fill",
      x1: "0",
      x2: "0",
      y1: "0",
      y2: "1"
    });
    fill.append(svg("stop", {
      offset: "0%",
      "stop-color": "var(--chart-sales)",
      "stop-opacity": ".27"
    }), svg("stop", {
      offset: "100%",
      "stop-color": "var(--chart-sales)",
      "stop-opacity": ".015"
    }));
    defs.append(fill);
    graph.append(defs);
    for (const [key, color] of [
        ["sales", "var(--chart-sales)"],
        ["cost", "var(--chart-cost)"]
      ]) {
      const line = data.map((d, i) => (i ? "L" : "M") + x(i) + " " + y(d[key])).join(" ");
      if (key === "sales") graph.append(svg("path", {
        d: line + " L" + x(data.length - 1) + " " + y(0) + " L" + x(0) + " " + y(0) + "Z",
        fill: "url(#sales-fill)"
      }));
      graph.append(svg("path", {
        d: line,
        fill: "none",
        stroke: color,
        "stroke-width": 2.5
      }));
      if (data.length <= 32) data.forEach((d, i) => graph.append(svg("circle", {
        cx: x(i),
        cy: y(d[key]),
        r: 3,
        fill: "white",
        stroke: color,
        "stroke-width": 1.7
      })));
    }
    const slots = Math.max(2, Math.min(7, Math.floor((right - left) / 48)));
    for (const i of new Set(Array.from({
        length: slots
      }, (_, k) => Math.round(k * (data.length - 1) / (slots - 1))))) {
      graph.append(svg("text", {
        x: x(i),
        y: 148,
        "font-size": 10,
        fill: "var(--muted)",
        "text-anchor": "middle"
      }, short(data[i].date)));
    }
    const tooltip = document.createElement("output");
    tooltip.className = "chart-tip";
    tooltip.hidden = true;
    const cursor = svg("line", {
      y1: top,
      y2: base,
      stroke: "var(--quiet)",
      "stroke-dasharray": "3 3",
      visibility: "hidden"
    });
    graph.append(cursor);

    function show(i) {
      const datum = data[i];
      cursor.setAttribute("x1", x(i));
      cursor.setAttribute("x2", x(i));
      cursor.setAttribute("visibility", "visible");
      tooltip.hidden = false;
      tooltip.textContent = short(datum.date) + (datum.last ? "â€“" + short(datum.last) : "") + " Â· Penjualan " + money(datum.sales) + " Â· HPP " + money(datum.cost);
    }

    function hide() {
      tooltip.hidden = true;
      cursor.setAttribute("visibility", "hidden");
    }
    const step = (right - left) / Math.max(1, data.length - 1);
    data.forEach((datum, i) => {
      const hit = svg("rect", {
        x: Math.max(left, x(i) - step / 2),
        y: top,
        width: data.length === 1 ? right - left : Math.min(right, x(i) + step / 2) - Math.max(left, x(i) - step / 2),
        height: base - top,
        fill: "transparent"
      });
      hit.addEventListener("pointerenter", () => show(i));
      graph.append(hit);
    });
    let active = 0;
    chart.onfocus = () => show(active);
    chart.onblur = hide;
    graph.addEventListener("pointerleave", hide);
    chart.onkeydown = e => {
      if (["ArrowLeft", "ArrowRight"].includes(e.key)) {
        e.preventDefault();
        active = Math.min(data.length - 1, Math.max(0, active + (e.key === "ArrowRight" ? 1 : -1)));
        show(active);
      }
    };
    chart.replaceChildren(graph, tooltip);
  }
  chart.tabIndex = 0;
  mode.addEventListener("change", draw);
  draw();
  new ResizeObserver(draw).observe(chart);
}
