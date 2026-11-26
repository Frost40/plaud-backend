// Note renderer self-check: node tests/note_render_check.mjs
// Runs the dashboard's real renderer code (between the "// Notes:" and "// Mermaid loads" markers) against the vendored libs.
import { readFileSync } from "node:fs";
import vm from "node:vm";
import assert from "node:assert/strict";

const app = new URL("../app/", import.meta.url);
const html = readFileSync(new URL("dashboard.html", app), "utf8");
const code = html.slice(html.indexOf("// Notes: CommonMark"), html.indexOf("// Mermaid loads only"));
assert.ok(code.length > 500, "renderer markers not found in dashboard.html");
const ctx = vm.createContext({});
ctx.window = ctx;
for (const f of ["markdown-it.min.js", "markdown-it-mark.min.js"]) vm.runInContext(readFileSync(new URL("vendor/" + f, app), "utf8"), ctx);
vm.runInContext(`const esc = (s) => String(s ?? "").replace(/[&<>"']/g, c => ({ "&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;" }[c]));
  const obs = (p) => "obsidian://open?file=" + encodeURIComponent(p);` + code + "; globalThis.md = md;", ctx);
const md = ctx.md;

const out = md(`From [[Rec|alias]] ![[a.ogg]]

## One
- [ ] todo — *Ann*
- [x] done at \`12:05\`
  - nested

> [!important] ⭐ 45:13 Highlight
> body

> [!note]
> untitled

| a | b |
|---|---|
| 1 | $31,000 and $5 |

---
## Two
<script>alert(1)</script> [x](javascript:alert(1)) ==hi==

\`\`\`mermaid
mindmap
  root((Topic (big)))
    Branch A
      Leaf
    Branch B
\`\`\`
`);
const has = (s) => assert.ok(out.includes(s), "missing: " + s + "\n---\n" + out);
has(`<a class="wiki" href="obsidian://open?file=Rec">alias</a>`);
has(`<span class="embed">a.ogg</span>`);
has(`<section class="sec"><h3>One</h3>`);                     // ## -> h3, wrapped in a card
has(`</section><section class="sec"><h3>Two</h3>`);           // the --- before a section is dropped
assert.ok(!out.includes("<hr>"), "hr between sections should be dropped");
has(`<li class="task"><input type="checkbox" disabled aria-label="To do">todo`);
has(`<li class="task done"><input type="checkbox" disabled checked aria-label="Done">done at <button type="button" class="ts-chip" data-seek="725"`);
has(`<blockquote class="callout c-important">\n<p><span class="callout-title">⭐ <button type="button" class="ts-chip" data-seek="2713"`);
has(`<span class="callout-title">Note</span>untitled`);
has(`<div class="tablewrap"><table>`);
has(`$31,000 and $5`);                                          // no math mode eating currency
has(`&lt;script&gt;`);                                          // raw HTML stays text
assert.ok(!out.includes(`href="javascript`), "javascript: link must not render");
has(`<mark>hi</mark>`);
has(`<figure class="mm"`);
has(`<span class="mm-l">Topic (big)</span>`);
has(`<span class="mm-l">Leaf</span>`);
const titled = md("# Title\n\nintro\n\n## A\ntext\n\n## B\ntext");    // a lone # title stays outside; ## sections become cards
assert.ok(titled.startsWith("<h2>Title</h2>") && titled.split(`<section class="sec">`).length === 3, titled);
assert.ok(md("```mermaid\nflowchart LR\n A-->B\n```").includes(`<figure class="mmd" data-src=`), "non-mindmap goes to Mermaid");
console.log("note renderer: ok");
