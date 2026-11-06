// Smoke test terhadap demo sintetis yang sudah berjalan di loopback.
const {
  chromium
} = require(process.env.PLAYWRIGHT_MODULE || "playwright");
const assert = require("node:assert/strict");
const path = require("node:path");
const base = process.env.DEMO_URL || "http://127.0.0.1:18765";
assert.equal(new URL(base).hostname, "127.0.0.1");

async function run() {
  const browser = await chromium.launch({
    headless: true,
    executablePath: process.env.CHROME_BIN || undefined
  });
  const errors = [];
  try {
    for (const [role, paths] of Object.entries({
        Pemilik: ["/", "/analisis/", "/laporan/", "/stok/", "/periode/", "/aktivitas/"],
        Gudang: ["/", "/dokumen/", "/buat/?jenis=Penerimaan", "/hari/", "/analisis/"],
        Penjualan: ["/", "/buat/?jenis=Penjualan", "/laporan/?jenis=pelanggan"],
        Keuangan: ["/", "/dana/", "/pembukaan/", "/laporan/?jenis=dana"],
        Admin: ["/master/", "/master/?jenis=pegawai&baru=1", "/master/?jenis=harga"]
      })) {
      const page = await browser.newPage({
        viewport: {
          width: 1440,
          height: 900
        }
      });
      page.on("pageerror", e => errors.push(String(e)));
      await page.goto(base + "/masuk/");
      if (role === "Pemilik" && process.env.QA_CAPTURE) {
        await page.screenshot({
          path: path.join(process.env.QA_CAPTURE, "distribusi-masuk.png")
        });
      }
      await page.locator(`input[name="role"][value="${role}"]`).check();
      await Promise.all([page.waitForURL(url => url.pathname !== "/masuk/"), page.getByRole("button", {
        name: "Masuk ke ruang kerja"
      }).click()]);
      const navigation = await page.locator("#sidebar nav a").evaluateAll(nodes => nodes.map(node => ({
        url: node.getAttribute("href"),
        label: node.querySelector("span").textContent
      })));
      if (role === "Pemilik") {
        assert.deepEqual(navigation.map(item => item.label), ["Ringkasan", "Pesanan", "Pelanggan", "Stok & Gudang", "Pembelian", "Pengiriman", "Retur", "Piutang", "Kas & Bank", "Pengisian Stok", "Fee Pemasaran", "Laporan", "Log Audit", "Data Master", "Pengaturan"]);
      }
      for (const url of new Set([...paths, ...navigation.map(item => item.url)])) {
        const response = await page.goto(base + url);
        assert.equal(response.status(), 200, role + " " + url);
        assert.ok(await page.locator("h1").innerText());
      }
      if (role === "Pemilik") {
        for (const width of [1440, 1024, 768, 390]) {
          await page.setViewportSize({
            width,
            height: 900
          });
          await page.goto(base + "/");
          assert.ok(await page.locator("#chart svg rect").count());
          if (width === 1440) {
            const daily = await page.locator("#chart svg rect").count();
            await page.selectOption("#chart-mode", "week");
            assert.ok(await page.locator("#chart svg rect").count() <= daily);
            await page.selectOption("#chart-mode", "day");
          }
          assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1), "Layout " + width);
          if (process.env.QA_CAPTURE && [1440, 390].includes(width)) {
            await page.screenshot({
              path: path.join(process.env.QA_CAPTURE, "distribusi-" + width + ".png")
            });
          }
          if (width === 390) {
            await page.getByRole("button", {
              name: "Buka navigasi"
            }).click();
            await page.locator("#sidebar").getByRole("link", {
              name: "Pengiriman",
              exact: true
            }).click();
            assert.equal(await page.locator("h1").innerText(), "Pengiriman");
          }
        }
      }
      if (role === "Gudang") {
        assert.equal((await page.goto(base + "/api/keuangan/")).status(), 403);
      }
      if (role === "Penjualan") {
        await page.goto(base + "/buat/?jenis=Penjualan");
        const product = page.locator("#lines select[name=product]");
        await product.selectOption({
          index: 1
        });
        await page.locator("#lines input[name=qty]").fill("2");
        await page.locator("#lines input[name=price]").fill("195000");
        await page.locator("#lines input[name=discount]").fill("10000");
        assert.match(await page.locator("#draft-total").innerText(), /380\.000/);
        await page.getByRole("button", {
          name: "Tambah baris"
        }).click();
        assert.equal(await page.locator("#draft-total").innerText(), "—");
        await page.getByRole("button", {
          name: "Hapus baris"
        }).click();
        assert.match(await page.locator("#draft-total").innerText(), /380\.000/);
      }
      await page.close();
      console.log(role + ": halaman dan akses selesai diuji");
    }
    assert.deepEqual(errors, []);
  } finally {
    await browser.close();
  }
}
run().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
