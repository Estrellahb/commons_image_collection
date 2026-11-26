import { writeFile } from "node:fs/promises";
import { createRequire } from "node:module";
import { join } from "node:path";
import { pathToFileURL } from "node:url";

const [, , output, modules, preview] = process.argv;
const resolveFromRuntime = createRequire(join(modules, "zerobench-loader.cjs"));
const { Workbook, SpreadsheetFile } = await import(
  pathToFileURL(resolveFromRuntime.resolve("@oai/artifact-tool")).href
);

// Read stdin via its file descriptor (Windows and Unix).
const chunks = [];
for await (const chunk of process.stdin) chunks.push(chunk);
const rows = JSON.parse(Buffer.concat(chunks).toString("utf8"));
const wb = Workbook.create();
const sheet = wb.worksheets.add("图片分类");
sheet.showGridLines = false;
sheet.freezePanes.freezeRows(1);
sheet.tabColor = "#194353";
sheet.getRange("A:A").format.columnWidthPx = 252;
sheet.getRange("B:B").format.columnWidthPx = 242;

const header = sheet.getRange("A1:B1");
header.values = [["图片", "图片种类"]];
header.format = {
  fill: "#194353", font: {color: "#FFFFFF", bold: true, size: 11, name: "Microsoft YaHei"},
  horizontalAlignment: "center", verticalAlignment: "center", rowHeightPx: 34,
};

if (rows.length) {
  const body = sheet.getRangeByIndexes(1, 0, rows.length, 2);
  body.values = rows.map(([name, category]) => [name, category]);
  body.format = {
    font: {color: "#163744", size: 10, name: "Microsoft YaHei"},
    rowHeightPx: 112, verticalAlignment: "center", horizontalAlignment: "center",
    borders: {insideHorizontal: {style: "thin", color: "#D8E3E8"}},
  };
  sheet.getRangeByIndexes(1, 0, rows.length, 1).format.verticalAlignment = "bottom";
  rows.forEach(([, , width, height, dataUrl], i) => {
    if (i % 2 === 1) sheet.getRangeByIndexes(i + 1, 0, 1, 2).format.fill = "#F3F8F9";
    sheet.images.add({
      dataUrl,
      anchor: {
        from: {row: i + 1, col: 0, colOffsetPx: (252 - width) / 2, rowOffsetPx: 6 + (84 - height) / 2},
        extent: {widthPx: width, heightPx: height},
      },
    });
  });
}

wb.recalculate();
if (preview) {
  const range = `A1:B${Math.min(rows.length + 1, 5)}`;
  const view = await wb.render({sheetName: "图片分类", range, format: "png", scale: 1.3});
  await writeFile(preview, new Uint8Array(await view.arrayBuffer()));
}
const file = await SpreadsheetFile.exportXlsx(wb);
await file.save(output);
