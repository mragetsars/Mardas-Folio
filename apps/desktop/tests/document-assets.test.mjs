import test from "node:test";
import assert from "node:assert/strict";
import { documentImageSources, localImageDestination } from "../frontend/js/core/document-assets.mjs";

test("local image destinations share percent and Markdown escaping rules", () => {
  assert.equal(localImageDestination("assets/Persian%20chart.png"), "assets/Persian chart.png");
  assert.equal(localImageDestination("<assets/طرح صفحه.png>"), "assets/طرح صفحه.png");
  assert.equal(localImageDestination("assets/chart\\(1\\).png"), "assets/chart(1).png");
  assert.equal(localImageDestination("assets\\chart.png"), "assets/chart.png");
  assert.equal(localImageDestination("assets/chart.png?raw=1#detail"), "assets/chart.png");
  assert.equal(localImageDestination("assets/chart%23part.png"), "assets/chart#part.png");
});

test("external schemes, encoded traversal, absolute and invalid paths are excluded", () => {
  for (const value of ["https://host/image.png", "data:image/png;base64,x", "//host/img.png", "C:/img.png", "/img.png", "assets/%2e%2e/img.png", "%2f%2fhost/img.png", "x%00.png", "bad%ZZ.png"]) {
    assert.equal(localImageDestination(value), null, value);
  }
});

test("image scope only includes bounded unique destinations referenced by the document", () => {
  const text = `![one](assets/one.png) ![duplicate](assets/one.png)
![spaces](<assets/Persian chart.png>) ![title](assets/two.png "A chart")
![balanced](assets/chart(1).png) ![escaped](assets/chart\\(2\\).png)
![external](https://host/image.png) ![traversal](../image.png)
[referenced]: assets/reference%20image.png
`;
  assert.deepEqual(documentImageSources(text), ["assets/one.png", "assets/Persian chart.png", "assets/two.png", "assets/chart(1).png", "assets/chart(2).png", "assets/reference image.png"]);
  assert.equal(documentImageSources(text, { limit: 2 }).length, 2);
});
